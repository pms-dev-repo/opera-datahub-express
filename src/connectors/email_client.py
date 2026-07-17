from __future__ import annotations

import email
import imaplib
import re
from dataclasses import dataclass
from email.header import decode_header, make_header
from pathlib import Path


@dataclass
class EmailDownload:
    folder: str
    uid: bytes
    attachments: list[Path]



ALLOWED_EXTENSIONS = (".pdf",)

ALLOWED_SUBJECT_MARKERS = (
    "snapshot",
    "odata_",
)


def clean_text(value) -> str:
    value = str(value or "").strip()
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def decode_mime_text(value) -> str:
    if not value:
        return ""

    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


def gmail_raw_query(label: str) -> str:
    """
    Consulta principal por etiqueta Gmail.

    No agrega comillas internas para evitar que IMAP genere:
    BAD Could not parse command
    """
    label = clean_text(label)

    return (
        f"label:{label} "
        f"is:unread "
        f"has:attachment"
    )


def gmail_fallback_query() -> str:
    """
    Consulta de respaldo cuando Gmail no encuentra mensajes
    mediante la etiqueta configurada.
    """
    return (
        "is:unread "
        "has:attachment "
        "{subject:snapshot subject:odata_}"
    )


def get_all_mail_folder(
    mail: imaplib.IMAP4_SSL,
) -> str:
    status, folders = mail.list()

    if status != "OK" or not folders:
        return '"INBOX"'

    for raw in folders:
        line = raw.decode(errors="ignore")

        if "\\All" in line:
            return line.split(' "/" ')[-1]

    return '"INBOX"'


def search_messages(
    mail: imaplib.IMAP4_SSL,
    query: str,
) -> list[bytes]:
    """
    Ejecuta Gmail X-GM-RAW.

    La consulta completa se envía como un solo argumento IMAP.
    """

    print(f"GMAIL SEARCH QUERY: {query}")

    try:
        status, data = mail.search(
            None,
            "X-GM-RAW",
            f'"{query}"',
        )

    except imaplib.IMAP4.error as exc:
        print(f"Gmail search command failed: {exc}")
        return []

    print(f"GMAIL SEARCH RESULT: {status} {data}")

    if (
        status != "OK"
        or not data
        or not data[0]
    ):
        return []

    return data[0].split()


def get_uid_from_sequence(
    mail: imaplib.IMAP4_SSL,
    msg_id: bytes,
) -> bytes | None:
    status, uid_data = mail.fetch(
        msg_id,
        "(UID)",
    )

    if status != "OK" or not uid_data:
        print(
            f"Could not get UID for message "
            f"{msg_id.decode(errors='ignore')}"
        )
        return None

    raw_response = uid_data[0]

    if not isinstance(raw_response, bytes):
        return None

    uid_text = raw_response.decode(
        errors="ignore"
    )

    match = re.search(
        r"\bUID\s+(\d+)",
        uid_text,
    )

    if not match:
        print(
            f"Could not parse UID for message "
            f"{msg_id.decode(errors='ignore')}: "
            f"{uid_text}"
        )
        return None

    return match.group(1).encode()


def subject_is_allowed(
    subject: str,
) -> bool:
    subject_lower = clean_text(
        subject
    ).lower()

    return any(
        marker.lower() in subject_lower
        for marker in ALLOWED_SUBJECT_MARKERS
    )


def extract_rfc822_payload(
    msg_data,
) -> bytes | None:
    if not msg_data:
        return None

    for item in msg_data:
        if (
            isinstance(item, tuple)
            and len(item) >= 2
            and isinstance(item[1], bytes)
        ):
            return item[1]

    return None


def unique_output_path(
    incoming_dir: Path,
    filename: str,
    uid: bytes,
) -> Path:
    safe_name = Path(filename).name
    out_path = incoming_dir / safe_name

    if not out_path.exists():
        return out_path

    return incoming_dir / (
        f"{out_path.stem}_{uid.decode()}"
        f"{out_path.suffix}"
    )


def download_csv_attachments(
    host: str,
    port: int,
    user: str,
    password: str,
    folder: str,
    incoming_dir: Path,
) -> list[EmailDownload]:
    """
    Descarga archivos PDF no leídos.

    Primero busca por la etiqueta configurada.

    Si no encuentra correos, usa una búsqueda de respaldo
    basada en los asuntos snapshot y ODATA_.

    Returns:
        One EmailDownload per email containing the UID and saved attachments.
    """

    touched: list[EmailDownload] = []

    if not user or not password:
        print(
            "Email credentials not configured. "
            "Skipping email download."
        )
        return touched

    incoming_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    mail = imaplib.IMAP4_SSL(
        host,
        port,
    )

    try:
        mail.login(
            user,
            password,
        )

        all_mail = get_all_mail_folder(mail)

        print(
            f"Using mailbox: {all_mail}"
        )

        select_status, select_data = mail.select(
            all_mail
        )

        print(
            f"SELECT All Mail: "
            f"{select_status} {select_data}"
        )

        if select_status != "OK":
            return touched

        primary_query = gmail_raw_query(
            folder
        )

        message_ids = search_messages(
            mail,
            primary_query,
        )

        used_fallback = False

        if not message_ids:
            print(
                "No messages found using the configured label. "
                "Trying report-subject fallback search."
            )

            fallback_query = gmail_fallback_query()

            message_ids = search_messages(
                mail,
                fallback_query,
            )

            used_fallback = True

        print(
            f"Messages selected for review: "
            f"{len(message_ids)}"
        )

        for msg_id in message_ids:
            uid = get_uid_from_sequence(
                mail,
                msg_id,
            )

            if not uid:
                continue

            status, msg_data = mail.uid(
                "FETCH",
                uid,
                "(RFC822)",
            )

            if status != "OK":
                print(
                    f"Email fetch failed for UID "
                    f"{uid.decode()}: {status}"
                )
                continue

            raw_message = extract_rfc822_payload(
                msg_data
            )

            if not raw_message:
                print(
                    f"No RFC822 payload found for UID "
                    f"{uid.decode()}"
                )
                continue

            msg = email.message_from_bytes(
                raw_message
            )

            subject = decode_mime_text(
                msg.get("Subject", "")
            )

            message_id = clean_text(
                msg.get("Message-ID", "")
            )

            print(
                f"Reading UID {uid.decode()} "
                f"| Subject: {subject}"
            )

            print(
                f"Message-ID: {message_id}"
            )

            if (
                used_fallback
                and not subject_is_allowed(subject)
            ):
                print(
                    f"Skipped by subject filter: "
                    f"{subject}"
                )
                continue

            saved_paths: list[Path] = []

            for part in msg.walk():
                filename = part.get_filename()

                if not filename:
                    continue

                filename = decode_mime_text(
                    filename
                )

                safe_name = Path(
                    filename
                ).name

                if not safe_name.lower().endswith(
                    ALLOWED_EXTENSIONS
                ):
                    continue

                payload = part.get_payload(
                    decode=True
                )

                if not payload:
                    print(
                        f"Attachment empty: "
                        f"{safe_name}"
                    )
                    continue

                out_path = unique_output_path(
                    incoming_dir,
                    safe_name,
                    uid,
                )

                out_path.write_bytes(
                    payload
                )

                print(
                    f"Downloaded: {out_path} "
                    f"({len(payload):,} bytes)"
                )

                saved_paths.append(out_path)

            if saved_paths:
                touched.append(
                    EmailDownload(
                        folder=folder,
                        uid=uid,
                        attachments=saved_paths,
                    )
                )

        return touched

    finally:
        try:
            mail.logout()
        except Exception:
            pass


def delete_messages(
    host: str,
    port: int,
    user: str,
    password: str,
    touched: list[EmailDownload],
) -> None:
    """
    Después de procesar correctamente:

    1. Elimina la etiqueta Gmail configurada.
    2. Marca el correo como leído.
    """

    if not touched:
        return

    mail = imaplib.IMAP4_SSL(
        host,
        port,
    )

    try:
        mail.login(
            user,
            password,
        )

        all_mail = get_all_mail_folder(
            mail
        )

        print(
            f"Using mailbox for cleanup: "
            f"{all_mail}"
        )

        select_status, select_data = mail.select(
            all_mail
        )

        print(
            f"SELECT All Mail for cleanup: "
            f"{select_status} {select_data}"
        )

        if select_status != "OK":
            return

        for item in touched:
            folder = item.folder
            uid = item.uid
            fetch_status, fetch_data = mail.uid(
                "FETCH",
                uid,
                "(X-GM-LABELS FLAGS)",
            )

            print(
                f"Before cleanup UID "
                f"{uid.decode()}: "
                f"{fetch_status} {fetch_data}"
            )

            status, response = mail.uid(
                "STORE",
                uid,
                "-X-GM-LABELS",
                f'"{folder}"',
            )

            print(
                f"Remove label {folder} from UID "
                f"{uid.decode()}: "
                f"{status} {response}"
            )

            seen_status, seen_response = mail.uid(
                "STORE",
                uid,
                "+FLAGS",
                r"(\Seen)",
            )

            print(
                f"Mark seen UID "
                f"{uid.decode()}: "
                f"{seen_status} {seen_response}"
            )

            fetch_status, fetch_data = mail.uid(
                "FETCH",
                uid,
                "(X-GM-LABELS FLAGS)",
            )

            print(
                f"After cleanup UID "
                f"{uid.decode()}: "
                f"{fetch_status} {fetch_data}"
            )

    finally:
        try:
            mail.logout()
        except Exception:
            pass