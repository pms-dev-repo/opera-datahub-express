from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from .utils import read_standard_csv, clean_col
from ..parsers.parser_odata_arr_detail import parse_odata_arr_detail
from ..parsers.parser_odata_departures_all import parse_odata_departures_all
from ..parsers.parser_odata_forecast import parse_odata_forecast
from ..parsers.parser_odata_transportation import parse_odata_transportation
from ..parsers.parser_odata_gih_birthday import parse_odata_gih_birthday
from ..parsers.parser_snapshot import parse_snapshot


PREFIX_MAP = {
    "snaps": "snaps",
    "resfu": "resfu",
    "pr_bi": "pr_bi",
    "depar": "depar",
    "trans": "trans",
    "res_d": "res_d",
}


def read_res_detail_csv(path: Path) -> pd.DataFrame:
    raw_lines = path.read_text(
        encoding="utf-8-sig",
        errors="replace"
    ).splitlines()

    if not raw_lines:
        return pd.DataFrame()

    header = raw_lines[0]
    header_cols = next(csv.reader([header], delimiter="|"))
    expected_cols = len(header_cols)

    records = []
    current = ""

    record_start = re.compile(r"^\d{8}\|")

    for line in raw_lines[1:]:
        if not line.strip():
            continue

        if record_start.match(line):
            if current:
                records.append(current)

            current = line
        else:
            current += "|" + line

    if current:
        records.append(current)

    fixed_rows = []

    for record in records:
        row = next(csv.reader([record], delimiter="|"))

        if len(row) > expected_cols:
            row = row[:expected_cols]

        elif len(row) < expected_cols:
            row += [""] * (expected_cols - len(row))

        fixed_rows.append(row)

    return pd.DataFrame(fixed_rows, columns=header_cols)


def process_file(path: Path) -> tuple[str, pd.DataFrame]:
    if path.suffix.lower() == ".pdf":

        if path.stem.upper().startswith("ODATA_ARR_DETAIL"):
            df = parse_odata_arr_detail(path)
            return "odata_arr_detail", df

        if path.stem.upper().startswith("ODATA_DEPARTURES_ALL"):
            df = parse_odata_departures_all(path)
            return "odata_departures_all", df

        if path.stem.upper().startswith("ODATA_FORECAST"):
            df = parse_odata_forecast(path)
            return "odata_forecast", df

        if path.stem.upper().startswith("ODATA_TRANSPORTATION"):
            df = parse_odata_transportation(path)
            return "odata_transportation", df

        if path.stem.upper().startswith("ODATA_GIH_BIRTHDAY"):
            df = parse_odata_gih_birthday(path)
            return "odata_gih_birthday", df

        if path.stem.upper().startswith("SNAPSHOT"):
            df = parse_snapshot(path)
            return "snapshot", df

        raise ValueError(
            f"No parser configured for PDF {path.name}"
        )

    prefix = path.name[:5].lower()

    if prefix not in PREFIX_MAP:
        raise ValueError(
            f"Unknown report prefix '{prefix}' for file {path.name}"
        )

    table = PREFIX_MAP[prefix]

    if prefix == "res_d":
        df = read_res_detail_csv(path)
    else:
        df = read_standard_csv(path)

    df.columns = [clean_col(c) for c in df.columns]
    df["source_file"] = path.name

    return table, df