from __future__ import annotations

"""Production compatibility entry point for the ODATA Arrivals parser.

The application can continue importing::

    from src.parsers.parser_odata_arr_detail import parse_odata_arr_detail

Internally, the call is delegated to ArrivalParserV2, which is now the
validated production implementation.
"""

from pathlib import Path

import pandas as pd

from .arrival_parser_v2 import (
    REPORT_NAME,
    TARGET_TABLE,
    export_debug_v2,
    parse_odata_arr_detail_v2,
)


def parse_odata_arr_detail(
    pdf_path: str | Path,
    *,
    strict: bool = False,
) -> pd.DataFrame:
    """Parse an ODATA Arrivals Detail PDF using ArrivalParserV2."""
    return parse_odata_arr_detail_v2(
        pdf_path,
        strict=strict,
    )


def export_debug(
    pdf_path: str | Path,
    output_path: str | Path = (
        "data/debug/ODATA_arr_detail/"
        "odata_arr_detail_v2_debug.xlsx"
    ),
    *,
    strict: bool = False,
) -> Path:
    """Export the V2 engine, reservation blocks and parsed rows."""
    return export_debug_v2(
        pdf_path,
        output_path=output_path,
        strict=strict,
    )


if __name__ == "__main__":
    patterns = (
        "ODATA_arr_detail*.pdf",
        "ODATA_arr_detail*.PDF",
        "odata_arr_detail*.pdf",
        "odata_arr_detail*.PDF",
    )

    files: list[Path] = []

    for pattern in patterns:
        files.extend(Path("data/incoming").glob(pattern))

    if not files:
        raise FileNotFoundError(
            "No ODATA_arr_detail PDF was found in data/incoming"
        )

    source = sorted(set(files))[0]

    print(f"Using: {source.name}")

    dataframe = parse_odata_arr_detail(source)
    print(dataframe)
    print(f"Rows: {len(dataframe)}")

    output = export_debug(source)
    print(f"Debug exported: {output.resolve()}")
