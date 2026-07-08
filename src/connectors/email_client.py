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
        print(f"Email search failed: {status} {data}")
        mail.logout()
        return touched

    for uid in data[0].split():
        status, msg_data = mail.uid("fetch", uid, "(RFC822)")

        if status != "OK":
            print(f"Email fetch failed for UID {uid.decode()}: {status}")
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


def delete_messages(
    host: str,
    port: int,
    user: str,
    password: str,
    touched: list[tuple[str, bytes]],
) -> None:
    """
    For Gmail labels, the most reliable behavior is removing the processed label.
    This makes the emails disappear from label:SLANE without depending on Trash/MOVE.
    """

    if not touched:
        return

    mail = imaplib.IMAP4_SSL(host, port)
    mail.login(user, password)

    by_folder: dict[str, list[bytes]] = {}

    for folder, uid in touched:
        by_folder.setdefault(folder, []).append(uid)

    for folder, uids in by_folder.items():
        mail.select(f'"{folder}"')

        for uid in uids:
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