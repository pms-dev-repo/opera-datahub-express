from __future__ import annotations

from pathlib import Path
from datetime import datetime
from typing import Any
import re

import pandas as pd

from .pdf_engine import PdfEngine


REPORT_NAME = "ODATA_arr_detail"
TARGET_TABLE = "odata_arr_detail"

DATE_RE = re.compile(r"\d{2}-\d{2}-\d{2}")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
ROOM_LINE_RE = re.compile(r"^\d{2,5}\s+")
DETAIL_LINE_RE = re.compile(r"^\d{6,}\s+")

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

SECTION_LABELS = {
    "Share with:": "share_with",
    "Accompanying Names:": "accompanying_names",
    "Observations:": "observations",
    "Observation:": "observations",
    "Notes:": "observations",
    "Note:": "observations",
    "Comments:": "observations",
    "Comment:": "observations",
    "Remarks:": "observations",
    "Remark:": "observations",
}

HARD_STOP_MARKERS = (
    "Filter Arrival",
    "Room Class",
    "Room Types",
    "Rate Code",
    "Market Code",
    "Membership Type",
    "Membership Level",
    "From Arrival Time",
    "To Arrival Time",
    "Stay Statistics",
    "Include Checked",
    "Room Assignment",
    "Sandy Lane",
    "ODATA_arr_detail",
    "Page ",
    "Arrival Date Total",
    "Grand Total",
)

COLUMN_HEADER_MARKERS = (
    "Room Name",
    "Name Company",
    "Room Type",
    "Mkt. Code",
    "Src. Code",
    "Res. Status",
    "Block Code",
    "Arr. Time",
    "Carr. Code",
    "Travel Agent",
    "Conf No.",
    "ETD C/H",
    "Prev. Stays",
    "Prev. Nts.",
    "Last Room",
    "Method of Arrival",
)


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    value = str(value).replace("\ufffe", "").strip()

    if value.startswith("*"):
        value = value[1:]

    return re.sub(r"\s+", " ", value).strip()


def clean_guest_name(value: Any) -> str:
    value = clean_text(value)

    value = re.split(
        r"\s+[SCTG]-\s*",
        value,
        maxsplit=1,
    )[0]

    return value.strip()


def to_iso_date(value: Any) -> str | None:
    value = clean_text(value)

    if not value:
        return None

    try:
        return datetime.strptime(
            value,
            "%d-%m-%y",
        ).date().isoformat()
    except Exception:
        return None


def to_int(value: Any):
    value = clean_text(value)

    if not value:
        return None

    try:
        return int(float(value.replace(",", "")))
    except Exception:
        return None


def is_hard_stop(text: str) -> bool:
    text = clean_text(text)
    return any(marker in text for marker in HARD_STOP_MARKERS)


def is_column_header(text: str) -> bool:
    text = clean_text(text)

    if not text:
        return True

    if text in {
        "Name",
        "Company",
        "Chl.",
        "Rms.",
        "Adl.",
        "VIP",
        "Source",
    }:
        return True

    return any(marker in text for marker in COLUMN_HEADER_MARKERS)


def is_arrival_group_header(text: str) -> bool:
    text = clean_text(text)

    if not text.startswith("Arrival Date"):
        return False

    return bool(DATE_RE.search(text))


def parse_main_line(text: str) -> dict[str, Any]:
    text = clean_text(text)
    dates = DATE_RE.findall(text)

    if len(dates) < 2:
        return {}

    arrival_date = dates[0]
    departure_date = dates[1]

    before_arrival = text.split(arrival_date, 1)[0].strip()
    after_departure = text.split(departure_date, 1)[1].strip()

    before_tokens = before_arrival.split()

    if not before_tokens:
        return {}

    room_no = before_tokens[0]
    guest_name = clean_guest_name(
        " ".join(before_tokens[1:])
    )

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


def looks_like_flight(value: str) -> bool:
    value = clean_text(value).upper().replace(" ", "")
    return re.match(r"^[A-Z0-9]{2,}\d+$", value) is not None


def parse_detail_line(text: str) -> dict[str, Any]:
    text = clean_text(text)
    tokens = text.split()

    if not tokens:
        return {}

    confirmation_no = tokens[0]

    if not re.fullmatch(r"\d{6,}", confirmation_no):
        return {}

    body = tokens[1:]

    prev_stays = ""
    prev_nights = ""

    if (
        len(body) >= 2
        and re.fullmatch(r"-?\d+", body[-2])
        and re.fullmatch(r"-?\d+", body[-1])
    ):
        prev_stays = body[-2]
        prev_nights = body[-1]
        body = body[:-2]

    method_index = next(
        (
            index
            for index, token in enumerate(body)
            if token.upper() in METHOD_OPTIONS
        ),
        None,
    )

    method_of_arrival = (
        body[method_index].upper()
        if method_index is not None
        else ""
    )

    time_index = next(
        (
            index
            for index, token in enumerate(body)
            if TIME_RE.fullmatch(token)
        ),
        None,
    )

    arrival_time = (
        body[time_index]
        if time_index is not None
        else ""
    )

    boundaries = [
        index
        for index in (time_index, method_index)
        if index is not None
    ]
    first_boundary = min(boundaries) if boundaries else len(body)

    prefix = list(body[:first_boundary])
    vip = ""

    if prefix and prefix[0].upper() in KNOWN_VIP_CODES:
        vip = prefix.pop(0).upper()

    last_room = ""
    carrier_code = ""

    if time_index is not None:
        if prefix:
            last_room = " ".join(prefix).strip()

        carrier_start = time_index + 1
        carrier_end = (
            method_index
            if method_index is not None
            and method_index > time_index
            else len(body)
        )

        if carrier_start < carrier_end:
            carrier_code = " ".join(
                body[carrier_start:carrier_end]
            ).strip()

    elif method_index is not None:
        before_method = list(body[:method_index])

        if (
            before_method
            and before_method[0].upper()
            in KNOWN_VIP_CODES
        ):
            if not vip:
                vip = before_method[0].upper()
            before_method = before_method[1:]

        if before_method:
            if len(before_method) == 1:
                token = before_method[0]

                if looks_like_flight(token):
                    carrier_code = token
                else:
                    last_room = token
            else:
                first = before_method[0]

                if looks_like_flight(first):
                    carrier_code = " ".join(
                        before_method
                    ).strip()
                else:
                    last_room = first
                    carrier_code = " ".join(
                        before_method[1:]
                    ).strip()

    else:
        remaining = list(body)

        if (
            remaining
            and remaining[0].upper()
            in KNOWN_VIP_CODES
        ):
            if not vip:
                vip = remaining[0].upper()
            remaining = remaining[1:]

        if remaining:
            last_room = remaining[0]

        if len(remaining) > 1:
            carrier_code = " ".join(
                remaining[1:]
            ).strip()

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


def append_value(
    row: dict[str, Any],
    field: str,
    value: Any,
) -> None:
    value = clean_text(value)

    if not value:
        return

    current = clean_text(row.get(field))

    row[field] = (
        value
        if not current
        else f"{current} | {value}"
    )


def detect_section(text: str) -> tuple[str | None, str]:
    for label, field in SECTION_LABELS.items():
        if text.startswith(label):
            return (
                field,
                clean_text(
                    text.replace(label, "", 1)
                ),
            )

    return None, ""


def find_arrival_group_by_page(
    lines_df: pd.DataFrame,
) -> dict[int, list[tuple[float, str]]]:
    """
    Find Arrival Date group headers and their vertical positions per page.
    """
    groups: dict[int, list[tuple[float, str]]] = {}

    for _, line in lines_df.iterrows():
        text = clean_text(line["text"])

        if not is_arrival_group_header(text):
            continue

        dates = DATE_RE.findall(text)

        if not dates:
            continue

        page_number = int(line["page_number"])
        top = float(line["top"])

        groups.setdefault(
            page_number,
            [],
        ).append(
            (top, dates[-1])
        )

    for page_groups in groups.values():
        page_groups.sort(key=lambda item: item[0])

    return groups


def arrival_group_for_block(
    page_number: int,
    block_top: float,
    groups_by_page: dict[int, list[tuple[float, str]]],
) -> str:
    candidates = groups_by_page.get(
        page_number,
        [],
    )

    selected = ""

    for group_top, group_date in candidates:
        if group_top <= block_top:
            selected = group_date
        else:
            break

    return selected


def normalize_block_lines(
    raw_lines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Keep only the reservation content of a visual block.

    Header/footer leakage after a reservation is cut at the first hard stop.
    """
    cleaned: list[dict[str, Any]] = []
    reservation_started = False

    for line in sorted(
        raw_lines,
        key=lambda item: (
            float(item.get("top") or 0),
            float(item.get("x0") or 0),
        ),
    ):
        text = clean_text(line.get("text"))

        if not text:
            continue

        is_main = (
            ROOM_LINE_RE.match(text)
            and len(DATE_RE.findall(text)) >= 2
        )
        is_detail = DETAIL_LINE_RE.match(text) is not None

        if is_main or is_detail:
            reservation_started = True

        if reservation_started and is_hard_stop(text):
            break

        if not reservation_started:
            if (
                is_hard_stop(text)
                or is_column_header(text)
                or is_arrival_group_header(text)
            ):
                continue

        if is_column_header(text):
            continue

        cleaned.append(
            {
                **line,
                "text": text,
            }
        )

    return cleaned


def parse_sections_and_observations(
    lines: list[dict[str, Any]],
    excluded_indexes: set[int],
) -> dict[str, str]:
    result = {
        "share_with": "",
        "accompanying_names": "",
        "observations": "",
    }

    active_section: str | None = None

    for index, line in enumerate(lines):
        if index in excluded_indexes:
            active_section = None
            continue

        text = clean_text(line["text"])

        if not text:
            continue

        section, inline_value = detect_section(text)

        if section:
            active_section = section

            if inline_value:
                append_value(
                    result,
                    section,
                    inline_value,
                )

            continue

        if (
            is_hard_stop(text)
            or is_column_header(text)
            or is_arrival_group_header(text)
        ):
            active_section = None
            continue

        if active_section:
            append_value(
                result,
                active_section,
                text,
            )
        else:
            # Preserve any unlabelled content in the reservation block.
            append_value(
                result,
                "observations",
                text,
            )

    return result


def parse_visual_block(
    block: pd.Series,
    arrival_group_date: str,
    source_file: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    raw_lines = block.get("lines") or []
    lines = normalize_block_lines(raw_lines)

    debug = {
        "page_number": block.get("page_number"),
        "band_id": block.get("band_id"),
        "shade": block.get("shade"),
        "band_top": block.get("band_top"),
        "band_bottom": block.get("band_bottom"),
        "line_count": len(lines),
        "main_found": False,
        "detail_found": False,
        "parsed": False,
        "reason": "",
        "normalized_text": "\n".join(
            clean_text(line.get("text"))
            for line in lines
        ),
    }

    if not lines:
        debug["reason"] = "empty_block"
        return None, debug

    main_index = next(
        (
            index
            for index, line in enumerate(lines)
            if (
                ROOM_LINE_RE.match(line["text"])
                and len(DATE_RE.findall(line["text"])) >= 2
            )
        ),
        None,
    )

    detail_index = next(
        (
            index
            for index, line in enumerate(lines)
            if DETAIL_LINE_RE.match(line["text"])
        ),
        None,
    )

    debug["main_found"] = main_index is not None
    debug["detail_found"] = detail_index is not None

    if main_index is None:
        debug["reason"] = "main_not_found"
        return None, debug

    if detail_index is None:
        debug["reason"] = "detail_not_found"
        return None, debug

    main = parse_main_line(
        lines[main_index]["text"]
    )
    detail = parse_detail_line(
        lines[detail_index]["text"]
    )

    if not main:
        debug["reason"] = "main_parse_failed"
        return None, debug

    if not detail:
        debug["reason"] = "detail_parse_failed"
        return None, debug

    sections = parse_sections_and_observations(
        lines,
        excluded_indexes={
            main_index,
            detail_index,
        },
    )

    row = {
        **main,
        **detail,
        **sections,
        "arrival_group_date": arrival_group_date,
        "visual_band_id": clean_text(
            block.get("band_id")
        ),
        "visual_shade": clean_text(
            block.get("shade")
        ),
        "visual_page_number": block.get(
            "page_number"
        ),
        "visual_band_top": block.get(
            "band_top"
        ),
        "visual_band_bottom": block.get(
            "band_bottom"
        ),
        "source_report": REPORT_NAME,
        "source_file": source_file,
    }

    debug["parsed"] = True
    debug["reason"] = "success"
    debug["confirmation_no"] = detail.get(
        "confirmation_no"
    )
    debug["guest_name"] = main.get(
        "guest_name"
    )
    debug["room_no"] = main.get(
        "room_no"
    )

    return row, debug


def parse_odata_arr_detail(
    pdf_path: str | Path,
) -> pd.DataFrame:
    pdf_path = Path(pdf_path)
    engine = PdfEngine(pdf_path)

    lines_df = engine.group_lines()
    blocks_df = engine.group_visual_blocks()

    groups_by_page = find_arrival_group_by_page(
        lines_df
    )

    rows: list[dict[str, Any]] = []

    for _, block in blocks_df.sort_values(
        ["page_number", "band_top"],
        kind="stable",
    ).iterrows():
        page_number = int(block["page_number"])
        block_top = float(
            block.get("band_top") or 0
        )

        arrival_group_date = arrival_group_for_block(
            page_number,
            block_top,
            groups_by_page,
        )

        parsed, _ = parse_visual_block(
            block,
            arrival_group_date,
            pdf_path.name,
        )

        if parsed:
            rows.append(parsed)

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    df = df[
        df["confirmation_no"]
        .astype(str)
        .str.match(
            r"^\d{6,}$",
            na=False,
        )
    ]

    df = df.drop_duplicates(
        subset=[
            "confirmation_no",
            "guest_name",
        ],
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
        "observations",
        "visual_band_id",
        "visual_shade",
    ]

    for column in text_columns:
        if column in df.columns:
            df[column] = (
                df[column]
                .fillna("")
                .apply(clean_text)
            )

    for column in [
        "arrival_date",
        "departure_date",
        "arrival_group_date",
    ]:
        if column in df.columns:
            df[column] = df[column].apply(
                to_iso_date
            )

    for column in [
        "room_no",
        "adults",
        "children",
        "rooms",
        "confirmation_no",
        "prev_stays",
        "prev_nights",
        "visual_page_number",
    ]:
        if column in df.columns:
            df[column] = df[column].apply(
                to_int
            )

    final_columns = [
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
        "visual_band_id",
        "visual_shade",
        "visual_page_number",
        "visual_band_top",
        "visual_band_bottom",
        "source_report",
        "source_file",
    ]

    return df[
        [
            column
            for column in final_columns
            if column in df.columns
        ]
    ]


def build_block_debug(
    pdf_path: str | Path,
) -> pd.DataFrame:
    pdf_path = Path(pdf_path)
    engine = PdfEngine(pdf_path)

    lines_df = engine.group_lines()
    blocks_df = engine.group_visual_blocks()

    groups_by_page = find_arrival_group_by_page(
        lines_df
    )

    debug_rows: list[dict[str, Any]] = []

    for _, block in blocks_df.sort_values(
        ["page_number", "band_top"],
        kind="stable",
    ).iterrows():
        page_number = int(block["page_number"])
        block_top = float(
            block.get("band_top") or 0
        )

        arrival_group_date = arrival_group_for_block(
            page_number,
            block_top,
            groups_by_page,
        )

        _, debug = parse_visual_block(
            block,
            arrival_group_date,
            pdf_path.name,
        )

        debug["arrival_group_date"] = (
            arrival_group_date
        )
        debug_rows.append(debug)

    return pd.DataFrame(debug_rows)


def export_debug(
    pdf_path: str | Path,
    output_path: str | Path = (
        "data/debug/ODATA_arr_detail/"
        "odata_arr_detail_v4_debug.xlsx"
    ),
) -> Path:
    pdf_path = Path(pdf_path)
    output_path = Path(output_path)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    engine = PdfEngine(pdf_path)

    words = engine.extract_words()
    lines = engine.group_lines()
    bands = engine.visual_bands()
    blocks = engine.group_visual_blocks()
    block_debug = build_block_debug(pdf_path)
    parsed = parse_odata_arr_detail(pdf_path)

    with pd.ExcelWriter(
        output_path,
        engine="openpyxl",
    ) as writer:
        words.to_excel(
            writer,
            sheet_name="raw_words",
            index=False,
        )

        lines.drop(
            columns=["words"],
            errors="ignore",
        ).to_excel(
            writer,
            sheet_name="lines",
            index=False,
        )

        bands.to_excel(
            writer,
            sheet_name="visual_bands",
            index=False,
        )

        blocks.drop(
            columns=["lines"],
            errors="ignore",
        ).to_excel(
            writer,
            sheet_name="visual_blocks",
            index=False,
        )

        block_debug.to_excel(
            writer,
            sheet_name="block_debug",
            index=False,
        )

        engine.export_line_words(writer)

        parsed.to_excel(
            writer,
            sheet_name="parsed_rows",
            index=False,
        )

    return output_path


if __name__ == "__main__":
    files = list(
        Path("data/incoming").glob(
            "ODATA_arr_detail*.pdf"
        )
    )
    files += list(
        Path("data/incoming").glob(
            "ODATA_arr_detail*.PDF"
        )
    )
    files += list(
        Path("data/incoming").glob(
            "odata_arr_detail*.pdf"
        )
    )
    files += list(
        Path("data/incoming").glob(
            "odata_arr_detail*.PDF"
        )
    )

    if not files:
        raise FileNotFoundError(
            "No encontré ningún "
            "ODATA_arr_detail*.PDF "
            "en data/incoming"
        )

    pdf = files[0]

    print(f"Using: {pdf.name}")

    output = export_debug(pdf)

    print(
        f"Debug exported: "
        f"{output.resolve()}"
    )
