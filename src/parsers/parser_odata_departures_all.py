from __future__ import annotations

from pathlib import Path
from datetime import datetime
import re
import pandas as pd

from .pdf_engine import PdfEngine


REPORT_NAME = "ODATA_Departures_All"
TARGET_TABLE = "odata_departures_all"

DATE_RE = re.compile(r"\d{2}-\d{2}-\d{2}")


COLUMNS = {
    "room_no": (0, 30),
    "guest_name": (30, 120),
    "vip": (275, 305),
    "arrival_date": (300, 345),
    "departure_date": (345, 390),
    "adults": (390, 410),
    "children": (410, 430),
    "rooms": (430, 455),
    "nights": (455, 475),
    "room_type": (475, 500),
    "rate_code": (535, 575),
    "reservation_status": (575, 610),
    "departure_time": (610, 640),
    "payment_method": (640, 675),
}


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
        return int(float(str(value).replace(",", "").strip()))
    except Exception:
        return None


def is_noise(text: str) -> bool:
    noise = (
        "Filter ",
        "Room Class",
        "Sort Order",
        "Profile Type",
        "Sandy Lane",
        "ODATA_Departures_All",
        "departure_all",
        "Page ",
        "Name",
        "Company",
        "Travel Agent",
        "Source",
        "Group",
        "Room Room",
        "No.",
        "Rate",
        "Code",
        "VIP",
        "Total ",
        "Departure",
        "Date Date",
    )
    return any(n in text for n in noise)


def text_in_range(words: list, x_min: float, x_max: float) -> str:
    return " ".join(
        str(w["text"])
        for w in words
        if x_min <= float(w["x0"]) < x_max
    ).strip()


def extract_columns(words: list) -> dict:
    return {
        col: text_in_range(words, x_min, x_max)
        for col, (x_min, x_max) in COLUMNS.items()
    }


def clean_guest_name(value: str) -> str:
    value = str(value or "").strip()
    value = value.replace(" ,", ",")
    value = value.replace(" .", ".")
    value = value.replace("Ms .", "Ms.")
    value = value.replace("Mr .", "Mr.")
    value = value.replace("Mrs .", "Mrs.")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def split_rate_status(row: dict) -> dict:
    rate = str(row.get("rate_code") or "").strip()
    status = str(row.get("reservation_status") or "").strip()

    if rate.endswith("CKIN") and not status:
        row["rate_code"] = rate.replace("CKIN", "")
        row["reservation_status"] = "CKIN"

    return row


def parse_odata_departures_all(pdf_path: str | Path) -> pd.DataFrame:
    pdf_path = Path(pdf_path)
    engine = PdfEngine(pdf_path)

    lines_df = engine.group_lines()

    rows = []
    current_departure_group = None
    last_row_index = None

    for _, line in lines_df.iterrows():
        text = str(line["text"]).strip()
        words = line["words"]

        if not text:
            continue

        if text.startswith("Share with:"):
            if last_row_index is not None:
                rows[last_row_index]["share_with"] = text.replace("Share with:", "").strip()
            continue

        if is_noise(text):
            continue

        if text.startswith("Departure"):
            dates = DATE_RE.findall(text)
            if dates:
                current_departure_group = dates[-1]
            continue

        if DATE_RE.fullmatch(text):
            current_departure_group = text
            continue

        parsed = extract_columns(words)

        room_no = str(parsed.get("room_no") or "").strip()
        arrival_date = str(parsed.get("arrival_date") or "").strip()

        is_main_row = (
            room_no.isdigit()
            and DATE_RE.fullmatch(arrival_date) is not None
        )

        if is_main_row:
            parsed = split_rate_status(parsed)

            parsed["guest_name"] = clean_guest_name(parsed.get("guest_name"))
            parsed["departure_group_date"] = current_departure_group
            parsed["share_with"] = ""
            parsed["source_report"] = REPORT_NAME
            parsed["source_file"] = pdf_path.name

            rows.append(parsed)
            last_row_index = len(rows) - 1
            continue

        # Continuación de nombre, ejemplo: "& Mrs." o "."
        if last_row_index is not None:
            continuation = text.strip()
            min_x = min(float(w["x0"]) for w in words)

            if min_x < 80 and continuation not in ("",):
                rows[last_row_index]["guest_name"] = clean_guest_name(
                    rows[last_row_index]["guest_name"] + " " + continuation
                )

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    for col in ["arrival_date", "departure_date", "departure_group_date"]:
        if col in df.columns:
            df[col] = df[col].apply(to_iso_date)

    for col in ["room_no", "nights", "adults", "children", "rooms"]:
        if col in df.columns:
            df[col] = df[col].apply(to_int)

    final_columns = [
        "room_no",
        "guest_name",
        "nights",
        "arrival_date",
        "departure_date",
        "departure_group_date",
        "adults",
        "children",
        "rooms",
        "room_type",
        "reservation_status",
        "departure_time",
        "payment_method",
        "rate_code",
        "vip",
        "share_with",
        "source_report",
        "source_file",
    ]

    return df[[c for c in final_columns if c in df.columns]]


def export_debug(
    pdf_path: str | Path,
    output_path: str | Path = "data/debug/ODATA_Departures_All/odata_departures_all_debug.xlsx",
) -> Path:
    pdf_path = Path(pdf_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    engine = PdfEngine(pdf_path)

    words = engine.extract_words()
    lines = engine.group_lines()
    parsed = parse_odata_departures_all(pdf_path)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        words.to_excel(writer, sheet_name="raw_words", index=False)
        lines.drop(columns=["words"], errors="ignore").to_excel(writer, sheet_name="lines", index=False)
        engine.export_line_words(writer)
        parsed.to_excel(writer, sheet_name="parsed_rows", index=False)

    return output_path


if __name__ == "__main__":
    pdf = Path("data/incoming/ODATA_Departures_All.PDF")

    if not pdf.exists():
        raise FileNotFoundError(f"No encontré el PDF aquí: {pdf.resolve()}")

    out = export_debug(pdf)
    print(f"Debug exported: {out.resolve()}")