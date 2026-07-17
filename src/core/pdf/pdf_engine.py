"""Generic PDF extraction engine for OPERA-style reports.

This module is intentionally report-agnostic. It extracts words, groups them
into logical lines, detects wide visual rectangles (the alternating gray bands
used by many OPERA reports), and aggregates lines into visual blocks.

It does not know about arrivals, departures, reservations, flights, or any
other report-specific concept. Those rules belong in report profiles and
parsers.
"""

from __future__ import annotations


from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pdfplumber

from src.core.pdf.debug_exporter import DebugExporter
from src.core.pdf.models import Band, Block, Line, Word


class PdfEngineError(RuntimeError):
    """Raised when the PDF engine cannot process a document."""


class PdfEngine:
    """Extract generic visual structure from a PDF.

    The DataFrame-returning methods preserve compatibility with the current
    DataHub Express parsers while typed methods are provided for the new engine.

    Parameters
    ----------
    pdf_path:
        Path to the source PDF.
    line_tolerance:
        Maximum vertical difference, in PDF points, for words to be considered
        part of the same logical line.
    gray_tolerance:
        Allowed difference from ``gray_brightness`` when detecting wide gray
        rectangles.
    gray_brightness:
        Expected brightness of OPERA's light-gray alternating row background.
    min_band_width_ratio:
        Minimum rectangle width as a fraction of the page width.
    min_band_height:
        Minimum rectangle height in PDF points.
    """

    WORD_COLUMNS = [
        "page_number",
        "word_index",
        "text",
        "x0",
        "x1",
        "top",
        "bottom",
        "doctop",
        "width",
        "height",
        "band_id",
        "shade",
        "band_top",
        "band_bottom",
    ]

    LINE_COLUMNS = [
        "page_number",
        "line_number",
        "text",
        "x0",
        "x1",
        "top",
        "bottom",
        "band_id",
        "shade",
        "band_top",
        "band_bottom",
        "words",
    ]

    BAND_COLUMNS = [
        "page_number",
        "band_id",
        "top",
        "bottom",
        "shade",
    ]

    BLOCK_COLUMNS = [
        "page_number",
        "block_id",
        "band_id",
        "shade",
        "band_top",
        "band_bottom",
        "line_count",
        "text",
        "lines",
    ]

    def __init__(
        self,
        pdf_path: str | Path,
        line_tolerance: float = 2.5,
        gray_tolerance: float = 0.025,
        gray_brightness: float = 0.96,
        min_band_width_ratio: float = 0.85,
        min_band_height: float = 8.0,
    ) -> None:
        self.pdf_path = Path(pdf_path)
        self.line_tolerance = float(line_tolerance)
        self.gray_tolerance = float(gray_tolerance)
        self.gray_brightness = float(gray_brightness)
        self.min_band_width_ratio = float(min_band_width_ratio)
        self.min_band_height = float(min_band_height)

        self._words_df: pd.DataFrame | None = None
        self._lines_df: pd.DataFrame | None = None
        self._bands_df: pd.DataFrame | None = None
        self._blocks_df: pd.DataFrame | None = None

        self._typed_words: list[Word] | None = None
        self._typed_lines: list[Line] | None = None
        self._typed_bands: list[Band] | None = None
        self._typed_blocks: list[Block] | None = None

    # ------------------------------------------------------------------
    # Validation and normalization
    # ------------------------------------------------------------------

    def _validate_source(self) -> None:
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {self.pdf_path}")
        if not self.pdf_path.is_file():
            raise PdfEngineError(f"PDF path is not a file: {self.pdf_path}")

    @staticmethod
    def _clean_text(value: Any) -> str:
        text = str(value or "").replace("\ufffe", "").strip()
        return " ".join(text.split())

    @staticmethod
    def _color_to_brightness(value: Any) -> float | None:
        """Convert grayscale/RGB/CMYK-like values to a 0..1 brightness."""
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, (tuple, list)):
            numeric = [float(v) for v in value if isinstance(v, (int, float))]
            if not numeric:
                return None

            # pdfplumber commonly exposes RGB tuples. Averaging is sufficient
            # for the near-neutral light gray rectangles used by OPERA.
            return sum(numeric) / len(numeric)

        return None

    def clear_cache(self) -> None:
        """Discard every cached extraction result."""
        self._words_df = None
        self._lines_df = None
        self._bands_df = None
        self._blocks_df = None
        self._typed_words = None
        self._typed_lines = None
        self._typed_bands = None
        self._typed_blocks = None

    # ------------------------------------------------------------------
    # Band detection
    # ------------------------------------------------------------------

    def _detect_gray_rectangles(
        self,
        page: pdfplumber.page.Page,
        page_number: int,
    ) -> list[dict[str, Any]]:
        rectangles: list[dict[str, Any]] = []

        for rect in page.rects:
            width = float(rect.get("width") or 0.0)
            height = float(rect.get("height") or 0.0)
            brightness = self._color_to_brightness(
                rect.get("non_stroking_color")
            )

            if brightness is None:
                continue

            is_wide = width >= float(page.width) * self.min_band_width_ratio
            is_tall_enough = height >= self.min_band_height
            is_expected_gray = (
                abs(brightness - self.gray_brightness) <= self.gray_tolerance
            )

            if not (is_wide and is_tall_enough and is_expected_gray):
                continue

            rectangles.append(
                {
                    "page_number": page_number,
                    "top": float(rect["top"]),
                    "bottom": float(rect["bottom"]),
                    "x0": float(rect["x0"]),
                    "x1": float(rect["x1"]),
                    "brightness": brightness,
                    "shade": "gray",
                }
            )

        rectangles.sort(key=lambda item: (item["top"], item["bottom"]))
        return self._merge_overlapping_rectangles(rectangles)

    @staticmethod
    def _merge_overlapping_rectangles(
        rectangles: list[dict[str, Any]],
        tolerance: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Merge duplicate or vertically overlapping gray rectangles."""
        if not rectangles:
            return []

        merged: list[dict[str, Any]] = [rectangles[0].copy()]

        for rectangle in rectangles[1:]:
            current = merged[-1]
            overlaps = rectangle["top"] <= current["bottom"] + tolerance

            if overlaps:
                current["top"] = min(current["top"], rectangle["top"])
                current["bottom"] = max(current["bottom"], rectangle["bottom"])
                current["x0"] = min(current["x0"], rectangle["x0"])
                current["x1"] = max(current["x1"], rectangle["x1"])
            else:
                merged.append(rectangle.copy())

        return merged

    @staticmethod
    def _build_page_bands(
        page_number: int,
        page_height: float,
        gray_rectangles: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Create alternating gray/white bands for a complete page."""
        if not gray_rectangles:
            return [
                {
                    "page_number": page_number,
                    "band_id": 1,
                    "top": 0.0,
                    "bottom": float(page_height),
                    "shade": "white",
                }
            ]

        bands: list[dict[str, Any]] = []
        cursor = 0.0
        next_id = 1

        for gray in gray_rectangles:
            gray_top = max(0.0, float(gray["top"]))
            gray_bottom = min(float(page_height), float(gray["bottom"]))

            if gray_top > cursor:
                bands.append(
                    {
                        "page_number": page_number,
                        "band_id": next_id,
                        "top": cursor,
                        "bottom": gray_top,
                        "shade": "white",
                    }
                )
                next_id += 1

            if gray_bottom > gray_top:
                bands.append(
                    {
                        "page_number": page_number,
                        "band_id": next_id,
                        "top": gray_top,
                        "bottom": gray_bottom,
                        "shade": "gray",
                    }
                )
                next_id += 1
                cursor = max(cursor, gray_bottom)

        if cursor < page_height:
            bands.append(
                {
                    "page_number": page_number,
                    "band_id": next_id,
                    "top": cursor,
                    "bottom": float(page_height),
                    "shade": "white",
                }
            )

        return bands

    @staticmethod
    def _find_band(
        center_y: float,
        page_bands: Iterable[dict[str, Any]],
    ) -> dict[str, Any] | None:
        for band in page_bands:
            if float(band["top"]) <= center_y < float(band["bottom"]):
                return band
        return None

    # ------------------------------------------------------------------
    # Public DataFrame API (backward compatible)
    # ------------------------------------------------------------------

    def extract_words(self, force: bool = False) -> pd.DataFrame:
        """Extract words and attach generic visual-band metadata."""
        if self._words_df is not None and not force:
            return self._words_df.copy(deep=True)

        self._validate_source()
        records: list[dict[str, Any]] = []
        band_records: list[dict[str, Any]] = []

        try:
            with pdfplumber.open(self.pdf_path) as pdf:
                for page_number, page in enumerate(pdf.pages, start=1):
                    gray_rectangles = self._detect_gray_rectangles(
                        page, page_number
                    )
                    page_bands = self._build_page_bands(
                        page_number,
                        float(page.height),
                        gray_rectangles,
                    )
                    band_records.extend(page_bands)

                    words = page.extract_words(
                        x_tolerance=1,
                        y_tolerance=2,
                        keep_blank_chars=False,
                        use_text_flow=False,
                    )

                    for word_index, raw in enumerate(words, start=1):
                        text = self._clean_text(raw.get("text"))
                        if not text:
                            continue

                        top = float(raw["top"])
                        bottom = float(raw["bottom"])
                        center_y = (top + bottom) / 2.0
                        band = self._find_band(center_y, page_bands)

                        records.append(
                            {
                                "page_number": page_number,
                                "word_index": word_index,
                                "text": text,
                                "x0": float(raw["x0"]),
                                "x1": float(raw["x1"]),
                                "top": top,
                                "bottom": bottom,
                                "doctop": float(raw.get("doctop", top)),
                                "width": float(
                                    raw.get("width", float(raw["x1"]) - float(raw["x0"]))
                                ),
                                "height": float(raw.get("height", bottom - top)),
                                "band_id": band["band_id"] if band else None,
                                "shade": band["shade"] if band else "unknown",
                                "band_top": band["top"] if band else None,
                                "band_bottom": band["bottom"] if band else None,
                            }
                        )
        except Exception as exc:
            raise PdfEngineError(
                f"Could not extract PDF words from {self.pdf_path}: {exc}"
            ) from exc

        self._words_df = pd.DataFrame(records, columns=self.WORD_COLUMNS)
        self._bands_df = pd.DataFrame(band_records, columns=self.BAND_COLUMNS)
        self._typed_words = None
        self._typed_bands = None
        self._lines_df = None
        self._blocks_df = None
        self._typed_lines = None
        self._typed_blocks = None

        return self._words_df.copy(deep=True)

    def group_lines(self, force: bool = False) -> pd.DataFrame:
        """Group words into logical lines without report-specific rules."""
        if self._lines_df is not None and not force:
            return self._lines_df.copy(deep=True)

        words_df = self.extract_words(force=force)
        if words_df.empty:
            self._lines_df = pd.DataFrame(columns=self.LINE_COLUMNS)
            return self._lines_df.copy(deep=True)

        line_records: list[dict[str, Any]] = []

        for page_number, page_words in words_df.groupby("page_number", sort=True):
            ordered = page_words.sort_values(["top", "x0"], kind="stable")
            groups: list[list[dict[str, Any]]] = []

            for record in ordered.to_dict("records"):
                if not groups:
                    groups.append([record])
                    continue

                current = groups[-1]
                mean_top = sum(float(item["top"]) for item in current) / len(current)
                same_band = record.get("band_id") == current[0].get("band_id")
                aligned = abs(float(record["top"]) - mean_top) <= self.line_tolerance

                if aligned and same_band:
                    current.append(record)
                else:
                    groups.append([record])

            for line_number, group in enumerate(groups, start=1):
                group.sort(key=lambda item: float(item["x0"]))
                first = group[0]
                line_records.append(
                    {
                        "page_number": int(page_number),
                        "line_number": line_number,
                        "text": self._clean_text(
                            " ".join(str(item["text"]) for item in group)
                        ),
                        "x0": min(float(item["x0"]) for item in group),
                        "x1": max(float(item["x1"]) for item in group),
                        "top": min(float(item["top"]) for item in group),
                        "bottom": max(float(item["bottom"]) for item in group),
                        "band_id": first.get("band_id"),
                        "shade": first.get("shade"),
                        "band_top": first.get("band_top"),
                        "band_bottom": first.get("band_bottom"),
                        "words": group,
                    }
                )

        self._lines_df = pd.DataFrame(line_records, columns=self.LINE_COLUMNS)
        self._typed_lines = None
        self._blocks_df = None
        self._typed_blocks = None
        return self._lines_df.copy(deep=True)

    def visual_bands(self, force: bool = False) -> pd.DataFrame:
        """Return every inferred gray/white visual band."""
        if self._bands_df is None or force:
            self.extract_words(force=force)
        assert self._bands_df is not None
        return self._bands_df.copy(deep=True)

    def group_visual_blocks(self, force: bool = False) -> pd.DataFrame:
        """Aggregate lines by page and visual band."""
        if self._blocks_df is not None and not force:
            return self._blocks_df.copy(deep=True)

        lines = self.group_lines(force=force)
        if lines.empty:
            self._blocks_df = pd.DataFrame(columns=self.BLOCK_COLUMNS)
            return self._blocks_df.copy(deep=True)

        blocks: list[dict[str, Any]] = []
        block_id = 1

        for (page_number, band_id, shade), group in lines.groupby(
            ["page_number", "band_id", "shade"],
            dropna=False,
            sort=True,
        ):
            group = group.sort_values(["top", "x0"], kind="stable")
            blocks.append(
                {
                    "page_number": int(page_number),
                    "block_id": block_id,
                    "band_id": band_id,
                    "shade": shade,
                    "band_top": group["band_top"].min(),
                    "band_bottom": group["band_bottom"].max(),
                    "line_count": int(len(group)),
                    "text": "\n".join(group["text"].astype(str)),
                    "lines": group.to_dict("records"),
                }
            )
            block_id += 1

        self._blocks_df = pd.DataFrame(blocks, columns=self.BLOCK_COLUMNS)
        self._typed_blocks = None
        return self._blocks_df.copy(deep=True)

    # ------------------------------------------------------------------
    # Typed API for the new engine
    # ------------------------------------------------------------------

    def words(self, force: bool = False) -> list[Word]:
        if self._typed_words is not None and not force:
            return list(self._typed_words)

        frame = self.extract_words(force=force)
        self._typed_words = [
            Word(
                text=str(row.text),
                x0=float(row.x0),
                x1=float(row.x1),
                top=float(row.top),
                bottom=float(row.bottom),
                page=int(row.page_number),
            )
            for row in frame.itertuples(index=False)
        ]
        return list(self._typed_words)

    def lines(self, force: bool = False) -> list[Line]:
        if self._typed_lines is not None and not force:
            return list(self._typed_lines)

        frame = self.group_lines(force=force)
        typed: list[Line] = []
        for row in frame.itertuples(index=False):
            typed_words = [
                Word(
                    text=str(item["text"]),
                    x0=float(item["x0"]),
                    x1=float(item["x1"]),
                    top=float(item["top"]),
                    bottom=float(item["bottom"]),
                    page=int(row.page_number),
                )
                for item in row.words
            ]
            typed.append(Line(words=typed_words, page=int(row.page_number)))

        self._typed_lines = typed
        return list(self._typed_lines)

    def bands(self, force: bool = False) -> list[Band]:
        if self._typed_bands is not None and not force:
            return list(self._typed_bands)

        frame = self.visual_bands(force=force)
        self._typed_bands = [
            Band(
                page=int(row.page_number),
                band_id=int(row.band_id),
                top=float(row.top),
                bottom=float(row.bottom),
                shade=str(row.shade),
            )
            for row in frame.itertuples(index=False)
        ]
        return list(self._typed_bands)

    def blocks(self, force: bool = False) -> list[Block]:
        if self._typed_blocks is not None and not force:
            return list(self._typed_blocks)

        block_frame = self.group_visual_blocks(force=force)
        band_lookup = {(b.page, b.band_id): b for b in self.bands(force=False)}
        typed_blocks: list[Block] = []

        for row in block_frame.itertuples(index=False):
            lines: list[Line] = []
            for raw_line in row.lines:
                line_words = [
                    Word(
                        text=str(word["text"]),
                        x0=float(word["x0"]),
                        x1=float(word["x1"]),
                        top=float(word["top"]),
                        bottom=float(word["bottom"]),
                        page=int(row.page_number),
                    )
                    for word in raw_line["words"]
                ]
                lines.append(Line(words=line_words, page=int(row.page_number)))

            typed_blocks.append(
                Block(
                    page=int(row.page_number),
                    block_id=int(row.block_id),
                    band=band_lookup.get((int(row.page_number), int(row.band_id))),
                    lines=lines,
                )
            )

        self._typed_blocks = typed_blocks
        return list(self._typed_blocks)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def page_metrics(self) -> pd.DataFrame:
        """Return lightweight page-level extraction metrics."""
        words = self.extract_words()
        lines = self.group_lines()
        bands = self.visual_bands()
        blocks = self.group_visual_blocks()

        page_numbers = sorted(
            set(words.get("page_number", pd.Series(dtype=int)).tolist())
            | set(bands.get("page_number", pd.Series(dtype=int)).tolist())
        )

        rows: list[dict[str, Any]] = []
        for page_number in page_numbers:
            rows.append(
                {
                    "page_number": page_number,
                    "word_count": int((words["page_number"] == page_number).sum()),
                    "line_count": int((lines["page_number"] == page_number).sum()),
                    "band_count": int((bands["page_number"] == page_number).sum()),
                    "block_count": int((blocks["page_number"] == page_number).sum()),
                }
            )

        return pd.DataFrame(rows)

    def export_line_words(self, writer: pd.ExcelWriter) -> None:
        """Preserve the current debug workbook helper."""
        lines = self.group_lines()
        if lines.empty:
            return

        rows: list[dict[str, Any]] = []
        for _, line in lines.iterrows():
            for word_order, word in enumerate(line["words"], start=1):
                rows.append(
                    {
                        "page_number": line["page_number"],
                        "line_number": line["line_number"],
                        "band_id": line.get("band_id"),
                        "shade": line.get("shade"),
                        "line_text": line["text"],
                        "word_order": word_order,
                        "word_text": word.get("text"),
                        "x0": word.get("x0"),
                        "x1": word.get("x1"),
                        "top": word.get("top"),
                        "bottom": word.get("bottom"),
                    }
                )

        pd.DataFrame(rows).to_excel(writer, sheet_name="line_words", index=False)

    def export_debug(
        self,
        output_path: str | Path,
        **kwargs: Any,
    ) -> Path:
        """Export engine and optional parser diagnostics to Excel."""
        return DebugExporter(self).export(output_path, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        """Return typed engine output as serializable dictionaries."""
        return {
            "pdf_path": str(self.pdf_path),
            "words": [asdict(item) for item in self.words()],
            "bands": [asdict(item) for item in self.bands()],
            "blocks": [asdict(item) for item in self.blocks()],
        }