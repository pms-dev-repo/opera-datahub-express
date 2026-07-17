from __future__ import annotations

"""Excel diagnostics for the generic Opera PDF Engine.

The exporter is intentionally report-agnostic. It can export the generic
layers produced by ``PdfEngine`` and, optionally, parser-specific information
such as reservation blocks, parser steps, warnings, and parsed rows.
"""

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd


class DebugExporter:
    """Create a readable diagnostic workbook for a :class:`PdfEngine`.

    Parameters
    ----------
    engine:
        A ``PdfEngine`` instance. The exporter only relies on its public API:
        ``extract_words()``, ``group_lines()``, ``visual_bands()``,
        ``group_visual_blocks()``, ``page_metrics()``, and
        ``export_line_words()``.
    """

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export(
        self,
        output_path: str | Path,
        *,
        reservation_blocks: Iterable[Any] | None = None,
        parser_steps: Iterable[Mapping[str, Any] | Any] | None = None,
        parsed_rows: pd.DataFrame | Iterable[Mapping[str, Any] | Any] | None = None,
        warnings: Iterable[Mapping[str, Any] | Any] | None = None,
    ) -> Path:
        """Write all available diagnostic layers to an XLSX workbook."""
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

        with pd.ExcelWriter(destination, engine="openpyxl") as writer:
            self._write_generic_layers(writer)

            if reservation_blocks is not None:
                reservation_frame = self._reservation_blocks_frame(
                    reservation_blocks
                )
                self._write_frame(
                    writer,
                    reservation_frame,
                    "reservation_blocks",
                )

            if parser_steps is not None:
                self._write_frame(
                    writer,
                    self._records_frame(parser_steps),
                    "parser_steps",
                )

            if parsed_rows is not None:
                parsed_frame = (
                    parsed_rows.copy()
                    if isinstance(parsed_rows, pd.DataFrame)
                    else self._records_frame(parsed_rows)
                )
                self._write_frame(writer, parsed_frame, "parsed_rows")

            if warnings is not None:
                self._write_frame(
                    writer,
                    self._records_frame(warnings),
                    "warnings",
                )

            self._format_workbook(writer)

        return destination

    # ------------------------------------------------------------------
    # Generic engine sheets
    # ------------------------------------------------------------------

    def _write_generic_layers(self, writer: pd.ExcelWriter) -> None:
        words = self.engine.extract_words()
        lines = self.engine.group_lines()
        bands = self.engine.visual_bands()
        blocks = self.engine.group_visual_blocks()
        metrics = self.engine.page_metrics()

        self._write_frame(
            writer,
            words.drop(columns=["words"], errors="ignore"),
            "raw_words",
        )
        self._write_frame(
            writer,
            lines.drop(columns=["words"], errors="ignore"),
            "lines",
        )
        self._write_frame(writer, bands, "visual_bands")

        # Existing compact view.
        self._write_frame(
            writer,
            blocks.drop(columns=["lines"], errors="ignore"),
            "visual_blocks",
        )

        # Human-friendly block summary requested for visual validation.
        self._write_frame(
            writer,
            self._blocks_frame(blocks),
            "blocks",
        )

        # One row per line inside each block. This makes it easy to identify
        # where MAIN, DETAIL, SHARE, ACCOMPANYING, or OBSERVATION sections sit.
        self._write_frame(
            writer,
            self._block_lines_frame(blocks),
            "block_lines",
        )

        self._write_frame(writer, metrics, "page_metrics")
        self.engine.export_line_words(writer)

    @staticmethod
    def _blocks_frame(blocks: pd.DataFrame) -> pd.DataFrame:
        columns = [
            "page_number",
            "block_id",
            "band_id",
            "shade",
            "band_top",
            "band_bottom",
            "line_count",
            "first_line",
            "last_line",
            "text",
        ]

        if blocks.empty:
            return pd.DataFrame(columns=columns)

        rows: list[dict[str, Any]] = []

        for row in blocks.to_dict("records"):
            raw_lines = row.get("lines") or []
            line_texts = [
                str(line.get("text") or "").strip()
                for line in raw_lines
                if str(line.get("text") or "").strip()
            ]

            rows.append(
                {
                    "page_number": row.get("page_number"),
                    "block_id": row.get("block_id"),
                    "band_id": row.get("band_id"),
                    "shade": row.get("shade"),
                    "band_top": row.get("band_top"),
                    "band_bottom": row.get("band_bottom"),
                    "line_count": row.get("line_count", len(line_texts)),
                    "first_line": line_texts[0] if line_texts else "",
                    "last_line": line_texts[-1] if line_texts else "",
                    "text": "\n".join(line_texts),
                }
            )

        return pd.DataFrame(rows, columns=columns)

    @staticmethod
    def _block_lines_frame(blocks: pd.DataFrame) -> pd.DataFrame:
        columns = [
            "page_number",
            "block_id",
            "band_id",
            "shade",
            "line_order",
            "line_number",
            "top",
            "bottom",
            "x0",
            "x1",
            "text",
        ]

        if blocks.empty:
            return pd.DataFrame(columns=columns)

        rows: list[dict[str, Any]] = []

        for block in blocks.to_dict("records"):
            for line_order, line in enumerate(block.get("lines") or [], start=1):
                rows.append(
                    {
                        "page_number": block.get("page_number"),
                        "block_id": block.get("block_id"),
                        "band_id": block.get("band_id"),
                        "shade": block.get("shade"),
                        "line_order": line_order,
                        "line_number": line.get("line_number"),
                        "top": line.get("top"),
                        "bottom": line.get("bottom"),
                        "x0": line.get("x0"),
                        "x1": line.get("x1"),
                        "text": line.get("text"),
                    }
                )

        return pd.DataFrame(rows, columns=columns)

    # ------------------------------------------------------------------
    # Optional parser-specific sheets
    # ------------------------------------------------------------------

    @classmethod
    def _reservation_blocks_frame(
        cls,
        reservation_blocks: Iterable[Any],
    ) -> pd.DataFrame:
        columns = [
            "page",
            "block_id",
            "arrival_group",
            "main_line",
            "detail_line",
            "share",
            "accompanying",
            "observations",
            "raw_text",
        ]

        rows: list[dict[str, Any]] = []

        for block in reservation_blocks:
            record = cls._object_to_record(block)

            rows.append(
                {
                    "page": record.get("page"),
                    "block_id": record.get("block_id"),
                    "arrival_group": record.get("arrival_group"),
                    "main_line": cls._line_text(record.get("main_line")),
                    "detail_line": cls._line_text(record.get("detail_line")),
                    "share": cls._join_line_texts(record.get("share_lines")),
                    "accompanying": cls._join_line_texts(
                        record.get("accompanying_lines")
                    ),
                    "observations": cls._join_line_texts(
                        record.get("observation_lines")
                    ),
                    "raw_text": cls._join_line_texts(record.get("raw_lines")),
                }
            )

        return pd.DataFrame(rows, columns=columns)

    @classmethod
    def _records_frame(cls, values: Iterable[Any]) -> pd.DataFrame:
        return pd.DataFrame([cls._object_to_record(value) for value in values])

    @staticmethod
    def _object_to_record(value: Any) -> dict[str, Any]:
        if value is None:
            return {}

        if isinstance(value, Mapping):
            return dict(value)

        if is_dataclass(value):
            return asdict(value)

        if hasattr(value, "__dict__"):
            return dict(vars(value))

        return {"value": value}

    @classmethod
    def _line_text(cls, value: Any) -> str:
        if value is None:
            return ""

        if isinstance(value, str):
            return value

        if isinstance(value, Mapping):
            return str(value.get("text") or "")

        text = getattr(value, "text", None)
        return str(text or "")

    @classmethod
    def _join_line_texts(cls, values: Any) -> str:
        if values is None:
            return ""

        if isinstance(values, (str, bytes)):
            return str(values)

        if not isinstance(values, Sequence):
            values = [values]

        parts = [cls._line_text(value).strip() for value in values]
        return "\n".join(part for part in parts if part)

    # ------------------------------------------------------------------
    # Excel formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _write_frame(
        writer: pd.ExcelWriter,
        frame: pd.DataFrame,
        sheet_name: str,
    ) -> None:
        safe_name = sheet_name[:31]
        frame.to_excel(writer, sheet_name=safe_name, index=False)

    @staticmethod
    def _format_workbook(writer: pd.ExcelWriter) -> None:
        workbook = writer.book

        for worksheet in workbook.worksheets:
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions

            for column_cells in worksheet.columns:
                values = [
                    str(cell.value) if cell.value is not None else ""
                    for cell in column_cells[:200]
                ]
                max_length = max((len(value) for value in values), default=0)
                width = min(max(max_length + 2, 10), 60)
                worksheet.column_dimensions[
                    column_cells[0].column_letter
                ].width = width

            for row in worksheet.iter_rows():
                for cell in row:
                    cell.alignment = cell.alignment.copy(
                        vertical="top",
                        wrap_text=True,
                    )
