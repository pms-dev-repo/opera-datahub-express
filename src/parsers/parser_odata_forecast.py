from __future__ import annotations

from pathlib import Path
from datetime import datetime
import re
import pandas as pd

from .pdf_engine import PdfEngine


REPORT_NAME = "ODATA_Forecast"
TARGET_TABLE = "odata_forecast"

DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{2}$")

COLUMNS = {
    "business_date": (0, 42),
    "day": (42, 80),
    "adults": (80, 118),
    "children": (118, 150),
    "total_guests": (150, 180),
    "arrival_rooms_deducted": (180, 218),
    "departure_rooms_deducted": (218, 258),
    "occ_rooms_deducted": (258, 298),
    "occ_pct_rooms_deducted": (298, 348),
    "occ_rooms_non_deducted": (348, 390),
    "occ_pct_rooms_non_deducted": (390, 440),
    "ooo_rooms": (440, 475),
    "oos_rooms": (475, 500),
    "block_rooms_deducted": (500, 535),
    "block_rooms_non_deducted": (535, 575),
    "room_revenue_deducted": (575, 650),
    "avg_room_deducted": (650, 705),
    "other_revenue": (705, 760),
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


def to_float(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except Exception:
        return None


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


def is_forecast_row(row: dict) -> bool:
    return DATE_RE.match(str(row.get("business_date") or "").strip()) is not None


def parse_odata_forecast(pdf_path: str | Path) -> pd.DataFrame:
    pdf_path = Path(pdf_path)
    engine = PdfEngine(pdf_path)

    lines_df = engine.group_lines()

    rows = []
    current_section = None

    for _, line in lines_df.iterrows():
        text = str(line["text"]).strip()
        words = line["words"]

        if not text:
            continue

        if text in (
            "Individual Reservations",
            "Block Reservations",
            "Block Rooms Not Picked Up",
            "All Reservations And Block Rooms Not Picked Up Combined",
        ):
            current_section = text
            continue

        if text.startswith("Total "):
            continue

        parsed = extract_columns(words)

        if not is_forecast_row(parsed):
            continue

        parsed["forecast_section"] = current_section
        parsed["source_report"] = REPORT_NAME
        parsed["source_file"] = pdf_path.name

        rows.append(parsed)

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    df["business_date"] = df["business_date"].apply(to_iso_date)

    int_cols = [
        "adults",
        "children",
        "total_guests",
        "arrival_rooms_deducted",
        "departure_rooms_deducted",
        "occ_rooms_deducted",
        "occ_rooms_non_deducted",
        "ooo_rooms",
        "oos_rooms",
        "block_rooms_deducted",
        "block_rooms_non_deducted",
    ]

    float_cols = [
        "occ_pct_rooms_deducted",
        "occ_pct_rooms_non_deducted",
        "room_revenue_deducted",
        "avg_room_deducted",
        "other_revenue",
    ]

    for col in int_cols:
        if col in df.columns:
            df[col] = df[col].apply(to_int)

    for col in float_cols:
        if col in df.columns:
            df[col] = df[col].apply(to_float)

    final_columns = [
        "forecast_section",
        "business_date",
        "day",
        "adults",
        "children",
        "total_guests",
        "arrival_rooms_deducted",
        "departure_rooms_deducted",
        "occ_rooms_deducted",
        "occ_pct_rooms_deducted",
        "occ_rooms_non_deducted",
        "occ_pct_rooms_non_deducted",
        "ooo_rooms",
        "oos_rooms",
        "block_rooms_deducted",
        "block_rooms_non_deducted",
        "room_revenue_deducted",
        "avg_room_deducted",
        "other_revenue",
        "source_report",
        "source_file",
    ]

    return df[[c for c in final_columns if c in df.columns]]


def export_debug(
    pdf_path: str | Path,
    output_path: str | Path = "data/debug/ODATA_Forecast/odata_forecast_debug.xlsx",
) -> Path:
    pdf_path = Path(pdf_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    engine = PdfEngine(pdf_path)

    words = engine.extract_words()
    lines = engine.group_lines()
    parsed = parse_odata_forecast(pdf_path)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        words.to_excel(writer, sheet_name="raw_words", index=False)
        lines.drop(columns=["words"], errors="ignore").to_excel(writer, sheet_name="lines", index=False)
        engine.export_line_words(writer)
        parsed.to_excel(writer, sheet_name="parsed_rows", index=False)

    return output_path


if __name__ == "__main__":
    pdf = Path("data/incoming/ODATA_Forecast.PDF")

    if not pdf.exists():
        raise FileNotFoundError(f"No encontré el PDF aquí: {pdf.resolve()}")

    out = export_debug(pdf)
    print(f"Debug exported: {out.resolve()}")