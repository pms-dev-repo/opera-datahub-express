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


def clean_text(value) -> str:
    """
    Normaliza valores de texto.

    Convierte None y NaN en cadena vacía, elimina el asterisco
    inicial de OPERA y normaliza espacios.
    """
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    value = str(value).strip()

    if value.startswith("*"):
        value = value[1:]

    value = value.replace("\ufffe", "")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def clean_guest_name(value: str) -> str:
    value = clean_text(value)

    # Elimina Company, Source, Travel Agent o Group cuando
    # quedan concatenados al nombre.
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
        "room_type": (
            tail[0]
            if len(tail) > 0
            else ""
        ),
        "adults": (
            tail[1]
            if len(tail) > 1
            else ""
        ),
        "children": (
            tail[2]
            if len(tail) > 2
            else ""
        ),
        "rooms": (
            tail[3]
            if len(tail) > 3
            else ""
        ),
        "market_code": (
            tail[4]
            if len(tail) > 4
            else ""
        ),
        "source_code": (
            tail[5]
            if len(tail) > 5
            else ""
        ),
        "reservation_status": (
            tail[6]
            if len(tail) > 6
            else ""
        ),
    }


def parse_detail_line(text: str) -> dict:
    """
    Ejemplo:

        2079408 PRE 101 12:11 BA255 VAN 4 40

    Resultado:

        confirmation_no = 2079408
        vip = PRE
        last_room = 101
        arrival_time = 12:11
        carrier_code = BA255
        method_of_arrival = VAN
        prev_stays = 4
        prev_nights = 40
    """

    text = clean_text(text)
    tokens = text.split()

    confirmation_no = (
        tokens[0]
        if len(tokens) > 0
        else ""
    )

    vip = (
        tokens[1]
        if len(tokens) > 1
        else ""
    )

    last_room = (
        tokens[2]
        if len(tokens) > 2
        else ""
    )

    prev_stays = (
        tokens[-2]
        if len(tokens) >= 2
        else ""
    )

    prev_nights = (
        tokens[-1]
        if len(tokens) >= 1
        else ""
    )

    middle = (
        tokens[3:-2]
        if len(tokens) > 5
        else []
    )

    arrival_time = ""
    carrier_code = ""
    method_of_arrival = ""

    time_index = None

    for index, token in enumerate(middle):
        if TIME_RE.fullmatch(token):
            arrival_time = token
            time_index = index
            break

    method_index = None

    for index, token in enumerate(middle):
        if token.upper() in METHOD_OPTIONS:
            method_of_arrival = token.upper()
            method_index = index
            break

    carrier_start = (
        time_index + 1
        if time_index is not None
        else 0
    )

    carrier_end = (
        method_index
        if method_index is not None
        else len(middle)
    )

    if carrier_start < carrier_end:
        carrier_code = " ".join(
            middle[carrier_start:carrier_end]
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


def parse_odata_arr_detail(
    pdf_path: str | Path,
) -> pd.DataFrame:
    pdf_path = Path(pdf_path)
    engine = PdfEngine(pdf_path)

    lines_df = engine.group_lines()

    rows: list[dict] = []
    pending: dict | None = None
    current_arrival_group = ""

    for _, row in lines_df.iterrows():
        text = clean_text(row["text"])

        if not text or is_noise(text):
            continue

        if text.startswith("Arrival Date"):
            dates = DATE_RE.findall(text)

            if dates:
                current_arrival_group = dates[-1]

            continue

        if text.startswith("Share with:"):
            if rows:
                rows[-1]["share_with"] = clean_text(
                    text.replace(
                        "Share with:",
                        "",
                        1,
                    )
                )

            continue

        if text.startswith("Accompanying Names:"):
            if rows:
                rows[-1]["accompanying_names"] = clean_text(
                    text.replace(
                        "Accompanying Names:",
                        "",
                        1,
                    )
                )

            continue

        if (
            ROOM_LINE_RE.match(text)
            and DATE_RE.search(text)
        ):
            parsed_main = parse_main_line(text)

            if parsed_main:
                pending = parsed_main
                pending["arrival_group_date"] = (
                    current_arrival_group
                )
            else:
                pending = None

            continue

        if (
            pending
            and DETAIL_LINE_RE.match(text)
        ):
            detail = parse_detail_line(text)

            final_row = {
                **pending,
                **detail,
                "share_with": "",
                "accompanying_names": "",
                "source_report": REPORT_NAME,
                "source_file": pdf_path.name,
            }

            rows.append(final_row)
            pending = None

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