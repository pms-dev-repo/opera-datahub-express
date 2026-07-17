from __future__ import annotations

"""Generic parser comparator based on a pandas merge.

Default use compares:
- src.parsers.parser_odata_arr_detail.parse_odata_arr_detail
- src.parsers.arrival_parser_v2.parse_odata_arr_detail_v2

The implementation is intentionally generic so it can later be reused for
Departures, Transportation, Snapshot, or any parser pair returning DataFrames.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable
import argparse
import math

import pandas as pd

from src.parsers.parser_odata_arr_detail import parse_odata_arr_detail
from src.parsers.arrival_parser_v2 import parse_odata_arr_detail_v2


ParserFunction = Callable[[str | Path], pd.DataFrame]

DEFAULT_KEY = "confirmation_no"

DEFAULT_COLUMNS = [
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

DEFAULT_IGNORED_COLUMNS = {
    "source_report",
    "source_file",
    "visual_band_id",
    "visual_shade",
    "visual_page_number",
    "visual_band_top",
    "visual_band_bottom",
}


@dataclass(frozen=True)
class ComparisonSummary:
    old_rows: int
    new_rows: int
    old_unique_keys: int
    new_unique_keys: int
    old_duplicates: tuple[Any, ...]
    new_duplicates: tuple[Any, ...]
    missing_in_v2: tuple[Any, ...]
    extra_in_v2: tuple[Any, ...]
    compared_columns: tuple[str, ...]
    field_mismatches: int
    matching_common_rows: int
    common_rows: int

    @property
    def passed(self) -> bool:
        return (
            self.old_rows == self.new_rows
            and not self.old_duplicates
            and not self.new_duplicates
            and not self.missing_in_v2
            and not self.extra_in_v2
            and self.field_mismatches == 0
        )


def clean_scalar(value: Any) -> Any:
    """Normalize harmless dtype, NaN and whitespace differences."""
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    if isinstance(value, str):
        normalized = " ".join(
            value.replace("\ufffe", "").split()
        ).strip()
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


def normalize_key(value: Any) -> Any:
    value = clean_scalar(value)

    if value is None:
        return None

    text = str(value).strip()

    try:
        number = float(text)
        if number.is_integer():
            return int(number)
    except (TypeError, ValueError):
        pass

    return text


def normalize_dataframe(
    dataframe: pd.DataFrame,
    *,
    key_column: str,
) -> pd.DataFrame:
    df = dataframe.copy()

    if key_column not in df.columns:
        raise KeyError(
            f"Parser output does not contain required key column: "
            f"{key_column}"
        )

    df[key_column] = df[key_column].map(normalize_key)
    df = df[df[key_column].notna()].copy()

    for column in df.columns:
        if column == key_column:
            continue
        df[column] = df[column].map(clean_scalar)

    return df.reset_index(drop=True)


def duplicate_keys(
    dataframe: pd.DataFrame,
    *,
    key_column: str,
) -> tuple[Any, ...]:
    values = (
        dataframe.loc[
            dataframe[key_column].duplicated(keep=False),
            key_column,
        ]
        .dropna()
        .unique()
        .tolist()
    )

    try:
        return tuple(sorted(values))
    except TypeError:
        return tuple(sorted(values, key=str))


def choose_columns(
    old_df: pd.DataFrame,
    new_df: pd.DataFrame,
    *,
    key_column: str,
    requested_columns: Iterable[str] | None = None,
    ignored_columns: Iterable[str] | None = None,
) -> list[str]:
    candidates = list(
        dict.fromkeys(
            requested_columns
            if requested_columns is not None
            else DEFAULT_COLUMNS
        )
    )

    ignored = set(
        ignored_columns
        if ignored_columns is not None
        else DEFAULT_IGNORED_COLUMNS
    )

    return [
        column
        for column in candidates
        if (
            column != key_column
            and column not in ignored
            and column in old_df.columns
            and column in new_df.columns
        )
    ]


def compare_dataframes(
    old_df: pd.DataFrame,
    new_df: pd.DataFrame,
    *,
    key_column: str = DEFAULT_KEY,
    columns: Iterable[str] | None = None,
    ignored_columns: Iterable[str] | None = None,
) -> tuple[
    ComparisonSummary,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    old_norm = normalize_dataframe(
        old_df,
        key_column=key_column,
    )
    new_norm = normalize_dataframe(
        new_df,
        key_column=key_column,
    )

    old_duplicates = duplicate_keys(
        old_norm,
        key_column=key_column,
    )
    new_duplicates = duplicate_keys(
        new_norm,
        key_column=key_column,
    )

    compared_columns = choose_columns(
        old_norm,
        new_norm,
        key_column=key_column,
        requested_columns=columns,
        ignored_columns=ignored_columns,
    )

    old_unique = old_norm.drop_duplicates(
        subset=[key_column],
        keep="first",
    )
    new_unique = new_norm.drop_duplicates(
        subset=[key_column],
        keep="first",
    )

    merged = old_unique.merge(
        new_unique,
        on=key_column,
        how="outer",
        suffixes=("_old", "_v2"),
        indicator=True,
        validate="one_to_one",
    )

    missing_in_v2 = tuple(
        merged.loc[
            merged["_merge"] == "left_only",
            key_column,
        ].tolist()
    )
    extra_in_v2 = tuple(
        merged.loc[
            merged["_merge"] == "right_only",
            key_column,
        ].tolist()
    )

    common = merged[
        merged["_merge"] == "both"
    ].copy()

    difference_rows: list[dict[str, Any]] = []
    row_status_rows: list[dict[str, Any]] = []

    for _, row in common.iterrows():
        key_value = row[key_column]
        mismatch_columns: list[str] = []

        for column in compared_columns:
            old_value = clean_scalar(row.get(f"{column}_old"))
            new_value = clean_scalar(row.get(f"{column}_v2"))

            if old_value != new_value:
                mismatch_columns.append(column)
                difference_rows.append(
                    {
                        key_column: key_value,
                        "column": column,
                        "old_value": old_value,
                        "v2_value": new_value,
                    }
                )

        row_status_rows.append(
            {
                key_column: key_value,
                "status": (
                    "MATCH"
                    if not mismatch_columns
                    else "DIFFERENT"
                ),
                "mismatch_count": len(mismatch_columns),
                "mismatch_columns": ", ".join(mismatch_columns),
            }
        )

    differences = pd.DataFrame(
        difference_rows,
        columns=[
            key_column,
            "column",
            "old_value",
            "v2_value",
        ],
    )

    row_status = pd.DataFrame(
        row_status_rows,
        columns=[
            key_column,
            "status",
            "mismatch_count",
            "mismatch_columns",
        ],
    )

    matching_common_rows = (
        int((row_status["status"] == "MATCH").sum())
        if not row_status.empty
        else 0
    )

    summary = ComparisonSummary(
        old_rows=len(old_norm),
        new_rows=len(new_norm),
        old_unique_keys=old_norm[key_column].nunique(),
        new_unique_keys=new_norm[key_column].nunique(),
        old_duplicates=old_duplicates,
        new_duplicates=new_duplicates,
        missing_in_v2=missing_in_v2,
        extra_in_v2=extra_in_v2,
        compared_columns=tuple(compared_columns),
        field_mismatches=len(differences),
        matching_common_rows=matching_common_rows,
        common_rows=len(common),
    )

    return summary, differences, row_status, merged


def build_summary_table(
    summary: ComparisonSummary,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "check": "Overall result",
                "old_parser": "",
                "v2_parser": "",
                "status": "PASS" if summary.passed else "FAIL",
            },
            {
                "check": "Rows",
                "old_parser": summary.old_rows,
                "v2_parser": summary.new_rows,
                "status": (
                    "OK"
                    if summary.old_rows == summary.new_rows
                    else "DIFFERENT"
                ),
            },
            {
                "check": "Unique keys",
                "old_parser": summary.old_unique_keys,
                "v2_parser": summary.new_unique_keys,
                "status": (
                    "OK"
                    if summary.old_unique_keys == summary.new_unique_keys
                    else "DIFFERENT"
                ),
            },
            {
                "check": "Duplicates",
                "old_parser": ", ".join(
                    map(str, summary.old_duplicates)
                ),
                "v2_parser": ", ".join(
                    map(str, summary.new_duplicates)
                ),
                "status": (
                    "OK"
                    if (
                        not summary.old_duplicates
                        and not summary.new_duplicates
                    )
                    else "FAIL"
                ),
            },
            {
                "check": "Missing in V2",
                "old_parser": "",
                "v2_parser": ", ".join(
                    map(str, summary.missing_in_v2)
                ),
                "status": (
                    "OK"
                    if not summary.missing_in_v2
                    else "FAIL"
                ),
            },
            {
                "check": "Extra in V2",
                "old_parser": "",
                "v2_parser": ", ".join(
                    map(str, summary.extra_in_v2)
                ),
                "status": (
                    "OK"
                    if not summary.extra_in_v2
                    else "FAIL"
                ),
            },
            {
                "check": "Field mismatches",
                "old_parser": "",
                "v2_parser": summary.field_mismatches,
                "status": (
                    "OK"
                    if summary.field_mismatches == 0
                    else "FAIL"
                ),
            },
            {
                "check": "Matching common rows",
                "old_parser": summary.common_rows,
                "v2_parser": summary.matching_common_rows,
                "status": (
                    "OK"
                    if summary.matching_common_rows == summary.common_rows
                    else "DIFFERENT"
                ),
            },
            {
                "check": "Compared columns",
                "old_parser": "",
                "v2_parser": ", ".join(summary.compared_columns),
                "status": "INFO",
            },
        ]
    )


def build_column_summary(
    differences: pd.DataFrame,
) -> pd.DataFrame:
    if differences.empty:
        return pd.DataFrame(
            columns=["column", "mismatch_count"]
        )

    return (
        differences.groupby("column", dropna=False)
        .size()
        .reset_index(name="mismatch_count")
        .sort_values(
            ["mismatch_count", "column"],
            ascending=[False, True],
        )
        .reset_index(drop=True)
    )


def print_summary(summary: ComparisonSummary) -> None:
    width = 34

    def show(
        label: str,
        value: Any,
        success: bool,
    ) -> None:
        print(
            f"{label:.<{width}}"
            f"{value}  "
            f"{'OK' if success else 'FAIL'}"
        )

    print()
    print("=" * 72)
    print("PARSER COMPARISON")
    print("=" * 72)

    show(
        "Rows",
        f"{summary.old_rows} / {summary.new_rows}",
        summary.old_rows == summary.new_rows,
    )
    show(
        "Unique keys",
        (
            f"{summary.old_unique_keys} / "
            f"{summary.new_unique_keys}"
        ),
        summary.old_unique_keys == summary.new_unique_keys,
    )
    show(
        "Old duplicates",
        list(summary.old_duplicates) or "{}",
        not summary.old_duplicates,
    )
    show(
        "V2 duplicates",
        list(summary.new_duplicates) or "{}",
        not summary.new_duplicates,
    )
    show(
        "Missing in V2",
        list(summary.missing_in_v2) or "{}",
        not summary.missing_in_v2,
    )
    show(
        "Extra in V2",
        list(summary.extra_in_v2) or "{}",
        not summary.extra_in_v2,
    )
    show(
        "Field mismatches",
        summary.field_mismatches,
        summary.field_mismatches == 0,
    )
    show(
        "Matching common rows",
        (
            f"{summary.matching_common_rows} / "
            f"{summary.common_rows}"
        ),
        summary.matching_common_rows == summary.common_rows,
    )

    print("-" * 72)
    print("RESULT:", "PASS" if summary.passed else "FAIL")
    print("=" * 72)
    print()


def export_workbook(
    output_path: str | Path,
    *,
    summary: ComparisonSummary,
    differences: pd.DataFrame,
    row_status: pd.DataFrame,
    merged: pd.DataFrame,
    old_df: pd.DataFrame,
    new_df: pd.DataFrame,
    key_column: str,
) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    missing = merged[
        merged["_merge"] == "left_only"
    ].copy()
    extra = merged[
        merged["_merge"] == "right_only"
    ].copy()

    with pd.ExcelWriter(
        destination,
        engine="openpyxl",
    ) as writer:
        build_summary_table(summary).to_excel(
            writer,
            sheet_name="summary",
            index=False,
        )
        build_column_summary(differences).to_excel(
            writer,
            sheet_name="column_summary",
            index=False,
        )
        differences.to_excel(
            writer,
            sheet_name="field_differences",
            index=False,
        )
        row_status.to_excel(
            writer,
            sheet_name="row_status",
            index=False,
        )
        missing.to_excel(
            writer,
            sheet_name="missing_in_v2",
            index=False,
        )
        extra.to_excel(
            writer,
            sheet_name="extra_in_v2",
            index=False,
        )
        merged.to_excel(
            writer,
            sheet_name="merged_comparison",
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

        workbook = writer.book
        for worksheet in workbook.worksheets:
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions

    return destination


def compare_parsers(
    source_path: str | Path,
    *,
    old_parser: ParserFunction,
    new_parser: ParserFunction,
    key_column: str = DEFAULT_KEY,
    columns: Iterable[str] | None = None,
    ignored_columns: Iterable[str] | None = None,
    output_path: str | Path | None = None,
) -> ComparisonSummary:
    source = Path(source_path)

    old_df = old_parser(source)
    new_df = new_parser(source)

    summary, differences, row_status, merged = compare_dataframes(
        old_df,
        new_df,
        key_column=key_column,
        columns=columns,
        ignored_columns=ignored_columns,
    )

    print_summary(summary)

    if not differences.empty:
        print("First field differences:")
        print(differences.head(25).to_string(index=False))
        print()

        column_summary = build_column_summary(differences)
        print("Differences by column:")
        print(column_summary.to_string(index=False))
        print()

    if output_path is None:
        output_path = (
            Path("data/debug/ODATA_arr_detail")
            / f"{source.stem}_parser_comparison_v2.xlsx"
        )

    destination = export_workbook(
        output_path,
        summary=summary,
        differences=differences,
        row_status=row_status,
        merged=merged,
        old_df=old_df,
        new_df=new_df,
        key_column=key_column,
    )

    print(f"Comparison workbook: {destination.resolve()}")

    return summary


def compare_arrivals_pdf(
    source_path: str | Path,
    *,
    output_path: str | Path | None = None,
) -> ComparisonSummary:
    return compare_parsers(
        source_path,
        old_parser=parse_odata_arr_detail,
        new_parser=parse_odata_arr_detail_v2,
        key_column="confirmation_no",
        columns=DEFAULT_COLUMNS,
        ignored_columns=DEFAULT_IGNORED_COLUMNS,
        output_path=output_path,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare the current Arrivals parser against ArrivalParserV2."
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
        help="Optional Excel output path.",
    )
    parser.add_argument(
        "--fail-on-difference",
        action="store_true",
        help="Return exit code 1 when the comparison does not pass.",
    )
    return parser


def main() -> int:
    args = build_argument_parser().parse_args()

    summary = compare_arrivals_pdf(
        args.pdf,
        output_path=args.output,
    )

    if args.fail_on_difference and not summary.passed:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
