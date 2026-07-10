from __future__ import annotations

from pathlib import Path
from datetime import datetime
import re

import pandas as pd
import pdfplumber


REPORT_NAME = "snapshot"
TARGET_TABLE = "snapshot"


DATE_RE = re.compile(
    r"^\d{1,2}/\d{1,2}/\d{4}$"
)

CONFIRMATION_RE = re.compile(
    r"^\d{6,}$"
)

SOURCE_CODE_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9_./-]*$"
)

CHILDREN_AGES_RE = re.compile(
    r"^\d+(?:-\d+)*$"
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
        return datetime.strptime(
            value,
            "%m/%d/%Y",
        ).date().isoformat()

    except Exception:
        return None


def is_noise(text: str) -> bool:
    text = clean_text(text)

    return (
        not text
        or text.lower() == "snapshot"
        or text.startswith("Adults Children")
        or text.startswith("Child Bucket")
        or text.startswith("Reservation Status")
        or text.startswith("Confirmation Number")
        or text.startswith("Source Code")
        or text.startswith("Stay Date")
        or text.startswith("Room Type")
        or text.startswith("Room Children")
        or text in {
            "Adults",
            "Children",
            "Child",
            "Bucket",
            "Reservation",
            "Status",
            "Confirmation",
            "Number",
            "Stay",
            "Date",
            "Room",
            "Type",
            "Ages",
            "Source",
            "Code",
            "IN",
        }
    )


def find_date_index(tokens: list[str]) -> int | None:
    for index, token in enumerate(tokens):
        if DATE_RE.fullmatch(token):
            return index

    return None


def parse_line(text: str) -> dict | None:
    """
    Expected layouts:

    New PDF, without child ages:
        2 0 0 0 0 CHECKED IN 2079404 7/6/2026 ORR 330 DIR

    New PDF, with child ages:
        1 2 0 0 2 2079405 7/6/2026 ORR 331 13-16 DIR

    Old PDF, without source code:
        2 0 0 0 0 CHECKED IN 2079404 7/6/2026 ORR 330

    Old PDF, with child ages:
        1 2 0 0 2 2079405 7/6/2026 ORR 331 13-16
    """

    text = clean_text(text)

    if not text:
        return None

    tokens = text.split()

    if len(tokens) < 8:
        return None

    # Las primeras cinco columnas siempre deben ser numéricas.
    first_five = tokens[:5]

    if not all(token.isdigit() for token in first_five):
        return None

    date_index = find_date_index(tokens[5:])

    if date_index is None:
        return None

    # Ajustar el índice porque buscamos desde tokens[5:].
    date_index += 5

    stay_date = tokens[date_index]

    before_date = tokens[5:date_index]
    after_date = tokens[date_index + 1:]

    # Después de la fecha deben venir como mínimo Room Type y Room.
    if len(after_date) < 2:
        return None

    adults = tokens[0]
    children = tokens[1]
    child_bucket_1 = tokens[2]
    child_bucket_2 = tokens[3]
    child_bucket_3 = tokens[4]

    reservation_status = ""
    confirmation_number = None

    # El Confirmation Number, cuando aparece, es el último valor
    # antes de Stay Date y contiene al menos seis dígitos.
    if before_date and CONFIRMATION_RE.fullmatch(before_date[-1]):
        confirmation_number = before_date[-1]
        reservation_status = " ".join(before_date[:-1])

    else:
        reservation_status = " ".join(before_date)

    room_type = after_date[0]
    room_no = after_date[1]

    extras = after_date[2:]

    children_ages = ""
    source_code = ""

    # Source Code viene al final y comienza con una letra:
    # DIR, TOP, TRV, etc.
    if extras and SOURCE_CODE_RE.fullmatch(extras[-1]):
        source_code = extras.pop()

    # Lo que queda corresponde a Children Ages.
    # Ejemplos: 1, 10, 13-16, 3-9-12.
    if extras:
        possible_ages = "-".join(extras)

        if CHILDREN_AGES_RE.fullmatch(possible_ages):
            children_ages = possible_ages
        else:
            children_ages = " ".join(extras)

    return {
        "adults": adults,
        "children": children,
        "child_bucket_1": child_bucket_1,
        "child_bucket_2": child_bucket_2,
        "child_bucket_3": child_bucket_3,
        "reservation_status": clean_text(
            reservation_status
        ),
        "confirmation_number": confirmation_number,
        "stay_date": stay_date,
        "room_type": clean_text(room_type),
        "room_no": room_no,
        "children_ages": clean_text(children_ages),
        "source_code": clean_text(source_code),
    }


def extract_text_fast(
    pdf_path: Path,
) -> list[str]:
    lines: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)

        for page_no, page in enumerate(
            pdf.pages,
            start=1,
        ):
            text = page.extract_text() or ""

            for raw in text.splitlines():
                line = clean_text(raw)

                if line:
                    lines.append(line)

            if page_no % 50 == 0:
                print(
                    f"snapshot: read "
                    f"{page_no}/{total_pages} pages"
                )

    return lines


def parse_snapshot(
    pdf_path: str | Path,
) -> pd.DataFrame:
    pdf_path = Path(pdf_path)

    rows: list[dict] = []

    current_confirmation_number = None
    current_reservation_status = None

    lines = extract_text_fast(pdf_path)

    for text in lines:
        if is_noise(text):
            continue

        parsed = parse_line(text)

        if not parsed:
            continue

        # Confirmation Number se muestra una vez por reserva
        # y queda vacío en las líneas siguientes.
        if parsed.get("confirmation_number"):
            current_confirmation_number = parsed[
                "confirmation_number"
            ]
        else:
            parsed[
                "confirmation_number"
            ] = current_confirmation_number

        # Reservation Status funciona igual:
        # aparece al comienzo de cada bloque.
        if parsed.get("reservation_status"):
            current_reservation_status = parsed[
                "reservation_status"
            ]
        else:
            parsed[
                "reservation_status"
            ] = current_reservation_status

        # IMPORTANTE:
        # Source Code NO se arrastra.
        # Una misma reserva puede cambiar de DIR a TOP
        # dependiendo de la fecha de estadía.

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
        "source_code",
        "room_type",
        "children_ages",
    ]:
        if col in df.columns:
            df[col] = df[col].apply(clean_text)

    if "stay_date" in df.columns:
        df["stay_date"] = df["stay_date"].apply(
            to_iso_date
        )

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
        "data/debug/snapshot/snapshot_debug.xlsx"
    ),
) -> Path:
    pdf_path = Path(pdf_path)
    output_path = Path(output_path)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    raw_lines = extract_text_fast(pdf_path)
    parsed = parse_snapshot(pdf_path)

    parsed_line_tests = []

    for line_number, text in enumerate(
        raw_lines,
        start=1,
    ):
        parsed_line = parse_line(text)

        parsed_line_tests.append(
            {
                "line_number": line_number,
                "text": text,
                "parsed": parsed_line is not None,
                "confirmation_number": (
                    parsed_line.get("confirmation_number")
                    if parsed_line
                    else None
                ),
                "stay_date": (
                    parsed_line.get("stay_date")
                    if parsed_line
                    else None
                ),
                "room_type": (
                    parsed_line.get("room_type")
                    if parsed_line
                    else None
                ),
                "room_no": (
                    parsed_line.get("room_no")
                    if parsed_line
                    else None
                ),
                "children_ages": (
                    parsed_line.get("children_ages")
                    if parsed_line
                    else None
                ),
                "source_code": (
                    parsed_line.get("source_code")
                    if parsed_line
                    else None
                ),
            }
        )

    with pd.ExcelWriter(
        output_path,
        engine="openpyxl",
    ) as writer:
        pd.DataFrame(
            {
                "line_number": range(
                    1,
                    len(raw_lines) + 1,
                ),
                "text": raw_lines,
            }
        ).to_excel(
            writer,
            sheet_name="raw_lines",
            index=False,
        )

        pd.DataFrame(
            parsed_line_tests
        ).to_excel(
            writer,
            sheet_name="line_tests",
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
        Path("data/incoming").glob(
            "snapshot*.pdf"
        )
    )

    files += list(
        Path("data/incoming").glob(
            "snapshot*.PDF"
        )
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