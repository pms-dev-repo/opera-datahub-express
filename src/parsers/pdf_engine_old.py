from __future__ import annotations

from pathlib import Path
import pandas as pd
import pdfplumber

from .pdf_repair import repair_pdf


class PdfEngine:
    def __init__(self, pdf_file: str | Path):
        self.original_pdf_file = Path(pdf_file)
        self.pdf_file = self.original_pdf_file

    def _open_pdf(self):
        try:
            return pdfplumber.open(self.pdf_file)
        except Exception as exc:
            print(f"PDF read failed for {self.original_pdf_file.name}: {exc}")
            print(f"Repairing PDF: {self.original_pdf_file.name}")

            self.pdf_file = repair_pdf(self.original_pdf_file)
            return pdfplumber.open(self.pdf_file)

    def extract_words(self) -> pd.DataFrame:
        rows = []

        with self._open_pdf() as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                words = page.extract_words(
                    keep_blank_chars=False,
                    use_text_flow=False,
                    extra_attrs=[],
                )

                for w in words:
                    rows.append({
                        "page": page_number,
                        "text": w.get("text"),
                        "x0": w.get("x0"),
                        "x1": w.get("x1"),
                        "top": w.get("top"),
                        "bottom": w.get("bottom"),
                    })

        return pd.DataFrame(rows)

    def group_lines(self, y_tolerance: float = 3) -> pd.DataFrame:
        words = self.extract_words()

        if words.empty:
            return pd.DataFrame(columns=["page", "top", "text", "words"])

        words = words.sort_values(["page", "top", "x0"]).reset_index(drop=True)

        lines = []

        for page, page_words in words.groupby("page"):
            current_words = []
            current_top = None

            for _, word in page_words.iterrows():
                word_top = float(word["top"])

                if current_top is None:
                    current_top = word_top
                    current_words = [word.to_dict()]
                    continue

                if abs(word_top - current_top) <= y_tolerance:
                    current_words.append(word.to_dict())
                else:
                    current_words = sorted(current_words, key=lambda x: x["x0"])
                    lines.append({
                        "page": page,
                        "top": current_top,
                        "text": " ".join(w["text"] for w in current_words),
                        "words": current_words,
                    })

                    current_top = word_top
                    current_words = [word.to_dict()]

            if current_words:
                current_words = sorted(current_words, key=lambda x: x["x0"])
                lines.append({
                    "page": page,
                    "top": current_top,
                    "text": " ".join(w["text"] for w in current_words),
                    "words": current_words,
                })

        return pd.DataFrame(lines)

    def export_line_words(self, writer) -> None:
        lines = self.group_lines()

        rows = []

        for _, line in lines.iterrows():
            for word in line["words"]:
                rows.append({
                    "page": line["page"],
                    "line_top": line["top"],
                    "line_text": line["text"],
                    "word_text": word["text"],
                    "x0": word["x0"],
                    "x1": word["x1"],
                    "top": word["top"],
                    "bottom": word["bottom"],
                })

        pd.DataFrame(rows).to_excel(writer, sheet_name="line_words", index=False)