from __future__ import annotations

from pathlib import Path
import pandas as pd
import pdfplumber


class PdfEngine:

    def __init__(self, pdf_file: str | Path):
        self.pdf_file = Path(pdf_file)

        if not self.pdf_file.exists():
            raise FileNotFoundError(
                f"No encontré el PDF: {self.pdf_file.resolve()}"
            )

    def extract_words(self) -> pd.DataFrame:
        rows = []

        with pdfplumber.open(self.pdf_file) as pdf:
            for page_no, page in enumerate(pdf.pages, start=1):

                words = page.extract_words(
                    keep_blank_chars=True,
                    use_text_flow=False,
                )

                for w in words:
                    rows.append({
                        "page": page_no,
                        "text": w.get("text", ""),
                        "x0": round(float(w.get("x0", 0)), 2),
                        "x1": round(float(w.get("x1", 0)), 2),
                        "top": round(float(w.get("top", 0)), 2),
                        "bottom": round(float(w.get("bottom", 0)), 2),
                    })

        return pd.DataFrame(rows)

    def group_lines(self, tolerance: float = 3.0) -> pd.DataFrame:
        words = self.extract_words()

        if words.empty:
            return pd.DataFrame()

        lines = []

        for page, df_page in words.groupby("page"):
            df_page = df_page.sort_values(["top", "x0"]).reset_index(drop=True)

            current = []
            current_top = None
            line_no = 0

            for _, word in df_page.iterrows():
                top = float(word["top"])

                if current_top is None:
                    current_top = top
                    current = [word]
                    continue

                if abs(top - current_top) <= tolerance:
                    current.append(word)
                else:
                    line_no += 1
                    lines.append(self._build_line(page, line_no, current))
                    current_top = top
                    current = [word]

            if current:
                line_no += 1
                lines.append(self._build_line(page, line_no, current))

        return pd.DataFrame(lines)

    def export_line_words(self, writer):
        lines = self.group_lines()
        rows = []

        for _, line in lines.iterrows():
            for w in line["words"]:
                rows.append({
                    "page": line["page"],
                    "line_no": line["line_no"],
                    "top": round(float(w["top"]), 2),
                    "x0": round(float(w["x0"]), 2),
                    "x1": round(float(w["x1"]), 2),
                    "text": w["text"],
                })

        pd.DataFrame(rows).to_excel(
            writer,
            sheet_name="line_words",
            index=False
        )

    @staticmethod
    def _build_line(page: int, line_no: int, words: list) -> dict:
        words_sorted = sorted(words, key=lambda x: x["x0"])

        return {
            "page": page,
            "line_no": line_no,
            "top": min(float(w["top"]) for w in words_sorted),
            "bottom": max(float(w["bottom"]) for w in words_sorted),
            "x0": min(float(w["x0"]) for w in words_sorted),
            "x1": max(float(w["x1"]) for w in words_sorted),
            "text": " ".join(str(w["text"]) for w in words_sorted).strip(),
            "words": words_sorted,
        }

    @staticmethod
    def text_in_range(words: list, x_min: float, x_max: float) -> str:
        selected = [
            str(w["text"])
            for w in words
            if x_min <= float(w["x0"]) < x_max
        ]

        return " ".join(selected).strip()

    def export_debug(self, output_file: str | Path) -> Path:
        output_file = Path(output_file)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        words = self.extract_words()
        lines = self.group_lines()

        with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
            words.to_excel(writer, sheet_name="raw_words", index=False)

            lines.drop(
                columns=["words"],
                errors="ignore"
            ).to_excel(
                writer,
                sheet_name="lines",
                index=False
            )

            self.export_line_words(writer)

        return output_file