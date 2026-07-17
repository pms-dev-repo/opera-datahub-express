from __future__ import annotations

"""QA comparator for the current Arrivals parser and ArrivalParserV2.

The comparator runs both parsers against the same PDF and produces:

- a console summary;
- row-count and confirmation-number checks;
- field-level differences keyed by confirmation number;
- an Excel workbook with summary, mismatches and both parser outputs.

Expected project modules
------------------------
Current parser:
    src.parsers.parser_odata_arr_detail.parse_odata_arr_detail

V2 parser:
    src.parsers.arrival_parser_v2.parse_odata_arr_detail_v2

Adjust the imports below if the files live in a different package.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
import argparse
import math

import pandas as pd

from src.parsers.parser_odata_arr_detail import parse_odata_arr_detail
from src.parsers.arrival_parser_v2 import parse_odata_arr_detail_v2


KEY_COLUMN = "confirmation_no"

BUSINESS_COLUMNS = [
    "room_no",
    "guest_name",
    "arrival_date",
    "departure_date",
    "room_type",
    "adults",
    "children",
    "rooms",
    "market_code",
    "source_code",
    "reservation_status",
    "arrival_group_date",
    "confirmation_no",
    "vip",
    "last_room",
    "arrival_time",
    "carrier_code",
    "method_of_arrival",
    "prev_stays",
    "prev_nights",
    "share_with",
    "accompanying_names",
    "observations",
]

IGNORED_COLUMNS = {
    "source_report",
    "source_file",
    "visual_band_id",
    "visual_shade",
    "visual_page_number",
    "visual_band_top",
    "visual_band_bottom",
}


@dataclass(frozen=True)
class ComparisonResult:
    old_rows: int
    new_rows: int
    old_unique_confirmations: int
    new_unique_confirmations: int
    missing_in_v2: tuple[int, ...]
    extra_in_v2: tuple[int, ...]
    duplicate_confirmations_old: tuple[int, ...]
    duplicate_confirmations_new: tuple[int, ...]
    compared_columns: tuple[str, ...]
    mismatch_count: int
    matching_reservations: int
    total_common_reservations: int

    @property
    def passed(self) -> bool:
        return (
            self.old_rows == self.new_rows
            and not self.missing_in_v2
            and not self.extra_in_v2
            and not self.duplicate_confirmations_old
            and not self.duplicate_confirmations_new
            and self.mismatch_count == 0
        )


def clean_scalar(value: Any) -> Any:
    """Normalize values so harmless dtype/whitespace differences do not fail QA."""
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    if isinstance(value, str):
        normalized = " ".join(value.replace("\ufffe", "").split()).strip()
        return normalized or None

    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if math.isnan(value):
            return None
        if value.is_integer():
            return int(value)
        return round(value, 8)

    return value


def normalize_confirmation(value: Any) -> int | None:
    value = clean_scalar(value)

    if value is None:
        return None

    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()

    if KEY_COLUMN not in normalized.columns:
        raise KeyError(
            f"Parser output does not contain required column: {KEY_COLUMN}"
        )

    normalized[KEY_COLUMN] = normalized[KEY_COLUMN].apply(
        normalize_confirmation
    )

    normalized = normalized[
        normalized[KEY_COLUMN].notna()
    ].copy()

    for column in normalized.columns:
        if column == KEY_COLUMN:
            continue
        normalized[column] = normalized[column].map(clean_scalar)

    return normalized.reset_index(drop=True)


def duplicate_confirmations(df: pd.DataFrame) -> tuple[int, ...]:
    duplicated = (
        df.loc[df[KEY_COLUMN].duplicated(keep=False), KEY_COLUMN]
        .dropna()
        .astype(int)
        .unique()
        .tolist()
    )
    return tuple(sorted(duplicated))


def select_columns(
    old_df: pd.DataFrame,
    new_df: pd.DataFrame,
    *,
    requested: Iterable[str] | None = None,
) -> list[str]:
    if requested:
        candidates = list(dict.fromkeys(requested))
    else:
        candidates = BUSINESS_COLUMNS

    return [
        column
        for column in candidates
        if (
            column not in IGNORED_COLUMNS
            and column in old_df.columns
            and column in new_df.columns
        )
    ]


def compare_parser_outputs(
    old_df: pd.DataFrame,
    new_df: pd.DataFrame,
    *,
    columns: Iterable[str] | None = None,
) -> tuple[ComparisonResult, pd.DataFrame, pd.DataFrame]:
    old_norm = normalize_dataframe(old_df)
    new_norm = normalize_dataframe(new_df)

    duplicate_old = duplicate_confirmations(old_norm)
    duplicate_new = duplicate_confirmations(new_norm)

    old_keys = set(old_norm[KEY_COLUMN].astype(int))
    new_keys = set(new_norm[KEY_COLUMN].astype(int))

    missing_in_v2 = tuple(sorted(old_keys - new_keys))
    extra_in_v2 = tuple(sorted(new_keys - old_keys))
    common_keys = sorted(old_keys & new_keys)

    compared_columns = select_columns(
        old_norm,
        new_norm,
        requested=columns,
    )

    # First occurrence is used for field comparison; duplicates are reported
    # separately and therefore still fail the overall validation.
    old_indexed = (
        old_norm.drop_duplicates(KEY_COLUMN, keep="first")
        .set_index(KEY_COLUMN)
    )
    new_indexed = (
        new_norm.drop_duplicates(KEY_COLUMN, keep="first")
        .set_index(KEY_COLUMN)
    )

    differences: list[dict[str, Any]] = []
    reservation_status_rows: list[dict[str, Any]] = []

    for confirmation_no in common_keys:
        reservation_mismatches = 0

        for column in compared_columns:
            old_value = clean_scalar(old_indexed.at[confirmation_no, column])
            new_value = clean_scalar(new_indexed.at[confirmation_no, column])

            if old_value != new_value:
                reservation_mismatches += 1
                differences.append(
                    {
                        "confirmation_no": confirmation_no,
                        "column": column,
                        "old_value": old_value,
                        "new_value": new_value,
                    }
                )

        reservation_status_rows.append(
            {
                "confirmation_no": confirmation_no,
                "status": (
                    "MATCH"
                    if reservation_mismatches == 0
                    else "DIFFERENT"
                ),
                "mismatch_columns": reservation_mismatches,
            }
        )

    reservation_status = pd.DataFrame(reservation_status_rows)
    differences_df = pd.DataFrame(
        differences,
        columns=[
            "confirmation_no",
            "column",
            "old_value",
            "new_value",
        ],
    )

    matching_reservations = int(
        (
            reservation_status["status"] == "MATCH"
        ).sum()
    ) if not reservation_status.empty else 0

    result = ComparisonResult(
        old_rows=len(old_norm),
        new_rows=len(new_norm),
        old_unique_confirmations=len(old_keys),
        new_unique_confirmations=len(new_keys),
        missing_in_v2=missing_in_v2,
        extra_in_v2=extra_in_v2,
        duplicate_confirmations_old=duplicate_old,
        duplicate_confirmations_new=duplicate_new,
        compared_columns=tuple(compared_columns),
        mismatch_count=len(differences_df),
        matching_reservations=matching_reservations,
        total_common_reservations=len(common_keys),
    )

    return result, differences_df, reservation_status


def summary_dataframe(result: ComparisonResult) -> pd.DataFrame:
    rows = [
        {
            "check": "Overall result",
            "old_parser": "",
            "v2_parser": "",
            "status": "PASS" if result.passed else "FAIL",
        },
        {
            "check": "Rows",
            "old_parser": result.old_rows,
            "v2_parser": result.new_rows,
            "status": (
                "OK"
                if result.old_rows == result.new_rows
                else "DIFFERENT"
            ),
        },
        {
            "check": "Unique confirmations",
            "old_parser": result.old_unique_confirmations,
            "v2_parser": result.new_unique_confirmations,
            "status": (
                "OK"
                if (
                    result.old_unique_confirmations
                    == result.new_unique_confirmations
                )
                else "DIFFERENT"
            ),
        },
        {
            "check": "Missing confirmations in V2",
            "old_parser": "",
            "v2_parser": ", ".join(map(str, result.missing_in_v2)),
            "status": "OK" if not result.missing_in_v2 else "FAIL",
        },
        {
            "check": "Extra confirmations in V2",
            "old_parser": "",
            "v2_parser": ", ".join(map(str, result.extra_in_v2)),
            "status": "OK" if not result.extra_in_v2 else "FAIL",
        },
        {
            "check": "Duplicates in old parser",
            "old_parser": ", ".join(
                map(str, result.duplicate_confirmations_old)
            ),
            "v2_parser": "",
            "status": (
                "OK"
                if not result.duplicate_confirmations_old
                else "FAIL"
            ),
        },
        {
            "check": "Duplicates in V2",
            "old_parser": "",
            "v2_parser": ", ".join(
                map(str, result.duplicate_confirmations_new)
            ),
            "status": (
                "OK"
                if not result.duplicate_confirmations_new
                else "FAIL"
            ),
        },
        {
            "check": "Field-level mismatches",
            "old_parser": "",
            "v2_parser": result.mismatch_count,
            "status": "OK" if result.mismatch_count == 0 else "FAIL",
        },
        {
            "check": "Fully matching common reservations",
            "old_parser": result.total_common_reservations,
            "v2_parser": result.matching_reservations,
            "status": (
                "OK"
                if (
                    result.matching_reservations
                    == result.total_common_reservations
                )
                else "DIFFERENT"
            ),
        },
        {
            "check": "Compared columns",
            "old_parser": "",
            "v2_parser": ", ".join(result.compared_columns),
            "status": "INFO",
        },
    ]

    return pd.DataFrame(rows)


def print_console_summary(result: ComparisonResult) -> None:
    width = 34

    def line(label: str, value: Any, ok: bool | None = None) -> None:
        suffix = ""
        if ok is True:
            suffix = "  OK"
        elif ok is False:
            suffix = "  FAIL"
        print(f"{label:.<{width}}{value}{suffix}")

    print()
    print("=" * 72)
    print("ARRIVALS PARSER COMPARISON")
    print("=" * 72)

    line(
        "Rows",
        f"{result.old_rows} / {result.new_rows}",
        result.old_rows == result.new_rows,
    )
    line(
        "Unique confirmations",
        (
            f"{result.old_unique_confirmations} / "
            f"{result.new_unique_confirmations}"
        ),
        (
            result.old_unique_confirmations
            == result.new_unique_confirmations
        ),
    )
    line(
        "Missing in V2",
        list(result.missing_in_v2) or "{}",
        not result.missing_in_v2,
    )
    line(
        "Extra in V2",
        list(result.extra_in_v2) or "{}",
        not result.extra_in_v2,
    )
    line(
        "Old parser duplicates",
        list(result.duplicate_confirmations_old) or "{}",
        not result.duplicate_confirmations_old,
    )
    line(
        "V2 duplicates",
        list(result.duplicate_confirmations_new) or "{}",
        not result.duplicate_confirmations_new,
    )
    line(
        "Field mismatches",
        result.mismatch_count,
        result.mismatch_count == 0,
    )
    line(
        "Matching reservations",
        (
            f"{result.matching_reservations} / "
            f"{result.total_common_reservations}"
        ),
        (
            result.matching_reservations
            == result.total_common_reservations
        ),
    )

    print("-" * 72)
    print("RESULT:", "PASS" if result.passed else "FAIL")
    print("=" * 72)
    print()


def export_comparison_workbook(
    output_path: str | Path,
    *,
    result: ComparisonResult,
    differences: pd.DataFrame,
    reservation_status: pd.DataFrame,
    old_df: pd.DataFrame,
    new_df: pd.DataFrame,
) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    missing_df = pd.DataFrame(
        {
            "confirmation_no": result.missing_in_v2,
            "issue": "Missing in V2",
        }
    )
    extra_df = pd.DataFrame(
        {
            "confirmation_no": result.extra_in_v2,
            "issue": "Extra in V2",
        }
    )

    with pd.ExcelWriter(destination, engine="openpyxl") as writer:
        summary_dataframe(result).to_excel(
            writer,
            sheet_name="summary",
            index=False,
        )
        differences.to_excel(
            writer,
            sheet_name="field_differences",
            index=False,
        )
        reservation_status.to_excel(
            writer,
            sheet_name="reservation_status",
            index=False,
        )
        missing_df.to_excel(
            writer,
            sheet_name="missing_in_v2",
            index=False,
        )
        extra_df.to_excel(
            writer,
            sheet_name="extra_in_v2",
            index=False,
        )
        old_df.to_excel(
            writer,
            sheet_name="old_parser_rows",
            index=False,
        )
        new_df.to_excel(
            writer,
            sheet_name="v2_parser_rows",
            index=False,
        )

    return destination


def compare_pdf(
    pdf_path: str | Path,
    *,
    output_path: str | Path | None = None,
    columns: Iterable[str] | None = None,
) -> ComparisonResult:
    source = Path(pdf_path)

    old_df = parse_odata_arr_detail(source)
    new_df = parse_odata_arr_detail_v2(source)

    result, differences, reservation_status = compare_parser_outputs(
        old_df,
        new_df,
        columns=columns,
    )

    print_console_summary(result)

    if not differences.empty:
        print("First field differences:")
        print(differences.head(20).to_string(index=False))
        print()

    if output_path is None:
        output_path = (
            Path("data/debug/ODATA_arr_detail")
            / f"{source.stem}_parser_comparison.xlsx"
        )

    destination = export_comparison_workbook(
        output_path,
        result=result,
        differences=differences,
        reservation_status=reservation_status,
        old_df=old_df,
        new_df=new_df,
    )

    print(f"Comparison workbook: {destination.resolve()}")

    return result


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare the current ODATA Arrivals parser against "
            "ArrivalParserV2."
        )
    )
    parser.add_argument(
        "pdf",
        type=Path,
        help="Path to an ODATA_arr_detail PDF.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Optional output path for the Excel comparison workbook.",
    )
    parser.add_argument(
        "--fail-on-difference",
        action="store_true",
        help=(
            "Return exit code 1 when the comparison is not a full PASS. "
            "Useful in CI."
        ),
    )
    return parser


def main() -> int:
    args = build_argument_parser().parse_args()

    result = compare_pdf(
        args.pdf,
        output_path=args.output,
    )

    if args.fail_on_difference and not result.passed:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
