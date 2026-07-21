from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

import pandas as pd
import pdfplumber


REPORT_NAME = "snapshot"
TARGET_TABLE = "snapshot"

DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")


# Fixed horizontal positions of the OPERA Snapshot report.
# The new fields were added at the end of the report:
# UDFD01 | First Name | Last Name | VIP Code
COLUMN_RANGES = {
    "adults": (50, 95),
    "children": (95, 128),
    "child_bucket_1": (128, 161),
    "child_bucket_2": (161, 194),
    "child_bucket_3": (194, 222),
    "reservation_status": (222, 274),
    "confirmation_number": (274, 330),
    "stay_date": (330, 377),
    "room_type": (377, 406),
    "room_no": (406, 435),
    "children_ages": (435, 488),
    "source_code": (488, 520),
    "rate_code": (520, 577),
    "anniversary_date": (577, 622),
    "first_name": (622, 681),
    "last_name": (681, 750),
    "vip_code": (750, 805),
}


FINAL_COLUMNS = [
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
    "rate_code",
    "anniversary_date",
    "first_name",
    "last_name",
    "vip_code",
    "source_report",
    "source_file",
]


def clean_text(value) -> str:
    if value is None:
        return ""

    value = str(value).replace("\n", " ").strip()
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


def detect_date_format(values: list[str]) -> str:
    """
    Detect DD/MM/YYYY versus MM/DD/YYYY from unambiguous dates.

    Current report:
        17/07/2026 -> DD/MM/YYYY

    Previous report:
        7/17/2026 -> MM/DD/YYYY
    """
    for value in values:
        match = re.search(r"\d{1,2}/\d{1,2}/\d{4}", clean_text(value))

        if not match:
            continue

        first, second, _ = match.group(0).split("/")

        if int(first) > 12:
            return "%d/%m/%Y"

        if int(second) > 12:
            return "%m/%d/%Y"

    return "%d/%m/%Y"


def to_iso_date(value: str, preferred_format: str) -> str | None:
    value = clean_text(value)

    if not value:
        return None

    # UDFD01 includes a time under the date, for example:
    # 07/09/1974 0:00:00
    match = re.search(r"\d{1,2}/\d{1,2}/\d{4}", value)

    if not match:
        return None

    date_value = match.group(0)

    formats = [preferred_format]

    for fallback in ("%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d"):
        if fallback not in formats:
            formats.append(fallback)

    for fmt in formats:
        try:
            return datetime.strptime(date_value, fmt).date().isoformat()
        except ValueError:
            continue

    return None


def words_in_range(
    words: list[dict],
    x_min: float,
    x_max: float,
    top_min: float,
    top_max: float,
) -> str:
    selected = [
        word
        for word in words
        if x_min <= float(word["x0"]) < x_max
        and top_min <= float(word["top"]) < top_max
    ]

    selected.sort(
        key=lambda word: (
            round(float(word["top"]), 1),
            float(word["x0"]),
        )
    )

    return clean_text(
        " ".join(str(word["text"]) for word in selected)
    )


def extract_page_rows(page) -> list[dict]:
    """
    Extract rows from word coordinates.

    This is considerably faster than page.extract_tables() and preserves
    multi-line fields such as CHECKED IN and UDFD01's 0:00:00 time.
    """
    words = page.extract_words(
        use_text_flow=False,
        keep_blank_chars=False,
    )

    if not words:
        return []

    # Every data row begins with the Adults value in the first column.
    row_starts = sorted(
        {
            round(float(word["top"]), 3)
            for word in words
            if 50 <= float(word["x0"]) < 95
            and clean_text(word["text"]).isdigit()
            and float(word["top"]) > 90
        }
    )

    rows: list[dict] = []

    for index, row_top in enumerate(row_starts):
        next_top = (
            row_starts[index + 1]
            if index + 1 < len(row_starts)
            else page.height
        )

        # A small tolerance keeps second-line values inside the row,
        # while preventing words from the next row from being included.
        row_bottom = next_top - 0.2

        row = {
            column: words_in_range(
                words,
                x_min,
                x_max,
                row_top - 0.5,
                row_bottom,
            )
            for column, (x_min, x_max) in COLUMN_RANGES.items()
        }

        if DATE_RE.fullmatch(row.get("stay_date", "")):
            rows.append(row)

    return rows


def extract_rows(pdf_path: Path) -> list[dict]:
    rows: list[dict] = []

    current_confirmation_number = ""
    current_reservation_status = ""

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)

        for page_number, page in enumerate(pdf.pages, start=1):
            page_rows = extract_page_rows(page)

            for row in page_rows:
                confirmation_number = clean_text(
                    row.get("confirmation_number")
                )

                if confirmation_number:
                    current_confirmation_number = confirmation_number
                else:
                    row["confirmation_number"] = (
                        current_confirmation_number
                    )

                reservation_status = clean_text(
                    row.get("reservation_status")
                )

                if reservation_status:
                    current_reservation_status = reservation_status
                else:
                    row["reservation_status"] = (
                        current_reservation_status
                    )

                row["source_report"] = REPORT_NAME
                row["source_file"] = pdf_path.name
                row["_page_number"] = page_number

                rows.append(row)

            if page_number % 50 == 0:
                print(
                    f"snapshot: read "
                    f"{page_number}/{total_pages} pages"
                )

    return rows


def parse_snapshot(pdf_path: str | Path) -> pd.DataFrame:
    pdf_path = Path(pdf_path)

    rows = extract_rows(pdf_path)
    df = pd.DataFrame(rows)

    if df.empty:
        return df

    date_format = detect_date_format(
        df["stay_date"].dropna().astype(str).tolist()
    )

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
        "source_code",
        "rate_code",
        "first_name",
        "last_name",
        "vip_code",
    ]:
        if col not in df.columns:
            df[col] = None
        else:
            df[col] = df[col].apply(clean_text)
            df[col] = df[col].replace("", None)

    df["stay_date"] = df["stay_date"].apply(
        lambda value: to_iso_date(value, date_format)
    )

    if "anniversary_date" not in df.columns:
        df["anniversary_date"] = None
    else:
        df["anniversary_date"] = df["anniversary_date"].apply(
            lambda value: to_iso_date(value, date_format)
        )

    for col in FINAL_COLUMNS:
        if col not in df.columns:
            df[col] = None

    return df[FINAL_COLUMNS]


def export_debug(
    pdf_path: str | Path,
    output_path: str | Path = (
        "data/debug/snapshot/snapshot_debug.xlsx"
    ),
) -> Path:
    pdf_path = Path(pdf_path)
    output_path = Path(output_path)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    raw_rows = extract_rows(pdf_path)
    parsed = parse_snapshot(pdf_path)

    with pd.ExcelWriter(
        output_path,
        engine="openpyxl",
    ) as writer:
        pd.DataFrame(raw_rows).to_excel(
            writer,
            sheet_name="raw_rows",
            index=False,
        )

        parsed.to_excel(
            writer,
            sheet_name="parsed_rows",
            index=False,
        )

    return output_path


if __name__ == "__main__":
    files = list(
        Path("data/incoming").glob("snapshot*.pdf")
    )

    files += list(
        Path("data/incoming").glob("snapshot*.PDF")
    )

    if not files:
        raise FileNotFoundError(
            "No encontré ningún snapshot*.PDF "
            "en data/incoming"
        )

    pdf = files[0]

    print(f"Using: {pdf.name}")

    out = export_debug(pdf)

    print(f"Debug exported: {out.resolve()}")
