from __future__ import annotations

from pathlib import Path
from datetime import datetime
import re
import pandas as pd
import pdfplumber


REPORT_NAME = "snapshot"
TARGET_TABLE = "snapshot"

ROW_RE = re.compile(
    r"^(?P<adults>\d+)\s+"
    r"(?P<children>\d+)\s+"
    r"(?P<child_bucket_1>\d+)\s+"
    r"(?P<child_bucket_2>\d+)\s+"
    r"(?P<child_bucket_3>\d+)\s+"
    r"(?:(?P<reservation_status>[A-Z ]+?)\s+)?"
    r"(?:(?P<confirmation_number>\d{6,})\s+)?"
    r"(?P<source_code>\S+)\s+"
    r"(?P<stay_date>\d{1,2}/\d{1,2}/\d{4})\s+"
    r"(?P<room_type>[A-Z0-9]+)\s+"
    r"(?P<room_no>\d+)"
    r"(?:\s+(?P<children_ages>[0-9\-]+))?$"
)


def clean_text(value) -> str:
    value = str(value or "").strip()
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def to_int(value):
    value = clean_text(value)
    if not value:
        return None

    try:
        return int(float(value.replace(",", "")))
    except Exception:
        return None


def to_iso_date(value: str) -> str | None:
    value = clean_text(value)
    if not value:
        return None

    try:
        return datetime.strptime(value, "%m/%d/%Y").date().isoformat()
    except Exception:
        return None


def is_noise(text: str) -> bool:
    return (
        not text
        or text.lower() == "snapshot"
        or text.startswith("Adults Children")
        or text.startswith("Child Bucket")
        or text.startswith("Reservation Status")
        or text.startswith("Confirmation Number")
        or text.startswith("Stay Date")
        or text.startswith("Room Type")
        or text.startswith("Room Children")
    )


def parse_line(text: str) -> dict | None:
    text = clean_text(text)
    match = ROW_RE.match(text)

    if not match:
        return None

    data = match.groupdict()

    return {
        "adults": data.get("adults"),
        "children": data.get("children"),
        "child_bucket_1": data.get("child_bucket_1"),
        "child_bucket_2": data.get("child_bucket_2"),
        "child_bucket_3": data.get("child_bucket_3"),
        "reservation_status": clean_text(data.get("reservation_status")),
        "confirmation_number": data.get("confirmation_number"),
        "source_code": data.get("source_code"),
        "stay_date": data.get("stay_date"),
        "room_type": clean_text(data.get("room_type")),
        "room_no": data.get("room_no"),
        "children_ages": clean_text(data.get("children_ages")),
    }


def extract_text_fast(pdf_path: Path) -> list[str]:
    lines = []

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)

        for page_no, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""

            for raw in text.splitlines():
                line = clean_text(raw)
                if line:
                    lines.append(line)

            if page_no % 50 == 0:
                print(f"snapshot: read {page_no}/{total_pages} pages")

    return lines


def parse_snapshot(pdf_path: str | Path) -> pd.DataFrame:
    pdf_path = Path(pdf_path)

    rows = []

    current_confirmation_number = None
    current_reservation_status = None

    lines = extract_text_fast(pdf_path)

    for text in lines:
        if is_noise(text):
            continue

        parsed = parse_line(text)

        if not parsed:
            continue

        if parsed.get("confirmation_number"):
            current_confirmation_number = parsed["confirmation_number"]
        else:
            parsed["confirmation_number"] = current_confirmation_number

        if parsed.get("reservation_status"):
            current_reservation_status = parsed["reservation_status"]
        else:
            parsed["reservation_status"] = current_reservation_status

        parsed["source_report"] = REPORT_NAME
        parsed["source_file"] = pdf_path.name

        rows.append(parsed)

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    for col in [
        "adults",
        "children",
        "child_bucket_1",
        "child_bucket_2",
        "child_bucket_3",
        "confirmation_number",
        "room_no",
    ]:
        if col in df.columns:
            df[col] = df[col].apply(to_int)

    for col in [
        "reservation_status",
        "room_type",
        "children_ages",
    ]:
        if col in df.columns:
            df[col] = df[col].apply(clean_text)

    df["stay_date"] = df["stay_date"].apply(to_iso_date)

    final_columns = [
        "confirmation_number",
        "reservation_status",
        "stay_date",
        "adults",
        "children",
        "child_bucket_1",
        "child_bucket_2",
        "child_bucket_3",
        "room_type",
        "room_no",
        "children_ages",
        "source_code",
        "source_report",
        "source_file",
    ]

    return df[[c for c in final_columns if c in df.columns]]


def export_debug(
    pdf_path: str | Path,
    output_path: str | Path = "data/debug/snapshot/snapshot_debug.xlsx",
) -> Path:
    pdf_path = Path(pdf_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    parsed = parse_snapshot(pdf_path)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        parsed.to_excel(writer, sheet_name="parsed_rows", index=False)

    return output_path


if __name__ == "__main__":
    files = list(Path("data/incoming").glob("snapshot*.pdf"))
    files += list(Path("data/incoming").glob("snapshot*.PDF"))

    if not files:
        raise FileNotFoundError(
            "No encontré ningún snapshot*.PDF en data/incoming"
        )

    pdf = files[0]

    print(f"Using: {pdf.name}")

    out = export_debug(pdf)

    print(f"Debug exported: {out.resolve()}")