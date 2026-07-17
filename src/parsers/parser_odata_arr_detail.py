from __future__ import annotations

"""Production compatibility entry point for the ODATA Arrivals parser.

The application can continue importing::

    from src.parsers.parser_odata_arr_detail import parse_odata_arr_detail

Internally, the call is delegated to ArrivalParserV2, which is now the
validated production implementation.

This wrapper also waits for the PDF file to finish writing and retries
temporary PDF read errors. A genuinely truncated/corrupt PDF is still
reported as an error so the source email is not deleted.
"""

import time
from pathlib import Path

import pandas as pd

from ..core.pdf.pdf_engine import PdfEngineError
from .arrival_parser_v2 import (
    REPORT_NAME,
    TARGET_TABLE,
    export_debug_v2,
    parse_odata_arr_detail_v2,
)


DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_DELAY_SECONDS = 5.0
DEFAULT_STABILITY_CHECKS = 3
DEFAULT_STABILITY_DELAY_SECONDS = 1.0


class ArrivalPdfNotReadyError(RuntimeError):
    """Raised when an Arrivals PDF is incomplete, unstable or unreadable."""


def _wait_until_file_is_stable(
    pdf_path: Path,
    *,
    checks: int = DEFAULT_STABILITY_CHECKS,
    delay_seconds: float = DEFAULT_STABILITY_DELAY_SECONDS,
) -> None:
    """Wait until the PDF size remains unchanged for consecutive checks."""

    if checks < 2:
        checks = 2

    previous_size: int | None = None
    stable_count = 0

    for _ in range(checks + 5):
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        current_size = pdf_path.stat().st_size

        if current_size <= 0:
            stable_count = 0
        elif current_size == previous_size:
            stable_count += 1
        else:
            stable_count = 0

        if stable_count >= checks - 1:
            return

        previous_size = current_size
        time.sleep(delay_seconds)

    raise ArrivalPdfNotReadyError(
        f"PDF size did not stabilize before parsing: {pdf_path}"
    )


def _has_pdf_header(pdf_path: Path) -> bool:
    """Return True when the file starts with the standard PDF signature."""

    with pdf_path.open("rb") as stream:
        return stream.read(5) == b"%PDF-"


def _has_pdf_eof_marker(pdf_path: Path) -> bool:
    """Check for a PDF EOF marker near the end of the file."""

    file_size = pdf_path.stat().st_size
    read_size = min(file_size, 8192)

    with pdf_path.open("rb") as stream:
        stream.seek(-read_size, 2)
        tail = stream.read(read_size)

    return b"%%EOF" in tail


def _validate_pdf_container(pdf_path: Path) -> None:
    """Perform inexpensive checks before sending the file to pdfplumber."""

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if pdf_path.stat().st_size == 0:
        raise ArrivalPdfNotReadyError(f"PDF is empty: {pdf_path}")

    if not _has_pdf_header(pdf_path):
        raise ArrivalPdfNotReadyError(
            f"File does not contain a valid PDF header: {pdf_path}"
        )

    if not _has_pdf_eof_marker(pdf_path):
        raise ArrivalPdfNotReadyError(
            f"PDF appears truncated because %%EOF was not found: {pdf_path}"
        )


def _is_temporary_pdf_error(exc: BaseException) -> bool:
    """Identify errors worth retrying after the downloaded file settles."""

    message = str(exc).lower()

    retryable_fragments = (
        "unexpected eof",
        "end of file",
        "no /root object",
        "xref",
        "truncated",
        "could not extract pdf words",
    )

    return any(fragment in message for fragment in retryable_fragments)


def parse_odata_arr_detail(
    pdf_path: str | Path,
    *,
    strict: bool = False,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
) -> pd.DataFrame:
    """Parse an ODATA Arrivals Detail PDF using ArrivalParserV2.

    The parser waits until the file size is stable and retries temporary
    pdfminer/pdfplumber errors. If all attempts fail, the exception is
    propagated so the pipeline can mark the file as failed and retain the
    original email for a later retry.
    """

    source = Path(pdf_path)

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    last_error: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            _wait_until_file_is_stable(source)
            _validate_pdf_container(source)

            return parse_odata_arr_detail_v2(
                source,
                strict=strict,
            )

        except (PdfEngineError, ArrivalPdfNotReadyError) as exc:
            last_error = exc

            if attempt >= max_attempts or not _is_temporary_pdf_error(exc):
                break

            print(
                f"Arrival PDF read failed for {source.name} "
                f"(attempt {attempt}/{max_attempts}): {exc}"
            )
            print(
                f"Retrying in {retry_delay_seconds:.1f} seconds..."
            )
            time.sleep(retry_delay_seconds)

    raise ArrivalPdfNotReadyError(
        f"Could not parse Arrivals PDF after {max_attempts} attempts: "
        f"{source}. Last error: {last_error}"
    ) from last_error


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

    source = Path(pdf_path)

    _wait_until_file_is_stable(source)
    _validate_pdf_container(source)

    return export_debug_v2(
        source,
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
