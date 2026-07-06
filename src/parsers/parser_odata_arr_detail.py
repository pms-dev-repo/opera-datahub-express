from __future__ import annotations

from pathlib import Path
from datetime import datetime
import re
import pandas as pd

from .pdf_engine import PdfEngine


REPORT_NAME = "ODATA_arr_detail"
TARGET_TABLE = "odata_arr_detail"

DATE_RE = re.compile(r"\d{2}-\d{2}-\d{2}")
ROOM_LINE_RE = re.compile(r"^\d{2,5}\s+")
DETAIL_LINE_RE = re.compile(r"^\d{6,}\s+")


def to_iso_date(value: str) -> str | None:
    if value is None or str(value).strip() == "":
        return None

    try:
        return datetime.strptime(str(value).strip(), "%d-%m-%y").date().isoformat()
    except Exception:
        return None


def to_int(value):
    if value is None or str(value).strip() == "":
        return None

    try:
        return int(float(str(value).strip()))
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

    return any(n in text for n in noise)


def parse_main_line(text: str) -> dict:
    dates = DATE_RE.findall(text)

    if len(dates) < 2:
        return {}

    arrival_date = dates[0]
    departure_date = dates[1]

    before_arrival = text.split(arrival_date)[0].strip()
    after_departure = text.split(departure_date, 1)[1].strip()

    before_tokens = before_arrival.split()
    room_no = before_tokens[0] if before_tokens else ""

    name_company = " ".join(before_tokens[1:]).strip()

    company_markers = [" S- ", " T- "]
    guest_name = name_company

    for marker in company_markers:
        if marker in f" {name_company} ":
            parts = f" {name_company} ".split(marker, 1)
            guest_name = parts[0].strip()
            break

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
        "reservation_status": tail[6] if len(tail) > 6 else "",
    }


def parse_detail_line(text: str) -> dict:
    tokens = text.split()

    confirmation_no = tokens[0] if len(tokens) > 0 else ""
    vip = tokens[1] if len(tokens) > 1 else ""
    last_room = tokens[2] if len(tokens) > 2 else ""

    prev_stays = tokens[-2] if len(tokens) >= 2 else ""
    prev_nights = tokens[-1] if len(tokens) >= 1 else ""

    middle = tokens[3:-2] if len(tokens) > 5 else []

    method_options = {"VAN", "MER", "OWN", "EXE/LUG", "SCON"}

    carrier_code = ""
    method_of_arrival = ""

    for i, token in enumerate(middle):
        if token in method_options:
            carrier_code = " ".join(middle[:i]).strip()
            method_of_arrival = token
            break

    if not method_of_arrival:
        carrier_code = " ".join(middle).strip()

    return {
        "confirmation_no": confirmation_no,
        "vip": vip,
        "last_room": last_room,
        "carrier_code": carrier_code,
        "method_of_arrival": method_of_arrival,
        "prev_stays": prev_stays,
        "prev_nights": prev_nights,
    }


def parse_odata_arr_detail(pdf_path: str | Path) -> pd.DataFrame:
    pdf_path = Path(pdf_path)
    engine = PdfEngine(pdf_path)

    lines_df = engine.group_lines()

    rows = []
    pending = None
    current_arrival_group = ""

    for _, row in lines_df.iterrows():
        text = str(row["text"]).strip()

        if not text or is_noise(text):
            continue

        if text.startswith("Arrival Date"):
            dates = DATE_RE.findall(text)
            if dates:
                current_arrival_group = dates[-1]
            continue

        if text.startswith("Share with:"):
            if rows:
                rows[-1]["share_with"] = text.replace("Share with:", "").strip()
            continue

        if text.startswith("Accompanying Names:"):
            if rows:
                rows[-1]["accompanying_names"] = text.replace("Accompanying Names:", "").strip()
            continue

        if ROOM_LINE_RE.match(text) and DATE_RE.search(text):
            pending = parse_main_line(text)
            pending["arrival_group_date"] = current_arrival_group
            continue

        if pending and DETAIL_LINE_RE.match(text):
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

    df = df[df["confirmation_no"].astype(str).str.match(r"^\d{6,}$", na=False)]
    df = df.drop_duplicates(subset=["confirmation_no", "guest_name"], keep="first")

    for col in ["arrival_date", "departure_date", "arrival_group_date"]:
        if col in df.columns:
            df[col] = df[col].apply(to_iso_date)

    int_cols = [
        "room_no",
        "adults",
        "children",
        "rooms",
        "confirmation_no",
        "prev_stays",
        "prev_nights",
    ]

    for col in int_cols:
        if col in df.columns:
            df[col] = df[col].apply(to_int)

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
        "reservation_status",
        "arrival_group_date",
        "confirmation_no",
        "vip",
        "last_room",
        "carrier_code",
        "method_of_arrival",
        "prev_stays",
        "prev_nights",
        "share_with",
        "accompanying_names",
        "source_report",
        "source_file",
    ]

    df = df[[c for c in final_columns if c in df.columns]]

    return df


def export_debug(
    pdf_path: str | Path,
    output_path: str | Path = "data/debug/ODATA_arr_detail/odata_arr_detail_debug.xlsx",
) -> Path:
    pdf_path = Path(pdf_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    engine = PdfEngine(pdf_path)

    words = engine.extract_words()
    lines = engine.group_lines()
    parsed = parse_odata_arr_detail(pdf_path)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        words.to_excel(writer, sheet_name="raw_words", index=False)
        lines.drop(columns=["words"], errors="ignore").to_excel(writer, sheet_name="lines", index=False)
        engine.export_line_words(writer)
        parsed.to_excel(writer, sheet_name="parsed_rows", index=False)

    return output_path


if __name__ == "__main__":
    pdf = Path("data/incoming/ODATA_arr_detail.PDF")

    if not pdf.exists():
        raise FileNotFoundError(f"No encontré el PDF aquí: {pdf.resolve()}")

    out = export_debug(pdf)
    print(f"Debug exported: {out.resolve()}")