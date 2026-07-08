import email
import imaplib
from pathlib import Path


ALLOWED_EXTENSIONS = (".pdf",)


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
    mail.select(f'"{folder}"')

    status, data = mail.uid("search", None, "UNSEEN")

    if status != "OK":
        mail.logout()
        return touched

    for uid in data[0].split():
        status, msg_data = mail.uid("fetch", uid, "(RFC822)")

        if status != "OK":
            continue

        msg = email.message_from_bytes(msg_data[0][1])
        saved_any = False

        for part in msg.walk():
            filename = part.get_filename()

            if not filename:
                continue

            if not filename.lower().endswith(ALLOWED_EXTENSIONS):
                continue

            payload = part.get_payload(decode=True)

            if not payload:
                continue

            safe_name = Path(filename).name
            out_path = incoming_dir / safe_name
            out_path.write_bytes(payload)

            print(f"Downloaded: {out_path}")
            saved_any = True

        if saved_any:
            touched.append((folder, uid))

    mail.logout()
    return touched


def _get_trash_folder(mail: imaplib.IMAP4_SSL) -> str:
    status, folders = mail.list()

    if status == "OK":
        for raw in folders:
            line = raw.decode(errors="ignore")

            if "\\Trash" in line:
                return line.split(' "/" ')[-1].strip('"')

    return "[Gmail]/Trash"


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

    trash_folder = _get_trash_folder(mail)
    print(f"Trash folder detected: {trash_folder}")

    by_folder: dict[str, list[bytes]] = {}

    for folder, uid in touched:
        by_folder.setdefault(folder, []).append(uid)

    for folder, uids in by_folder.items():
        mail.select(f'"{folder}"')

        for uid in uids:
            # First try IMAP MOVE using UID.
            status, _ = mail.uid("MOVE", uid, f'"{trash_folder}"')

            if status == "OK":
                print(f"Moved UID {uid.decode()} to Trash")
                continue

            # Fallback: copy to trash, mark deleted, expunge.
            copy_status, _ = mail.uid("COPY", uid, f'"{trash_folder}"')

            if copy_status == "OK":
                mail.uid("STORE", uid, "+FLAGS", "\\Deleted")
                print(f"Copied UID {uid.decode()} to Trash and deleted original")
            else:
                # Last Gmail fallback: remove label and add Trash label.
                mail.uid("STORE", uid, "+X-GM-LABELS", r'"\Trash"')
                mail.uid("STORE", uid, "+FLAGS", "\\Deleted")
                print(f"Deleted UID {uid.decode()} using Gmail fallback")

        mail.expunge()

    mail.logout()