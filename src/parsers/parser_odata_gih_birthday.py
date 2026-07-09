from __future__ import annotations

from pathlib import Path
from datetime import date
import re
import pandas as pd

from .pdf_engine import PdfEngine


REPORT_NAME = "ODATA_GIH_Birthday"
TARGET_TABLE = "odata_gih_birthday"

DATE_RE = re.compile(r"\d{2}-\d{2}-\d{2}")
STATUS_VALUES = {"CKIN", "CHECKED IN"}


COLUMNS = {
    "room_no": (0, 40),
    "guest_name": (40, 230),
    "company": (230, 360),
    "arrival_date": (360, 405),
    "departure_date": (405, 465),
    "number_of_nights": (465, 475),
    "rate_code": (475, 535),
    "reservation_status": (535, 590),
    "birth_date": (590, 640),
    "age": (640, 660),
    "vip": (660, 700),
    "number_of_stays": (700, 760),
    "last_stay": (760, 850),
}


def clean_text(value) -> str:
    value = str(value or "").strip()

    if value.startswith("*"):
        value = value[1:]

    value = re.sub(r"\s+", " ", value)
    return value.strip()


def to_iso_date(value: str) -> str | None:
    value = clean_text(value)

    if not value or value.upper() in {"XX/XX/XX", "XX-XX-XX"}:
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
        "ODATA_GIH_Birthday",
        "Filter ",
        "From Stay Date",
        "Reservation Status",
        "Sort Order",
        "Page ",
        "pr_birthday",
        "Room",
        "Name",
        "Company",
        "Arr.Date",
        "Dep.Date",
        "Nts.",
        "Resv. Status",
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

    return any(n == text or text.startswith(n) for n in noise)


def looks_like_birthday_row(row: dict) -> bool:
    return (
        clean_text(row.get("room_no")).isdigit()
        and DATE_RE.fullmatch(clean_text(row.get("arrival_date") or "")) is not None
        and DATE_RE.fullmatch(clean_text(row.get("departure_date") or "")) is not None
        and clean_text(row.get("reservation_status")) == "CKIN"
    )


def append_continuation(rows: list[dict], words: list, text: str) -> None:
    if not rows or not words:
        return

    min_x = min(float(w["x0"]) for w in words)

    if text.startswith("T- "):
        rows[-1]["travel_agent"] = clean_text(text)
        return

    if 210 <= min_x < 360:
        current = clean_text(rows[-1].get("company"))
        rows[-1]["company"] = clean_text((current + " " + text).strip())


def parse_odata_gih_birthday(pdf_path: str | Path) -> pd.DataFrame:
    pdf_path = Path(pdf_path)
    engine = PdfEngine(pdf_path)

    lines_df = engine.group_lines()

    rows = []

    for _, line in lines_df.iterrows():
        text = clean_text(line["text"])
        words = line["words"]

        if not text:
            continue

        if is_noise(text):
            continue

        parsed = extract_columns(words)

        if looks_like_birthday_row(parsed):
            parsed["source_report"] = REPORT_NAME
            parsed["source_file"] = pdf_path.name
            rows.append(parsed)
            continue

        append_continuation(rows, words, text)

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    for col in [
        "guest_name",
        "company",
        "reservation_status",
        "vip",
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

    df["source"] = None

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
        lines.drop(columns=["words"], errors="ignore").to_excel(
            writer,
            sheet_name="lines",
            index=False,
        )
        engine.export_line_words(writer)
        parsed.to_excel(writer, sheet_name="parsed_rows", index=False)

    return output_path


if __name__ == "__main__":
    files = list(Path("data/incoming").glob("ODATA_GIH_Birthday*.pdf"))
    files += list(Path("data/incoming").glob("ODATA_GIH_Birthday*.PDF"))
    files += list(Path("data/incoming").glob("odata_gih_birthday*.pdf"))
    files += list(Path("data/incoming").glob("odata_gih_birthday*.PDF"))

    if not files:
        raise FileNotFoundError(
            "No encontré ningún ODATA_GIH_Birthday*.PDF en data/incoming"
        )

    pdf = files[0]

    print(f"Using: {pdf.name}")

    out = export_debug(pdf)
    print(f"Debug exported: {out.resolve()}")