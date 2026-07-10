from __future__ import annotations

import email
import imaplib
import re
from email.header import decode_header, make_header
from pathlib import Path


ALLOWED_EXTENSIONS = (".pdf",)

# Reportes permitidos en la búsqueda de respaldo.
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


def quote_gmail_value(value: str) -> str:
    """
    Escapa un valor para utilizarlo en una búsqueda X-GM-RAW.

    Ejemplo:
        SLANE             -> "SLANE"
        Opera Reports     -> "Opera Reports"
    """
    value = clean_text(value)
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')

    return f'"{value}"'


def gmail_raw_query(label: str) -> str:
    """
    Búsqueda principal por etiqueta.

    Las comillas permiten trabajar también con etiquetas que contienen
    espacios o caracteres especiales.
    """
    quoted_label = quote_gmail_value(label)

    return (
        f"label:{quoted_label} "
        f"is:unread "
        f"has:attachment"
    )


def gmail_fallback_query() -> str:
    """
    Búsqueda de respaldo.

    Busca correos no leídos con adjuntos cuyo asunto corresponda
    a los reportes del DataHub.
    """
    subject_conditions = " ".join(
        f"subject:{quote_gmail_value(marker)}"
        for marker in ALLOWED_SUBJECT_MARKERS
    )

    return (
        f"is:unread "
        f"has:attachment "
        f"{{{subject_conditions}}}"
    )


def get_all_mail_folder(mail: imaplib.IMAP4_SSL) -> str:
    status, folders = mail.list()

    if status != "OK" or not folders:
        return '"INBOX"'

    for raw in folders:
        line = raw.decode(errors="ignore")

        if "\\All" in line:
            mailbox = line.split(' "/" ')[-1]
            return mailbox

    return '"INBOX"'


def search_messages(
    mail: imaplib.IMAP4_SSL,
    query: str,
) -> list[bytes]:
    """
    Ejecuta una búsqueda Gmail X-GM-RAW y devuelve números
    de secuencia IMAP.
    """
    try:
        status, data = mail.search(
            None,
            "X-GM-RAW",
            f'"{query}"',
        )

    except imaplib.IMAP4.error as exc:
        print(f"Gmail search command failed: {exc}")
        return []

    print(f"GMAIL SEARCH QUERY: {query}")
    print(f"GMAIL SEARCH RESULT: {status} {data}")

    if status != "OK" or not data:
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

    uid_text = raw_response.decode(errors="ignore")

    match = re.search(r"\bUID\s+(\d+)", uid_text)

    if not match:
        print(
            f"Could not parse UID for message "
            f"{msg_id.decode(errors='ignore')}: "
            f"{uid_text}"
        )
        return None

    return match.group(1).encode()


def subject_is_allowed(subject: str) -> bool:
    """
    Protección para que la búsqueda de respaldo no descargue
    cualquier PDF personal no leído.
    """
    subject_lower = clean_text(subject).lower()

    return any(
        marker.lower() in subject_lower
        for marker in ALLOWED_SUBJECT_MARKERS
    )


def download_csv_attachments(
    host: str,
    port: int,
    user: str,
    password: str,
    folder: str,
    incoming_dir: Path,
) -> list[tuple[str, bytes]]:
    """
    Descarga adjuntos PDF no leídos.

    Primero busca por la etiqueta configurada.
    Si no encuentra mensajes, utiliza una búsqueda de respaldo
    por asunto: snapshot u ODATA_.

    Returns:
        [(folder, uid)]
    """

    touched: list[tuple[str, bytes]] = []

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
        print(f"Using mailbox: {all_mail}")

        select_status, select_data = mail.select(all_mail)
        print(
            f"SELECT All Mail: "
            f"{select_status} {select_data}"
        )

        if select_status != "OK":
            return touched

        primary_query = gmail_raw_query(folder)
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

            if status != "OK" or not msg_data:
                print(
                    f"Email fetch failed for UID "
                    f"{uid.decode()}: {status}"
                )
                continue

            raw_message = None

            for item in msg_data:
                if (
                    isinstance(item, tuple)
                    and len(item) >= 2
                    and isinstance(item[1], bytes)
                ):
                    raw_message = item[1]
                    break

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
            print(f"Message-ID: {message_id}")

            # La búsqueda secundaria podría encontrar otros PDFs.
            # Solo aceptamos asuntos relacionados con el DataHub.
            if used_fallback and not subject_is_allowed(subject):
                print(
                    f"Skipped by subject filter: {subject}"
                )
                continue

            saved_any = False

            for part in msg.walk():
                filename = part.get_filename()

                if not filename:
                    continue

                filename = decode_mime_text(filename)
                safe_name = Path(filename).name

                if not safe_name.lower().endswith(
                    ALLOWED_EXTENSIONS
                ):
                    continue

                payload = part.get_payload(
                    decode=True
                )

                if not payload:
                    print(
                        f"Attachment empty: {safe_name}"
                    )
                    continue

                out_path = incoming_dir / safe_name

                # Evita sobrescribir otro archivo ya descargado
                # con el mismo nombre.
                if out_path.exists():
                    out_path = incoming_dir / (
                        f"{out_path.stem}_{uid.decode()}"
                        f"{out_path.suffix}"
                    )

                out_path.write_bytes(payload)

                print(
                    f"Downloaded: {out_path} "
                    f"({len(payload):,} bytes)"
                )

                saved_any = True

            if saved_any:
                touched.append(
                    (folder, uid)
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
    touched: list[tuple[str, bytes]],
) -> None:
    """
    Después de procesar correctamente:

    1. Intenta eliminar la etiqueta configurada.
    2. Marca el correo como leído.

    Si el correo fue encontrado mediante la búsqueda de respaldo y
    no tenía esa etiqueta, el STORE de eliminación puede no modificar
    nada, pero igualmente será marcado como leído.
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

        all_mail = get_all_mail_folder(mail)

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

        for folder, uid in touched:
            fetch_status, fetch_data = mail.uid(
                "FETCH",
                uid,
                "(X-GM-LABELS FLAGS)",
            )

            print(
                f"Before cleanup UID {uid.decode()}: "
                f"{fetch_status} {fetch_data}"
            )

            status, response = mail.uid(
                "STORE",
                uid,
                "-X-GM-LABELS",
                quote_gmail_value(folder),
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
                f"Mark seen UID {uid.decode()}: "
                f"{seen_status} {seen_response}"
            )

            fetch_status, fetch_data = mail.uid(
                "FETCH",
                uid,
                "(X-GM-LABELS FLAGS)",
            )

            print(
                f"After cleanup UID {uid.decode()}: "
                f"{fetch_status} {fetch_data}"
            )

    finally:
        try:
            mail.logout()
        except Exception:
            pass