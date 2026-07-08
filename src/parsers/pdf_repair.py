from pathlib import Path
from pypdf import PdfReader, PdfWriter


def repair_pdf(pdf_path: str | Path) -> Path:
    pdf_path = Path(pdf_path)

    repaired_dir = Path("data/processing/repaired")
    repaired_dir.mkdir(parents=True, exist_ok=True)

    repaired_path = repaired_dir / pdf_path.name

    reader = PdfReader(str(pdf_path), strict=False)
    writer = PdfWriter()

    for page in reader.pages:
        writer.add_page(page)

    with repaired_path.open("wb") as f:
        writer.write(f)

    return repaired_path