from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import fitz


class PdfEngine:
    """
    PDF extraction engine with visual row-band metadata.

    Existing public methods preserved:
      - extract_words()
      - group_lines()
      - export_line_words()

    New metadata returned by extract_words()/group_lines():
      - band_id
      - shade: "gray", "white", or "header"
      - band_top / band_bottom
      - page_number
    """

    def __init__(
        self,
        pdf_path: str | Path,
        line_tolerance: float = 2.5,
        gray_tolerance: float = 0.025,
        min_band_width_ratio: float = 0.85,
    ) -> None:
        self.pdf_path = Path(pdf_path)
        self.line_tolerance = float(line_tolerance)
        self.gray_tolerance = float(gray_tolerance)
        self.min_band_width_ratio = float(min_band_width_ratio)

        self._words_df: pd.DataFrame | None = None
        self._lines_df: pd.DataFrame | None = None
        self._bands_by_page: dict[int, list[dict[str, Any]]] = {}

    @staticmethod
    def _clean_text(value: Any) -> str:
        value = str(value or "").replace("\ufffe", "").strip()
        return " ".join(value.split())

    @staticmethod
    def _color_to_gray(value: Any) -> float | None:
        """
        Convert PDF grayscale/RGB values to a single 0..1 brightness.
        """
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, (tuple, list)) and value:
            numeric = [float(v) for v in value if isinstance(v, (int, float))]
            if not numeric:
                return None
            return sum(numeric) / len(numeric)

        return None

    def _detect_gray_rectangles(
        self,
        page: fitz.Page,
        page_number: int,
    ) -> list[dict[str, Any]]:
        rectangles: list[dict[str, Any]] = []

        for drawing in page.get_drawings():
            rect = drawing.get("rect")
            brightness = self._color_to_gray(drawing.get("fill"))

            if rect is None or brightness is None:
                continue

            width = float(rect.width)
            height = float(rect.height)

            if (
                width >= float(page.rect.width) * self.min_band_width_ratio
                and height >= 8
                and abs(brightness - 0.96) <= self.gray_tolerance
            ):
                rectangles.append(
                    {
                        "page_number": page_number,
                        "top": float(rect.y0),
                        "bottom": float(rect.y1),
                        "x0": float(rect.x0),
                        "x1": float(rect.x1),
                        "shade": "gray",
                        "brightness": brightness,
                    }
                )

        rectangles.sort(key=lambda item: item["top"])
        return rectangles

    @staticmethod
    def _build_visual_bands(
        page_number: int,
        page_height: float,
        gray_rectangles: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Build alternating gray/white visual regions.

        Gray rectangles are explicit PDF objects. White bands are inferred
        from the vertical gaps between gray rectangles.
        """
        if not gray_rectangles:
            return [
                {
                    "page_number": page_number,
                    "band_id": f"{page_number}:0",
                    "top": 0.0,
                    "bottom": float(page_height),
                    "shade": "header",
                }
            ]

        bands: list[dict[str, Any]] = []
        cursor = 0.0
        local_id = 0

        for gray in gray_rectangles:
            gray_top = float(gray["top"])
            gray_bottom = float(gray["bottom"])

            if gray_top > cursor:
                bands.append(
                    {
                        "page_number": page_number,
                        "band_id": f"{page_number}:{local_id}",
                        "top": cursor,
                        "bottom": gray_top,
                        "shade": "white",
                    }
                )
                local_id += 1

            bands.append(
                {
                    "page_number": page_number,
                    "band_id": f"{page_number}:{local_id}",
                    "top": gray_top,
                    "bottom": gray_bottom,
                    "shade": "gray",
                }
            )
            local_id += 1
            cursor = max(cursor, gray_bottom)

        if cursor < page_height:
            bands.append(
                {
                    "page_number": page_number,
                    "band_id": f"{page_number}:{local_id}",
                    "top": cursor,
                    "bottom": float(page_height),
                    "shade": "white",
                }
            )

        return bands

    @staticmethod
    def _band_for_vertical_center(
        center_y: float,
        bands: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        for band in bands:
            if float(band["top"]) <= center_y < float(band["bottom"]):
                return band
        return None

    def extract_words(self, force: bool = False) -> pd.DataFrame:
        if self._words_df is not None and not force:
            return self._words_df.copy()

        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {self.pdf_path}")

        records: list[dict[str, Any]] = []
        self._bands_by_page = {}
        document: fitz.Document | None = None

        try:
            document = fitz.open(self.pdf_path)
            doctop_offset = 0.0

            for page_number, page in enumerate(document, start=1):
                page_height = float(page.rect.height)
                gray_rectangles = self._detect_gray_rectangles(
                    page,
                    page_number,
                )
                bands = self._build_visual_bands(
                    page_number,
                    page_height,
                    gray_rectangles,
                )
                self._bands_by_page[page_number] = bands

                words = page.get_text("words", sort=True)

                for word_index, word in enumerate(words, start=1):
                    x0, top, x1, bottom, raw_text = word[:5]
                    text = self._clean_text(raw_text)
                    if not text:
                        continue

                    x0 = float(x0)
                    x1 = float(x1)
                    top = float(top)
                    bottom = float(bottom)
                    center_y = (top + bottom) / 2
                    band = self._band_for_vertical_center(center_y, bands)

                    records.append(
                        {
                            "page_number": page_number,
                            "word_index": word_index,
                            "text": text,
                            "x0": x0,
                            "x1": x1,
                            "top": top,
                            "bottom": bottom,
                            "doctop": doctop_offset + top,
                            "width": x1 - x0,
                            "height": bottom - top,
                            "band_id": band["band_id"] if band else None,
                            "shade": band["shade"] if band else "unknown",
                            "band_top": band["top"] if band else None,
                            "band_bottom": band["bottom"] if band else None,
                        }
                    )

                doctop_offset += page_height

        except Exception as exc:
            raise RuntimeError(
                f"Could not extract PDF words from {self.pdf_path}: {exc}"
            ) from exc
        finally:
            if document is not None:
                document.close()

        self._words_df = pd.DataFrame(records)
        return self._words_df.copy()

    def group_lines(self, force: bool = False) -> pd.DataFrame:
        if self._lines_df is not None and not force:
            return self._lines_df.copy()

        words_df = self.extract_words(force=force)

        if words_df.empty:
            self._lines_df = pd.DataFrame(
                columns=[
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
            )
            return self._lines_df.copy()

        line_records: list[dict[str, Any]] = []

        for page_number, page_words in words_df.groupby(
            "page_number",
            sort=True,
        ):
            ordered = page_words.sort_values(
                ["top", "x0"],
                kind="stable",
            )

            groups: list[list[dict[str, Any]]] = []

            for record in ordered.to_dict("records"):
                if not groups:
                    groups.append([record])
                    continue

                current = groups[-1]
                mean_top = sum(
                    float(item["top"])
                    for item in current
                ) / len(current)

                same_visual_band = (
                    record.get("band_id")
                    == current[0].get("band_id")
                )

                if (
                    abs(float(record["top"]) - mean_top)
                    <= self.line_tolerance
                    and same_visual_band
                ):
                    current.append(record)
                else:
                    groups.append([record])

            for line_number, group in enumerate(
                groups,
                start=1,
            ):
                group = sorted(
                    group,
                    key=lambda item: float(item["x0"]),
                )

                text = self._clean_text(
                    " ".join(
                        str(item["text"])
                        for item in group
                    )
                )

                first = group[0]

                line_records.append(
                    {
                        "page_number": int(page_number),
                        "line_number": line_number,
                        "text": text,
                        "x0": min(
                            float(item["x0"])
                            for item in group
                        ),
                        "x1": max(
                            float(item["x1"])
                            for item in group
                        ),
                        "top": min(
                            float(item["top"])
                            for item in group
                        ),
                        "bottom": max(
                            float(item["bottom"])
                            for item in group
                        ),
                        "band_id": first.get("band_id"),
                        "shade": first.get("shade"),
                        "band_top": first.get("band_top"),
                        "band_bottom": first.get("band_bottom"),
                        "words": group,
                    }
                )

        self._lines_df = pd.DataFrame(line_records)
        return self._lines_df.copy()

    def visual_bands(self) -> pd.DataFrame:
        if not self._bands_by_page:
            self.extract_words()

        rows = [
            band
            for page_bands in self._bands_by_page.values()
            for band in page_bands
        ]
        return pd.DataFrame(rows)

    def group_visual_blocks(self) -> pd.DataFrame:
        """
        Aggregate grouped text lines by visual band.

        Useful for debugging how OPERA's alternating row colors divide
        reservations and observations.
        """
        lines = self.group_lines()

        if lines.empty:
            return pd.DataFrame()

        blocks: list[dict[str, Any]] = []

        for (
            page_number,
            band_id,
            shade,
        ), group in lines.groupby(
            ["page_number", "band_id", "shade"],
            dropna=False,
            sort=True,
        ):
            group = group.sort_values(
                ["top", "x0"],
                kind="stable",
            )

            blocks.append(
                {
                    "page_number": page_number,
                    "band_id": band_id,
                    "shade": shade,
                    "band_top": group["band_top"].min(),
                    "band_bottom": group["band_bottom"].max(),
                    "line_count": len(group),
                    "text": "\n".join(
                        group["text"].astype(str)
                    ),
                    "lines": group.to_dict("records"),
                }
            )

        return pd.DataFrame(blocks)

    def export_line_words(
        self,
        writer: pd.ExcelWriter,
    ) -> None:
        lines = self.group_lines()

        if lines.empty:
            return

        export_rows: list[dict[str, Any]] = []

        for _, line in lines.iterrows():
            for word_order, word in enumerate(
                line["words"],
                start=1,
            ):
                export_rows.append(
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

        pd.DataFrame(export_rows).to_excel(
            writer,
            sheet_name="line_words",
            index=False,
        )
