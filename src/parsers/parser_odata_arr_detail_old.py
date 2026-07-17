from __future__ import annotations

from pathlib import Path
from datetime import datetime
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

SECTION_STOP_MARKERS = (
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
    "Arrival Date",
    "Arrival Date Total",
    "Grand Total",
    "Room #",
    "Stays Nts.",
    "Prev. Stays",
    "Prev. Nts.",
    "ETD C/H",
)


def clean_text(value) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    value = str(value).strip()
    value = value.replace("\ufffe", "")

    if value.startswith("*"):
        value = value[1:]

    value = re.sub(r"\s+", " ", value)

    return value.strip()


def clean_guest_name(value: str) -> str:
    value = clean_text(value)

    value = re.split(
        r"\s+[SCTG]-\s*",
        value,
        maxsplit=1,
    )[0]

    return value.strip()


def to_iso_date(value: str) -> str | None:
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


def to_int(value):
    value = clean_text(value)

    if not value:
        return None

    try:
        return int(float(value.replace(",", "")))
    except Exception:
        return None


def is_noise(text: str) -> bool:
    noise = (
        "Filter Arrival",
        "Room Class",
        "Market Code All",
        "From Arrival Time",
        "Room Assignment",
        "Sort Order",
        "Sandy Lane",
        "ODATA_arr_detail",
        "Page ",
        "Name",
        "Company",
        "Room Type",
        "Mkt.",
        "Src.",
        "Res.",
        "Block Code",
        "Arr. Time",
        "Travel Agent",
        "Source",
        "Arr. Date",
        "Conf No.",
        "ETD C/H",
        "Grand Total",
        "Arrival Date Total",
    )

    return any(item in text for item in noise)


def parse_main_line(text: str) -> dict:
    text = clean_text(text)
    dates = DATE_RE.findall(text)

    if len(dates) < 2:
        return {}

    arrival_date = dates[0]
    departure_date = dates[1]

    before_arrival = text.split(
        arrival_date,
        1,
    )[0].strip()

    after_departure = text.split(
        departure_date,
        1,
    )[1].strip()

    before_tokens = before_arrival.split()

    room_no = (
        before_tokens[0]
        if before_tokens
        else ""
    )

    name_company = " ".join(
        before_tokens[1:]
    ).strip()

    guest_name = clean_guest_name(
        name_company
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


def parse_detail_line(text: str) -> dict:
    """
    Interpreta la línea de detalle usando patrones y no posiciones fijas.

    Casos soportados:
        2079408 PRE 101 12:11 BA255 VAN 4 40
        596796710 NEW LT- OWN 0 0
        597895914 NEW 3 12:48 PJ - YV2692 VAN 0 0
        597895914 NEW 12:48 PJ - YV2692 VAN 0 0
    """
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

    # Método de llegada.
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

    # Hora de llegada.
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

    # VIP: buscarlo al comienzo del bloque, antes de hora/método.
    vip = ""
    first_boundary_candidates = [
        index
        for index in (time_index, method_index)
        if index is not None
    ]
    first_boundary = (
        min(first_boundary_candidates)
        if first_boundary_candidates
        else len(body)
    )

    prefix = list(body[:first_boundary])

    if prefix:
        first_token = clean_text(prefix[0]).upper()

        if first_token in KNOWN_VIP_CODES:
            vip = first_token
            prefix = prefix[1:]

    last_room = ""
    carrier_code = ""

    if time_index is not None:
        # Antes de la hora solo deben quedar VIP y/o Last Room.
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
        # Sin hora: antes del método puede venir Last Room y/o carrier.
        before_method = list(body[:method_index])

        if before_method:
            first_token = clean_text(before_method[0]).upper()

            if first_token in KNOWN_VIP_CODES:
                if not vip:
                    vip = first_token
                before_method = before_method[1:]

        if before_method:
            def looks_like_flight(value: str) -> bool:
                value = clean_text(value).upper()
                value = value.replace(" ", "")
                return re.match(r"^[A-Z0-9]{2,}\d+$", value) is not None

            if len(before_method) == 1:
                token = before_method[0]

                if looks_like_flight(token):
                    carrier_code = token
                    last_room = ""
                else:
                    last_room = token

            else:
                first = before_method[0]

                if looks_like_flight(first):
                    carrier_code = " ".join(before_method).strip()
                    last_room = ""
                else:
                    last_room = first
                    carrier_code = " ".join(
                        before_method[1:]
                    ).strip()

    else:
        # Caso excepcional sin hora ni método.
        remaining = list(body)

        if remaining:
            first_token = clean_text(remaining[0]).upper()

            if first_token in KNOWN_VIP_CODES:
                if not vip:
                    vip = first_token
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


def append_multiline_value(
    row: dict,
    field: str,
    value: str,
) -> None:
    value = clean_text(value)

    if not value:
        return

    current = clean_text(row.get(field))

    row[field] = (
        value
        if not current
        else clean_text(f"{current} | {value}")
    )



def is_section_stop(text: str) -> bool:
    text = clean_text(text)

    if not text:
        return True

    if any(marker in text for marker in SECTION_STOP_MARKERS):
        return True

    if ROOM_LINE_RE.match(text) and DATE_RE.search(text):
        return True

    if DETAIL_LINE_RE.match(text):
        return True

    return False


def looks_like_section_value(text: str) -> bool:
    text = clean_text(text)

    if not text:
        return False

    if is_section_stop(text):
        return False

    if is_noise(text):
        return False

    return True


def parse_odata_arr_detail(
    pdf_path: str | Path,
) -> pd.DataFrame:
    pdf_path = Path(pdf_path)
    engine = PdfEngine(pdf_path)

    lines_df = engine.group_lines()

    rows: list[dict] = []
    pending_main: dict | None = None
    current_row: dict | None = None

    current_arrival_group = ""
    section_mode: str | None = None

    for _, row in lines_df.iterrows():
        text = clean_text(row["text"])

        if not text:
            continue

        if text.startswith("Arrival Date"):
            dates = DATE_RE.findall(text)

            if dates:
                current_arrival_group = dates[-1]

            section_mode = None
            continue

        if text.startswith("Share with:"):
            section_mode = "share_with"

            inline_value = clean_text(
                text.replace(
                    "Share with:",
                    "",
                    1,
                )
            )

            if current_row and inline_value:
                append_multiline_value(
                    current_row,
                    "share_with",
                    inline_value,
                )

            continue

        if text.startswith("Accompanying Names:"):
            section_mode = "accompanying_names"

            inline_value = clean_text(
                text.replace(
                    "Accompanying Names:",
                    "",
                    1,
                )
            )

            if current_row and inline_value:
                append_multiline_value(
                    current_row,
                    "accompanying_names",
                    inline_value,
                )

            continue

        if (
            ROOM_LINE_RE.match(text)
            and DATE_RE.search(text)
        ):
            parsed_main = parse_main_line(text)

            if parsed_main:
                pending_main = parsed_main
                pending_main["arrival_group_date"] = (
                    current_arrival_group
                )

            section_mode = None
            continue

        if (
            pending_main
            and DETAIL_LINE_RE.match(text)
        ):
            detail = parse_detail_line(text)

            if detail:
                current_row = {
                    **pending_main,
                    **detail,
                    "share_with": "",
                    "accompanying_names": "",
                    "source_report": REPORT_NAME,
                    "source_file": pdf_path.name,
                }

                rows.append(current_row)

            pending_main = None
            section_mode = None
            continue

        if is_section_stop(text):
            section_mode = None

            if is_noise(text):
                continue

        if is_noise(text):
            section_mode = None
            continue

        if (
            current_row
            and section_mode
            and looks_like_section_value(text)
        ):
            append_multiline_value(
                current_row,
                section_mode,
                text,
            )
            continue

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
    ]

    for col in text_columns:
        if col in df.columns:
            df[col] = (
                df[col]
                .fillna("")
                .apply(clean_text)
            )

    date_columns = [
        "arrival_date",
        "departure_date",
        "arrival_group_date",
    ]

    for col in date_columns:
        if col in df.columns:
            df[col] = df[col].apply(
                to_iso_date
            )

    int_columns = [
        "room_no",
        "adults",
        "children",
        "rooms",
        "confirmation_no",
        "prev_stays",
        "prev_nights",
    ]

    for col in int_columns:
        if col in df.columns:
            df[col] = df[col].apply(
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
        "source_report",
        "source_file",
    ]

    return df[
        [
            col
            for col in final_columns
            if col in df.columns
        ]
    ]


def export_debug(
    pdf_path: str | Path,
    output_path: str | Path = (
        "data/debug/ODATA_arr_detail/"
        "odata_arr_detail_debug.xlsx"
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
    parsed = parse_odata_arr_detail(
        pdf_path
    )

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

    out = export_debug(pdf)

    print(
        f"Debug exported: "
        f"{out.resolve()}"
    )