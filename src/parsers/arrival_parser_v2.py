from __future__ import annotations

"""Arrivals parser V2 based on reservation-level blocks.

Pipeline
--------
PDF -> PdfEngine -> ReservationBlockBuilder -> ArrivalParserV2 -> DataFrame

This parser contains only report/business interpretation. PDF geometry and
visual grouping remain in ``src.core.pdf``.
"""

from datetime import datetime
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from src.core.pdf.pdf_engine import PdfEngine
from src.core.pdf.reservation_block_builder import ReservationBlockBuilder


REPORT_NAME = "ODATA_arr_detail"
TARGET_TABLE = "odata_arr_detail"

DATE_RE = re.compile(r"\d{2}-\d{2}-\d{2}")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")

METHOD_OPTIONS = {
    "VAN",
    "VAN/LUG",
    "MER",
    "OWN",
    "EXE/LUG",
    "SCON",
}

KNOWN_VIP_CODES = {
    "NEW",
    "PRE",
    "PLAT",
    "T",
    "C",
    "CT",
}

FINAL_COLUMNS = [
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
    "source_report",
    "source_file",
]


class ArrivalParserError(RuntimeError):
    """Raised when a reservation block cannot be interpreted safely."""


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    text = str(value).replace("\ufffe", "").strip()

    if text.startswith("*"):
        text = text[1:]

    return re.sub(r"\s+", " ", text).strip()


def clean_guest_name(value: Any) -> str:
    text = clean_text(value)
    text = re.split(
        r"\s+[SCTG]-\s*",
        text,
        maxsplit=1,
    )[0]
    return text.strip()


def to_iso_date(value: Any) -> str | None:
    text = clean_text(value)

    if not text:
        return None

    # Builder already normalizes the arrival-group date to ISO.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text

    try:
        return datetime.strptime(text, "%d-%m-%y").date().isoformat()
    except ValueError:
        return None


def to_int(value: Any) -> int | None:
    text = clean_text(value)

    if not text:
        return None

    try:
        return int(float(text.replace(",", "")))
    except (TypeError, ValueError):
        return None


def line_text(line: Any) -> str:
    if line is None:
        return ""

    if isinstance(line, str):
        return clean_text(line)

    if isinstance(line, Mapping):
        return clean_text(line.get("text"))

    return clean_text(getattr(line, "text", ""))


def block_value(block: Any, name: str, default: Any = None) -> Any:
    if isinstance(block, Mapping):
        return block.get(name, default)
    return getattr(block, name, default)


def parse_main_line(text: str) -> dict[str, Any]:
    """Parse the reservation's first report line."""
    text = clean_text(text)
    dates = DATE_RE.findall(text)

    if len(dates) < 2:
        return {}

    arrival_date, departure_date = dates[:2]

    before_arrival = text.split(arrival_date, 1)[0].strip()
    after_departure = text.split(departure_date, 1)[1].strip()

    before_tokens = before_arrival.split()
    if len(before_tokens) < 2:
        return {}

    room_no = before_tokens[0]
    name_company = " ".join(before_tokens[1:]).strip()
    guest_name = clean_guest_name(name_company)

    tail = after_departure.split()

    return {
        "room_no": room_no,
        "guest_name": guest_name,
        "arrival_date": arrival_date,
        "departure_date": departure_date,
        "room_type": tail[0] if len(tail) > 0 else "",
        "adults": tail[1] if len(tail) > 1 else "",
        "children": tail[2] if len(tail) > 2 else "",
        "rooms": tail[3] if len(tail) > 3 else "",
        "market_code": tail[4] if len(tail) > 4 else "",
        "source_code": tail[5] if len(tail) > 5 else "",
        "reservation_status": tail[6] if len(tail) > 6 else "",
    }


def _looks_like_flight(value: str) -> bool:
    normalized = clean_text(value).upper().replace(" ", "")
    return re.match(r"^[A-Z0-9]{2,}\d+$", normalized) is not None


def parse_detail_line(text: str) -> dict[str, Any]:
    """Parse confirmation, VIP, room history, arrival and transport fields."""
    text = clean_text(text)
    tokens = text.split()

    if not tokens or not re.fullmatch(r"\d{6,}", tokens[0]):
        return {}

    confirmation_no = tokens[0]
    body = tokens[1:]

    prev_stays = ""
    prev_nights = ""

    if (
        len(body) >= 2
        and re.fullmatch(r"-?\d+", body[-2])
        and re.fullmatch(r"-?\d+", body[-1])
    ):
        prev_stays, prev_nights = body[-2:]
        body = body[:-2]

    time_index = next(
        (
            index
            for index, token in enumerate(body)
            if TIME_RE.fullmatch(token)
        ),
        None,
    )
    method_index = next(
        (
            index
            for index, token in enumerate(body)
            if token.upper() in METHOD_OPTIONS
        ),
        None,
    )

    arrival_time = body[time_index] if time_index is not None else ""
    method_of_arrival = (
        body[method_index].upper()
        if method_index is not None
        else ""
    )

    boundary_candidates = [
        index
        for index in (time_index, method_index)
        if index is not None
    ]
    first_boundary = (
        min(boundary_candidates)
        if boundary_candidates
        else len(body)
    )

    prefix = list(body[:first_boundary])
    vip = ""

    if prefix and clean_text(prefix[0]).upper() in KNOWN_VIP_CODES:
        vip = clean_text(prefix.pop(0)).upper()

    last_room = ""
    carrier_code = ""

    if time_index is not None:
        if prefix:
            last_room = " ".join(prefix).strip()

        carrier_start = time_index + 1
        carrier_end = (
            method_index
            if method_index is not None and method_index > time_index
            else len(body)
        )

        if carrier_start < carrier_end:
            carrier_code = " ".join(body[carrier_start:carrier_end]).strip()

    elif method_index is not None:
        before_method = list(body[:method_index])

        if before_method and clean_text(before_method[0]).upper() in KNOWN_VIP_CODES:
            if not vip:
                vip = clean_text(before_method[0]).upper()
            before_method = before_method[1:]

        if len(before_method) == 1:
            if _looks_like_flight(before_method[0]):
                carrier_code = before_method[0]
            else:
                last_room = before_method[0]

        elif before_method:
            if _looks_like_flight(before_method[0]):
                carrier_code = " ".join(before_method).strip()
            else:
                last_room = before_method[0]
                carrier_code = " ".join(before_method[1:]).strip()

    else:
        remaining = list(body)

        if remaining and clean_text(remaining[0]).upper() in KNOWN_VIP_CODES:
            if not vip:
                vip = clean_text(remaining[0]).upper()
            remaining = remaining[1:]

        if remaining:
            last_room = remaining[0]
        if len(remaining) > 1:
            carrier_code = " ".join(remaining[1:]).strip()

    return {
        "confirmation_no": confirmation_no,
        "vip": vip,
        "last_room": last_room,
        "arrival_time": arrival_time,
        "carrier_code": carrier_code,
        "method_of_arrival": method_of_arrival,
        "prev_stays": prev_stays,
        "prev_nights": prev_nights,
    }


def _strip_section_label(text: str, labels: Sequence[str]) -> str:
    value = clean_text(text)

    for label in labels:
        value = re.sub(
            rf"^{re.escape(label)}\s*:\s*",
            "",
            value,
            count=1,
            flags=re.IGNORECASE,
        )

    return clean_text(value)


def _join_section_lines(
    lines: Iterable[Any],
    labels: Sequence[str],
) -> str:
    values: list[str] = []

    for line in lines:
        value = _strip_section_label(line_text(line), labels)
        if value:
            values.append(value)

    return " | ".join(values)


class ArrivalParserV2:
    """Interpret typed reservation blocks as ODATA Arrivals rows."""

    def __init__(self, *, strict: bool = False) -> None:
        self.strict = bool(strict)
        self.warnings: list[dict[str, Any]] = []

    def parse_blocks(
        self,
        reservation_blocks: Iterable[Any],
        *,
        source_file: str = "",
    ) -> pd.DataFrame:
        self.warnings = []
        rows: list[dict[str, Any]] = []

        for block in reservation_blocks:
            parsed = self.parse_block(block, source_file=source_file)

            if parsed:
                rows.append(parsed)

        return self._normalize_dataframe(pd.DataFrame(rows))

    def parse_block(
        self,
        block: Any,
        *,
        source_file: str = "",
    ) -> dict[str, Any] | None:
        main_text = line_text(block_value(block, "main_line"))
        detail_text = line_text(block_value(block, "detail_line"))

        main = parse_main_line(main_text)
        detail = parse_detail_line(detail_text)

        if not main or not detail:
            warning = {
                "page": block_value(block, "page"),
                "block_id": block_value(block, "block_id"),
                "main_line": main_text,
                "detail_line": detail_text,
                "reason": (
                    "main_line_not_parsed"
                    if not main
                    else "detail_line_not_parsed"
                ),
            }
            self.warnings.append(warning)

            if self.strict:
                raise ArrivalParserError(str(warning))
            return None

        share_with = _join_section_lines(
            block_value(block, "share_lines", []) or [],
            ("Share with", "Share With", "Sharers", "Sharing With"),
        )
        accompanying_names = _join_section_lines(
            block_value(block, "accompanying_lines", []) or [],
            ("Accompanying Name", "Accompanying Names"),
        )

        arrival_group = block_value(block, "arrival_group", "")

        return {
            **main,
            **detail,
            "arrival_group_date": arrival_group,
            "share_with": share_with,
            "accompanying_names": accompanying_names,
            "source_report": REPORT_NAME,
            "source_file": source_file,
        }

    @staticmethod
    def _normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(columns=FINAL_COLUMNS)

        df = df[
            df["confirmation_no"]
            .astype(str)
            .str.fullmatch(r"\d{6,}", na=False)
        ].copy()

        df = df.drop_duplicates(
            subset=["confirmation_no", "guest_name"],
            keep="first",
        )

        if "guest_name" in df.columns:
            df["guest_name"] = (
                df["guest_name"]
                .fillna("")
                .apply(clean_guest_name)
            )

        text_columns = [
            "room_type",
            "market_code",
            "source_code",
            "reservation_status",
            "vip",
            "last_room",
            "arrival_time",
            "carrier_code",
            "method_of_arrival",
            "share_with",
            "accompanying_names",
            "source_report",
            "source_file",
        ]

        for column in text_columns:
            if column in df.columns:
                df[column] = df[column].fillna("").apply(clean_text)

        for column in (
            "arrival_date",
            "departure_date",
            "arrival_group_date",
        ):
            if column in df.columns:
                df[column] = df[column].apply(to_iso_date)

        for column in (
            "room_no",
            "adults",
            "children",
            "rooms",
            "confirmation_no",
            "prev_stays",
            "prev_nights",
        ):
            if column in df.columns:
                df[column] = df[column].apply(to_int)

        for column in FINAL_COLUMNS:
            if column not in df.columns:
                df[column] = None

        return df[FINAL_COLUMNS].reset_index(drop=True)


def parse_odata_arr_detail_v2(
    pdf_path: str | Path,
    *,
    strict: bool = False,
) -> pd.DataFrame:
    """Parse one ODATA Arrivals Detail PDF with the new pipeline."""
    path = Path(pdf_path)

    engine = PdfEngine(path)
    builder = ReservationBlockBuilder(strict=strict)
    blocks = builder.build_from_engine(engine)

    parser = ArrivalParserV2(strict=strict)
    return parser.parse_blocks(
        blocks,
        source_file=path.name,
    )


def export_debug_v2(
    pdf_path: str | Path,
    output_path: str | Path = (
        "data/debug/ODATA_arr_detail/"
        "odata_arr_detail_v2_debug.xlsx"
    ),
    *,
    strict: bool = False,
) -> Path:
    """Export engine, reservation-block and parsed-row diagnostics."""
    path = Path(pdf_path)
    destination = Path(output_path)

    engine = PdfEngine(path)
    builder = ReservationBlockBuilder(strict=strict)
    reservation_blocks = builder.build_from_engine(engine)

    parser = ArrivalParserV2(strict=strict)
    parsed = parser.parse_blocks(
        reservation_blocks,
        source_file=path.name,
    )

    warnings = [
        *builder.warnings,
        *parser.warnings,
    ]

    return engine.export_debug(
        destination,
        reservation_blocks=reservation_blocks,
        parsed_rows=parsed,
        warnings=warnings,
    )


if __name__ == "__main__":
    patterns = (
        "ODATA_arr_detail*.pdf",
        "ODATA_arr_detail*.PDF",
        "odata_arr_detail*.pdf",
        "odata_arr_detail*.PDF",
    )

    files: list[Path] = []

    for pattern in patterns:
        files.extend(Path("data/incoming").glob(pattern))

    if not files:
        raise FileNotFoundError(
            "No ODATA_arr_detail PDF was found in data/incoming"
        )

    source = sorted(set(files))[0]

    print(f"Using: {source.name}")

    dataframe = parse_odata_arr_detail_v2(source)
    print(dataframe)
    print(f"Rows: {len(dataframe)}")

    output = export_debug_v2(source)
    print(f"Debug exported: {output.resolve()}")
