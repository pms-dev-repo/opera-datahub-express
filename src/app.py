from __future__ import annotations

from datetime import datetime
import shutil
import traceback
from pathlib import Path

from . import settings
from .connectors.email_client import (
    download_csv_attachments,
    delete_messages,
)
from .db import (
    get_engine,
    replace_by_dates,
    log_load,
)
from .processors.core import process_file


def move_file(path: Path, base: Path) -> Path:
    if not path.exists():
        print(f"File already moved or missing: {path}")
        return path

    target_dir = base / datetime.now().strftime("%Y-%m-%d")
    target_dir.mkdir(parents=True, exist_ok=True)

    target = target_dir / path.name

    if target.exists():
        target = target_dir / (
            f"{path.stem}_{datetime.now().strftime('%H%M%S')}{path.suffix}"
        )

    shutil.move(str(path), str(target))
    return target


def get_pdf_files() -> list[Path]:
    files_by_path = {
        p.resolve(): p
        for pattern in ("*.pdf", "*.PDF")
        for p in settings.INCOMING_DIR.glob(pattern)
    }

    return sorted(files_by_path.values())


def run() -> None:
    touched_messages = download_csv_attachments(
        settings.EMAIL_HOST,
        settings.EMAIL_PORT,
        settings.EMAIL_USER,
        settings.EMAIL_PASSWORD,
        settings.EMAIL_FOLDER,
        settings.INCOMING_DIR,
    )

    engine = get_engine(settings.DATABASE_URL)
    ok = True

    files = get_pdf_files()

    print(f"PDF files to process: {len(files)}")

    for path in files:
        try:
            size = path.stat().st_size if path.exists() else 0
            print(f"Processing: {path.name} ({size:,} bytes)")

            table, df = process_file(path)

            replace_by_dates(engine, table, df)

            log_load(
                engine,
                table,
                path.name,
                len(df),
                "SUCCESS",
            )

            print(f"{table}: loaded {len(df)} rows")

            move_file(path, settings.ARCHIVE_DIR)

        except Exception as exc:
            ok = False

            print()
            print("=" * 80)
            print(f"ERROR processing {path.name}")

            if path.exists():
                print(f"File size: {path.stat().st_size:,} bytes")

            traceback.print_exc()
            print("=" * 80)

            try:
                log_load(
                    engine,
                    "unknown",
                    path.name,
                    0,
                    "ERROR",
                    str(exc),
                )
            except Exception:
                pass

            move_file(path, settings.ERROR_DIR)

    if ok and settings.EMAIL_DELETE_AFTER_SUCCESS and touched_messages:
        delete_messages(
            settings.EMAIL_HOST,
            settings.EMAIL_PORT,
            settings.EMAIL_USER,
            settings.EMAIL_PASSWORD,
            touched_messages,
        )

        print("Processed email messages deleted/expunged.")

    elif not ok:
        print("Some files failed. Email messages were NOT deleted.")

    else:
        print("No email messages to delete.")


if __name__ == "__main__":
    run()