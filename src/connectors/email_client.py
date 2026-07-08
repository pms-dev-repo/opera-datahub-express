import email
import imaplib
from pathlib import Path


ALLOWED_EXTENSIONS = (".pdf",)


def _print_folders(mail: imaplib.IMAP4_SSL) -> None:
    status, folders = mail.list()

    print("=" * 80)
    print("IMAP FOLDERS")
    print("=" * 80)

    if status != "OK" or not folders:
        print(f"Could not list folders: {status} {folders}")
        print("=" * 80)
        return

    for raw in folders:
        print(raw.decode(errors="ignore"))

    print("=" * 80)


def download_csv_attachments(
    host: str,
    port: int,
    user: str,
    password: str,
    folder: str,
    incoming_dir: Path,
) -> list[tuple[str, bytes]]:
    """Download unread PDF attachments only. Returns [(folder, uid)]."""

    touched: list[tuple[str, bytes]] = []

    if not user or not password:
        print("Email credentials not configured. Skipping email download.")
        return touched

    incoming_dir.mkdir(parents=True, exist_ok=True)

    mail = imaplib.IMAP4_SSL(host, port)
    mail.login(user, password)

    _print_folders(mail)

    select_status, select_data = mail.select(f'"{folder}"')
    print(f"SELECT {folder}: {select_status} {select_data}")

    status, flags = mail.response("PERMANENTFLAGS")
    print(f"PERMANENTFLAGS {folder}: {status} {flags}")

    if select_status != "OK":
        mail.logout()
        return touched

    status, data = mail.uid("search", None, "UNSEEN")

    if status != "OK":
        print(f"Email search failed: {status} {data}")
        mail.logout()
        return touched

    print(f"UNSEEN UIDs found: {data}")

    for uid in data[0].split():
        status, msg_data = mail.uid("fetch", uid, "(RFC822)")

        if status != "OK":
            print(f"Email fetch failed for UID {uid.decode()}: {status}")
            continue

        msg = email.message_from_bytes(msg_data[0][1])
        saved_any = False

        subject = msg.get("Subject", "")
        print(f"Reading UID {uid.decode()} | Subject: {subject}")

        for part in msg.walk():
            filename = part.get_filename()

            if not filename:
                continue

            if not filename.lower().endswith(ALLOWED_EXTENSIONS):
                continue

            payload = part.get_payload(decode=True)

            if not payload:
                print(f"Attachment empty: {filename}")
                continue

            safe_name = Path(filename).name
            out_path = incoming_dir / safe_name
            out_path.write_bytes(payload)

            print(f"Downloaded: {out_path} ({len(payload):,} bytes)")
            saved_any = True

        if saved_any:
            touched.append((folder, uid))

    mail.logout()
    return touched


def delete_messages(
    host: str,
    port: int,
    user: str,
    password: str,
    touched: list[tuple[str, bytes]],
) -> None:
    if not touched:
        return

    mail = imaplib.IMAP4_SSL(host, port)
    mail.login(user, password)

    _print_folders(mail)

    by_folder: dict[str, list[bytes]] = {}

    for folder, uid in touched:
        by_folder.setdefault(folder, []).append(uid)

    for folder, uids in by_folder.items():
        select_status, select_data = mail.select(f'"{folder}"')
        print(f"SELECT {folder} for cleanup: {select_status} {select_data}")

        status, flags = mail.response("PERMANENTFLAGS")
        print(f"PERMANENTFLAGS cleanup {folder}: {status} {flags}")

        if select_status != "OK":
            continue

        for uid in uids:
            fetch_status, fetch_data = mail.uid(
                "FETCH",
                uid,
                "(X-GM-LABELS FLAGS)"
            )
            print(
                f"Before cleanup UID {uid.decode()}: "
                f"{fetch_status} {fetch_data}"
            )

            status, response = mail.uid(
                "STORE",
                uid,
                "-X-GM-LABELS",
                f'"{folder}"',
            )

            print(
                f"Remove label {folder} from UID {uid.decode()}: "
                f"{status} {response}"
            )

            fetch_status, fetch_data = mail.uid(
                "FETCH",
                uid,
                "(X-GM-LABELS FLAGS)"
            )
            print(
                f"After remove label UID {uid.decode()}: "
                f"{fetch_status} {fetch_data}"
            )

            if status != "OK":
                status, response = mail.uid(
                    "STORE",
                    uid,
                    "+FLAGS",
                    "\\Deleted",
                )

                print(
                    f"Fallback delete UID {uid.decode()}: "
                    f"{status} {response}"
                )

        status, response = mail.expunge()
        print(f"EXPUNGE {folder}: {status} {response}")

    mail.logout()