from __future__ import annotations

from pathlib import Path
from datetime import date
import re
import pandas as pd

from .pdf_engine import PdfEngine


REPORT_NAME = "ODATA_Departures_All"
TARGET_TABLE = "odata_departures_all"

DATE_RE = re.compile(r"\d{2}-\d{2}-\d{2}")


COLUMNS = {
    "room_no": (0, 35),
    "guest_name": (35, 122),
    "company": (122, 282),
    "vip": (282, 309),
    "arrival_date": (309, 348),
    "departure_date": (348, 391),
    "adults": (391, 411),
    "children": (411, 430),
    "rooms": (430, 458),
    "nights": (458, 475),
    "room_type": (475, 505),
    "rate_code": (538, 575),
    "reservation_status": (575, 640),
    "payment_method": (640, 690),
}


def clean_text(value) -> str:
    value = str(value or "").strip()

    if value.startswith("*"):
        value = value[1:]

    value = re.sub(r"\s+", " ", value)
    return value.strip()


def clean_guest_name(value: str) -> str:
    value = clean_text(value)

    value = re.split(r"\s+[CTG]-", value)[0]
    value = re.sub(r"\bMaste r\b", "Master", value)
    value = re.sub(r"\bMr \.", "Mr.", value)
    value = re.sub(r"\bMrs \.", "Mrs.", value)

    return value.strip()


def to_iso_date(value: str) -> str | None:
    value = clean_text(value)

    if not value:
        return None

    try:
        day, month, year = value.split("-")
        yy = int(year)
        current_yy = date.today().year % 100
        yyyy = 2000 + yy if yy <= current_yy else 1900 + yy
        return date(yyyy, int(month), int(day)).isoformat()
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


def text_in_range(words: list, x_min: float, x_max: float) -> str:
    return " ".join(
        clean_text(w["text"])
        for w in words
        if x_min <= float(w["x0"]) < x_max
    ).strip()


def extract_columns(words: list) -> dict:
    return {
        col: text_in_range(words, x_min, x_max)
        for col, (x_min, x_max) in COLUMNS.items()
    }


def is_noise(text: str) -> bool:
    noise = (
        "Sandy Lane",
        "ODATA_Departures_All",
        "Filter ",
        "Reservation Status",
        "Sort Order",
        "Page ",
        "Room Name",
        "No. Travel",
        "Source",
        "Group",
        "Total ",
    )

    return any(n == text or text.startswith(n) for n in noise)


def get_departure_group_date(text: str) -> str | None:
    text = clean_text(text)

    if text.startswith("Departure "):
        value = text.replace("Departure ", "").strip()

        if DATE_RE.fullmatch(value):
            return value

    return None


def looks_like_departure_row(row: dict) -> bool:
    return (
        clean_text(row.get("room_no")).isdigit()
        and clean_text(row.get("guest_name"))
        and DATE_RE.fullmatch(clean_text(row.get("arrival_date") or "")) is not None
        and DATE_RE.fullmatch(clean_text(row.get("departure_date") or "")) is not None
    )


def append_continuation(rows: list[dict], words: list, text: str) -> None:
    if not rows or not words:
        return

    text = clean_text(text)

    if text.startswith("Share with:"):
        rows[-1]["share_with"] = clean_text(
            str(rows[-1].get("share_with") or "") + " " + text.replace("Share with:", "")
        )
        return

    guest_part = text_in_range(words, 35, 122)
    company_part = text_in_range(words, 122, 282)

    if guest_part:
        current = clean_text(rows[-1].get("guest_name"))
        rows[-1]["guest_name"] = clean_text((current + " " + guest_part).strip())

    if company_part:
        current = clean_text(rows[-1].get("company"))
        rows[-1]["company"] = clean_text((current + " " + company_part).strip())


def parse_odata_departures_all(pdf_path: str | Path) -> pd.DataFrame:
    pdf_path = Path(pdf_path)
    engine = PdfEngine(pdf_path)

    lines_df = engine.group_lines()
    rows = []

    current_departure_group_date = None

    for _, line in lines_df.iterrows():
        text = clean_text(line["text"])
        words = line["words"]

        if not text:
            continue

        group_date = get_departure_group_date(text)
        if group_date:
            current_departure_group_date = group_date
            continue

        if is_noise(text):
            continue

        parsed = extract_columns(words)

        if looks_like_departure_row(parsed):
            parsed["departure_group_date"] = current_departure_group_date
            parsed["departure_time"] = None
            parsed["share_with"] = None
            parsed["source_report"] = REPORT_NAME
            parsed["source_file"] = pdf_path.name
            rows.append(parsed)
            continue

        append_continuation(rows, words, text)

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    if "guest_name" in df.columns:
        df["guest_name"] = df["guest_name"].apply(clean_guest_name)

    for col in [
        "company",
        "room_type",
        "reservation_status",
        "departure_time",
        "payment_method",
        "rate_code",
        "vip",
        "share_with",
    ]:
        if col in df.columns:
            df[col] = df[col].apply(clean_text)

    for col in [
        "arrival_date",
        "departure_date",
        "departure_group_date",
    ]:
        if col in df.columns:
            df[col] = df[col].apply(to_iso_date)

    for col in [
        "room_no",
        "nights",
        "adults",
        "children",
        "rooms",
    ]:
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
        lines.drop(columns=["words"], errors="ignore").to_excel(
            writer,
            sheet_name="lines",
            index=False,
        )
        engine.export_line_words(writer)
        parsed.to_excel(writer, sheet_name="parsed_rows", index=False)

    return output_path


if __name__ == "__main__":
    files = list(Path("data/incoming").glob("ODATA_Departures_All*.pdf"))
    files += list(Path("data/incoming").glob("ODATA_Departures_All*.PDF"))
    files += list(Path("data/incoming").glob("odata_departures_all*.pdf"))
    files += list(Path("data/incoming").glob("odata_departures_all*.PDF"))

    if not files:
        raise FileNotFoundError(
            "No encontré ningún ODATA_Departures_All*.PDF en data/incoming"
        )

    pdf = files[0]

    print(f"Using: {pdf.name}")

    out = export_debug(pdf)
    print(f"Debug exported: {out.resolve()}")