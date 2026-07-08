from __future__ import annotations

from pathlib import Path
from datetime import datetime
import re
import pandas as pd

from .pdf_engine import PdfEngine
from .pdf_repair import repair_pdf


REPORT_NAME = "ODATA_Transportation"
TARGET_TABLE = "odata_transportation"

DATETIME_RE = re.compile(r"\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}")

KNOWN_TRANSPORT_TYPES = {
    "MER/BMW/LUXURY CAR",
    "Mercedes",
    "Own Car",
    "Rolls Royce Phantom",
    "Van",
    "Van & Luggage car",
}

COLUMNS = {
    "guest_name": (0, 165),
    "transport_datetime": (165, 255),
    "station_code": (255, 330),
    "carrier_code": (330, 405),
    "transport_code": (405, 495),
    "adults": (495, 522),
    "children": (522, 556),
    "stay_date": (556, 600),
    "reservation_status": (600, 650),
    "room_no": (650, 700),
    "vip": (700, 760),
}


def clean_text(value) -> str:
    value = str(value or "").strip()
    value = value.replace("\ufffe", "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def to_iso_date(value: str) -> str | None:
    value = clean_text(value)
    if not value:
        return None

    try:
        return datetime.strptime(value, "%d-%m-%y").date().isoformat()
    except Exception:
        return None


def to_iso_datetime(value: str) -> str | None:
    value = clean_text(value)
    if not value:
        return None

    try:
        return datetime.strptime(value, "%d-%m-%y %H:%M").isoformat(sep=" ")
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


def build_engine(pdf_path: Path) -> tuple[PdfEngine, Path]:
    try:
        engine = PdfEngine(pdf_path)
        engine.group_lines()
        return engine, pdf_path

    except Exception as exc:
        print(f"PDF read failed for {pdf_path.name}: {exc}")
        print(f"Repairing PDF: {pdf_path.name}")

        repaired_path = repair_pdf(pdf_path)

        engine = PdfEngine(repaired_path)
        engine.group_lines()

        return engine, repaired_path


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


def detect_direction(text: str) -> str | None:
    if "Transport Type (PickUp)" in text:
        return "PICKUP"

    if "Transport Type (Drop Off)" in text:
        return "DROPOFF"

    return None


def detect_transport_type(text: str) -> str | None:
    text = clean_text(text)

    for transport_type in KNOWN_TRANSPORT_TYPES:
        if text == transport_type:
            return transport_type

        if text.endswith(transport_type):
            return transport_type

    return None


def is_noise(text: str) -> bool:
    noise_contains = (
        "Sandy Lane",
        "ODATA_Transportation",
        "Filter:",
        "Transport Type All",
        "Reservation Status All",
        "Sort Order",
        "Page ",
        "transreq",
        "Guest Name",
        "Pick Up Date / Time",
        "Drop Off Date / Time",
        "Arr. Date",
        "Dep. Date",
        "Station Code",
        "Carrier Code",
        "Transport Code",
        "Adults",
        "Room",
        "VIP",
        "Children",
        "Resv. Status",
    )

    return any(n in text for n in noise_contains)


def looks_like_transport_row(row: dict) -> bool:
    return DATETIME_RE.fullmatch(clean_text(row.get("transport_datetime"))) is not None


def append_continuation(rows: list, words: list, text: str) -> None:
    if not rows or not words:
        return

    min_x = min(float(w["x0"]) for w in words)

    if 405 <= min_x < 495:
        rows[-1]["transport_code"] = clean_text(
            str(rows[-1].get("transport_code") or "") + " " + text
        )

    elif 330 <= min_x < 405:
        rows[-1]["carrier_code"] = clean_text(
            str(rows[-1].get("carrier_code") or "") + " " + text
        )


def parse_odata_transportation(pdf_path: str | Path) -> pd.DataFrame:
    original_pdf_path = Path(pdf_path)

    engine, readable_pdf_path = build_engine(original_pdf_path)

    lines_df = engine.group_lines()

    rows = []

    current_direction = None
    current_transport_type = None

    for _, line in lines_df.iterrows():
        text = clean_text(line["text"])
        words = line["words"]

        if not text:
            continue

        direction = detect_direction(text)
        transport_type = detect_transport_type(text)

        if direction:
            current_direction = direction
            if transport_type:
                current_transport_type = transport_type
            continue

        if transport_type:
            current_transport_type = transport_type
            continue

        if is_noise(text):
            continue

        parsed = extract_columns(words)

        if looks_like_transport_row(parsed):
            parsed["transport_direction"] = current_direction
            parsed["transport_type"] = current_transport_type
            parsed["source_report"] = REPORT_NAME
            parsed["source_file"] = original_pdf_path.name

            rows.append(parsed)
            continue

        append_continuation(rows, words, text)

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    for col in [
        "guest_name",
        "station_code",
        "carrier_code",
        "transport_code",
        "reservation_status",
        "vip",
        "transport_direction",
        "transport_type",
    ]:
        if col in df.columns:
            df[col] = df[col].apply(clean_text)

    df["transport_datetime"] = df["transport_datetime"].apply(to_iso_datetime)
    df["transport_date"] = df["transport_datetime"].str[:10]
    df["stay_date"] = df["stay_date"].apply(to_iso_date)

    for col in ["adults", "children", "room_no"]:
        if col in df.columns:
            df[col] = df[col].apply(to_int)

    final_columns = [
        "transport_direction",
        "transport_type",
        "guest_name",
        "transport_datetime",
        "transport_date",
        "stay_date",
        "station_code",
        "carrier_code",
        "transport_code",
        "adults",
        "children",
        "room_no",
        "vip",
        "reservation_status",
        "source_report",
        "source_file",
    ]

    return df[[c for c in final_columns if c in df.columns]]


def export_debug(
    pdf_path: str | Path,
    output_path: str | Path = "data/debug/ODATA_Transportation/odata_transportation_debug.xlsx",
) -> Path:
    original_pdf_path = Path(pdf_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    engine, _ = build_engine(original_pdf_path)

    words = engine.extract_words()
    lines = engine.group_lines()
    parsed = parse_odata_transportation(original_pdf_path)

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
    files = list(Path("data/incoming").glob("ODATA_Transportation*.pdf"))
    files += list(Path("data/incoming").glob("ODATA_Transportation*.PDF"))
    files += list(Path("data/incoming").glob("odata_transportation*.pdf"))
    files += list(Path("data/incoming").glob("odata_transportation*.PDF"))

    if not files:
        raise FileNotFoundError(
            "No encontré ningún ODATA_Transportation*.PDF en data/incoming"
        )

    pdf = files[0]

    print(f"Using: {pdf.name}")

    out = export_debug(pdf)
    print(f"Debug exported: {out.resolve()}")