from __future__ import annotations

from pathlib import Path
from datetime import date
import re
import pandas as pd

from .pdf_engine import PdfEngine


REPORT_NAME = "ODATA_GIH_Birthday"
TARGET_TABLE = "odata_gih_birthday"

DATE_RE = re.compile(r"\d{2}-\d{2}-\d{2}")

BIRTHDAY_LINE_RE = re.compile(
    r"^(?P<guest_name>.+?)\s+"
    r"(?P<birth_date>\d{2}-\d{2}-\d{2})\s+"
    r"(?P<age>\d+)\s+"
    r"(?P<vip>[A-Z]+)\s+"
    r"(?P<number_of_stays>\d+)"
    r"(?:\s+(?P<last_stay>\d{2}-\d{2}-\d{2}))?$"
)


def clean_text(value) -> str:
    value = str(value or "").strip()
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def to_iso_date(value: str) -> str | None:
    value = clean_text(value)

    if not value:
        return None

    try:
        day, month, year = value.split("-")

        yy = int(year)
        current_yy = date.today().year % 100

        if yy <= current_yy:
            yyyy = 2000 + yy
        else:
            yyyy = 1900 + yy

        return date(
            yyyy,
            int(month),
            int(day),
        ).isoformat()

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
        "Sandy Lane",
        "ODATA_GIH_Birthday",
        "Filter ",
        "From Stay Date",
        "Reservation Status",
        "Sort Order",
        "Page ",
        "pr_birthday",
        "Room",
        "Name Company Arr.Date Dep.Date Nts. Resv. Status",
        "Birth Date",
        "Age",
        "Vip",
        "No. of",
        "Stays",
        "Last Stay",
        "Source",
        "Travel Agent",
        "Rate Code",
    )

    return any(n in text for n in noise)


def parse_line(text: str) -> dict | None:
    text = clean_text(text)

    match = BIRTHDAY_LINE_RE.match(text)

    if not match:
        return None

    data = match.groupdict()

    return {
        "room_no": None,
        "guest_name": clean_text(data.get("guest_name")),
        "company": None,
        "arrival_date": None,
        "departure_date": None,
        "number_of_nights": None,
        "reservation_status": None,
        "birth_date": data.get("birth_date"),
        "age": data.get("age"),
        "vip": data.get("vip"),
        "number_of_stays": data.get("number_of_stays"),
        "last_stay": data.get("last_stay"),
        "source": None,
        "travel_agent": None,
        "rate_code": None,
    }


def parse_odata_gih_birthday(pdf_path: str | Path) -> pd.DataFrame:
    pdf_path = Path(pdf_path)
    engine = PdfEngine(pdf_path)

    lines_df = engine.group_lines()

    rows = []

    for _, line in lines_df.iterrows():
        text = clean_text(line["text"])

        if not text:
            continue

        if is_noise(text):
            continue

        parsed = parse_line(text)

        if parsed:
            parsed["source_report"] = REPORT_NAME
            parsed["source_file"] = pdf_path.name
            rows.append(parsed)

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    for col in [
        "guest_name",
        "company",
        "reservation_status",
        "vip",
        "source",
        "travel_agent",
        "rate_code",
    ]:
        if col in df.columns:
            df[col] = df[col].apply(clean_text)

    for col in ["arrival_date", "departure_date", "birth_date", "last_stay"]:
        if col in df.columns:
            df[col] = df[col].apply(to_iso_date)

    for col in ["room_no", "number_of_nights", "age", "number_of_stays"]:
        if col in df.columns:
            df[col] = df[col].apply(to_int)

    final_columns = [
        "room_no",
        "guest_name",
        "company",
        "arrival_date",
        "departure_date",
        "number_of_nights",
        "reservation_status",
        "birth_date",
        "age",
        "vip",
        "number_of_stays",
        "last_stay",
        "source",
        "travel_agent",
        "rate_code",
        "source_report",
        "source_file",
    ]

    return df[[c for c in final_columns if c in df.columns]]


def export_debug(
    pdf_path: str | Path,
    output_path: str | Path = "data/debug/ODATA_GIH_Birthday/odata_gih_birthday_debug.xlsx",
) -> Path:
    pdf_path = Path(pdf_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    engine = PdfEngine(pdf_path)

    words = engine.extract_words()
    lines = engine.group_lines()
    parsed = parse_odata_gih_birthday(pdf_path)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        words.to_excel(writer, sheet_name="raw_words", index=False)
        lines.drop(columns=["words"], errors="ignore").to_excel(writer, sheet_name="lines", index=False)
        engine.export_line_words(writer)
        parsed.to_excel(writer, sheet_name="parsed_rows", index=False)

    return output_path


if __name__ == "__main__":
    pdf = Path("data/incoming/ODATA_GIH_Birthday.PDF")

    if not pdf.exists():
        raise FileNotFoundError(f"No encontré el PDF aquí: {pdf.resolve()}")

    out = export_debug(pdf)
    print(f"Debug exported: {out.resolve()}")