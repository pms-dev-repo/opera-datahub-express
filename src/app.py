from __future__ import annotations

from datetime import datetime
import shutil
import traceback
from pathlib import Path

from . import settings
from .connectors.email_client import (
    EmailDownload,
    download_csv_attachments,
    delete_messages,
)
from .db import (
    get_engine,
    replace_by_dates,
    log_load,
    enrich_child_buckets_from_snapshot,
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


def process_download(
    engine,
    download: EmailDownload,
) -> tuple[bool, int]:
    success = True
    loaded_rows = 0

    for path in download.attachments:
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

            loaded_rows += len(df)
            move_file(path, settings.ARCHIVE_DIR)

        except Exception as exc:
            success = False

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

    return success, loaded_rows


def run() -> None:
    downloads = download_csv_attachments(
        settings.EMAIL_HOST,
        settings.EMAIL_PORT,
        settings.EMAIL_USER,
        settings.EMAIL_PASSWORD,
        settings.EMAIL_FOLDER,
        settings.INCOMING_DIR,
    )

    engine = get_engine(settings.DATABASE_URL)

    total_messages = len(downloads)
    successful_messages: list[EmailDownload] = []
    failed_messages = 0
    total_rows = 0
    any_file_failed = False

    print(f"Email messages to process: {total_messages}")

    for download in downloads:
        uid_text = download.uid.decode(errors="ignore")

        print()
        print("-" * 80)
        print(
            f"Processing email UID {uid_text} "
            f"with {len(download.attachments)} attachment(s)"
        )
        print("-" * 80)

        success, loaded_rows = process_download(
            engine,
            download,
        )

        total_rows += loaded_rows

        if success:
            successful_messages.append(download)
        else:
            failed_messages += 1
            any_file_failed = True

    if not any_file_failed:
        enrich_child_buckets_from_snapshot(engine)

    if (
        settings.EMAIL_DELETE_AFTER_SUCCESS
        and successful_messages
    ):
        delete_messages(
            settings.EMAIL_HOST,
            settings.EMAIL_PORT,
            settings.EMAIL_USER,
            settings.EMAIL_PASSWORD,
            successful_messages,
        )

        print(
            f"Successfully cleaned up "
            f"{len(successful_messages)} email message(s)."
        )

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Messages reviewed : {total_messages}")
    print(f"Successful        : {len(successful_messages)}")
    print(f"Failed            : {failed_messages}")
    print(f"Rows loaded       : {total_rows}")

    if not downloads:
        print("No email messages were downloaded.")
    elif failed_messages:
        print(
            "Failed messages were kept in Gmail for review/retry."
        )
    else:
        print("All downloaded messages were processed successfully.")

    print("=" * 80)


if __name__ == "__main__":
    run()