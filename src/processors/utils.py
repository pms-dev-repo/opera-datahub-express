from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path
import pandas as pd

DATE_FORMATS = ["%d-%b-%y", "%d-%m-%y", "%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"]


def clean_col(name: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower())).strip("_")


def parse_date(value):
    if pd.isna(value) or str(value).strip() == "":
        return None
    s = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s.title(), fmt).date()
        except ValueError:
            pass
    try:
        return pd.to_datetime(s, errors="coerce").date()
    except Exception:
        return None


def parse_datetime(value):
    if pd.isna(value) or str(value).strip() == "":
        return None
    s = re.sub(r"\s+", " ", str(value).strip())
    for fmt in ["%d-%m-%y %H:%M", "%d-%b-%y %H:%M", "%Y-%m-%d %H:%M:%S"]:
        try:
            return datetime.strptime(s.title(), fmt)
        except ValueError:
            pass
    return pd.to_datetime(s, errors="coerce")


def to_int(value):
    try:
        if pd.isna(value) or str(value).strip() == "":
            return None
        return int(float(str(value).replace(",", "")))
    except Exception:
        return None


def to_float(value):
    try:
        if pd.isna(value) or str(value).strip() == "":
            return None
        return float(str(value).replace(",", ""))
    except Exception:
        return None

def read_standard_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(
        path,
        sep="|",
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
        engine="python",
        on_bad_lines="skip",
    )


def read_opera_guest_csv(path: Path, name_col: str, name_parts: int = 3) -> pd.DataFrame:
    """Reads OPERA CSVs where names are exported as Last, First, Title without quotes.
    The function merges name_parts fields into one logical name column, then pads/truncates.
    """
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return pd.DataFrame()
    headers = rows[0]
    expected = len(headers)
    name_idx = headers.index(name_col)
    fixed = []
    for row in rows[1:]:
        if not row or len(row) == 1 or row[0].startswith("CF_") or row[0].startswith("SUM"):
            continue
        if len(row) >= name_idx + name_parts:
            merged_name = " ".join([x.strip() for x in row[name_idx:name_idx + name_parts] if x.strip()])
            row = row[:name_idx] + [merged_name] + row[name_idx + name_parts:]
        if len(row) < expected:
            row = row + [None] * (expected - len(row))
        fixed.append(row[:expected])
    return pd.DataFrame(fixed, columns=headers)
