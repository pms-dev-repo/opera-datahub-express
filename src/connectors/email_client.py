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
    """Download unread PDF attachments only. Returns [(folder, message_id)]."""

    touched: list[tuple[str, bytes]] = []

    if not user or not password:
        print("Email credentials not configured. Skipping email download.")
        return touched

    incoming_dir.mkdir(parents=True, exist_ok=True)

    mail = imaplib.IMAP4_SSL(host, port)
    mail.login(user, password)
    mail.select(f'"{folder}"')

    status, data = mail.search(None, "UNSEEN")

    if status != "OK":
        mail.logout()
        return touched

    for msg_id in data[0].split():
        status, msg_data = mail.fetch(msg_id, "(RFC822)")

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
            touched.append((folder, msg_id))

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

    for folder, msg_id in touched:
        by_folder.setdefault(folder, []).append(msg_id)

    for folder, ids in by_folder.items():
        mail.select(f'"{folder}"')

        for msg_id in ids:
            # Copy message to Trash
            copy_status, _ = mail.copy(msg_id, f'"{trash_folder}"')

            if copy_status == "OK":
                # Remove from current label/mailbox
                mail.store(msg_id, "+FLAGS", "\\Deleted")
                print(f"Deleted message {msg_id.decode()} from {folder}")
            else:
                # Gmail fallback
                mail.store(msg_id, "+X-GM-LABELS", r'"\Trash"')
                mail.store(msg_id, "+FLAGS", "\\Deleted")
                print(f"Deleted message {msg_id.decode()} using Gmail fallback")

        mail.expunge()

    mail.logout()