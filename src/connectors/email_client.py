import email
import imaplib
from pathlib import Path


ALLOWED_EXTENSIONS = (".pdf",)


def gmail_raw_query(label: str) -> str:
    return f"label:{label} is:unread has:attachment"


def get_all_mail_folder(mail: imaplib.IMAP4_SSL) -> str:
    status, folders = mail.list()

    if status != "OK" or not folders:
        return '"INBOX"'

    for raw in folders:
        line = raw.decode(errors="ignore")

        if "\\All" in line:
            return line.split(' "/" ')[-1]

    return '"INBOX"'


def download_csv_attachments(
    host: str,
    port: int,
    user: str,
    password: str,
    folder: str,
    incoming_dir: Path,
) -> list[tuple[str, bytes]]:
    """Download unread PDF attachments using Gmail X-GM-RAW. Returns [(folder, uid)]."""

    touched: list[tuple[str, bytes]] = []

    if not user or not password:
        print("Email credentials not configured. Skipping email download.")
        return touched

    incoming_dir.mkdir(parents=True, exist_ok=True)

    mail = imaplib.IMAP4_SSL(host, port)
    mail.login(user, password)

    all_mail = get_all_mail_folder(mail)
    print(f"Using mailbox: {all_mail}")

    select_status, select_data = mail.select(all_mail)
    print(f"SELECT All Mail: {select_status} {select_data}")

    if select_status != "OK":
        mail.logout()
        return touched

    query = gmail_raw_query(folder)

    status, data = mail.search(
        None,
        "X-GM-RAW",
        f'"{query}"',
    )

    print(f"GMAIL SEARCH QUERY: {query}")
    print(f"GMAIL SEARCH RESULT: {status} {data}")

    if status != "OK":
        mail.logout()
        return touched

    for msg_id in data[0].split():
        status, uid_data = mail.fetch(msg_id, "(UID)")

        if status != "OK" or not uid_data:
            print(f"Could not get UID for message {msg_id.decode()}")
            continue

        uid_text = uid_data[0].decode(errors="ignore")
        uid = uid_text.split("UID ")[-1].replace(")", "").strip().encode()

        status, msg_data = mail.uid("FETCH", uid, "(RFC822)")

        if status != "OK":
            print(f"Email fetch failed for UID {uid.decode()}: {status}")
            continue

        msg = email.message_from_bytes(msg_data[0][1])
        saved_any = False

        subject = msg.get("Subject", "")
        message_id = msg.get("Message-ID", "")

        print(f"Reading UID {uid.decode()} | Subject: {subject}")
        print(f"Message-ID: {message_id}")

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

    all_mail = get_all_mail_folder(mail)
    print(f"Using mailbox for cleanup: {all_mail}")

    select_status, select_data = mail.select(all_mail)
    print(f"SELECT All Mail for cleanup: {select_status} {select_data}")

    if select_status != "OK":
        mail.logout()
        return

    for folder, uid in touched:
        fetch_status, fetch_data = mail.uid(
            "FETCH",
            uid,
            "(X-GM-LABELS FLAGS)",
        )
        print(f"Before cleanup UID {uid.decode()}: {fetch_status} {fetch_data}")

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

        seen_status, seen_response = mail.uid(
            "STORE",
            uid,
            "+FLAGS",
            "\\Seen",
        )

        print(
            f"Mark seen UID {uid.decode()}: "
            f"{seen_status} {seen_response}"
        )

        fetch_status, fetch_data = mail.uid(
            "FETCH",
            uid,
            "(X-GM-LABELS FLAGS)",
        )
        print(f"After cleanup UID {uid.decode()}: {fetch_status} {fetch_data}")

    mail.logout()