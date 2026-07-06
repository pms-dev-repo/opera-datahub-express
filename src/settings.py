import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
EMAIL_HOST = os.getenv("EMAIL_HOST", "imap.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT") or "993")
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_FOLDER = os.getenv("EMAIL_FOLDER", "INBOX")
EMAIL_DELETE_AFTER_SUCCESS = os.getenv("EMAIL_DELETE_AFTER_SUCCESS", "true").lower() == "true"

BASE_DIR = Path(__file__).resolve().parents[1]
INCOMING_DIR = Path(os.getenv("INCOMING_DIR", "data/incoming"))
ARCHIVE_DIR = Path(os.getenv("ARCHIVE_DIR", "data/archive"))
ERROR_DIR = Path(os.getenv("ERROR_DIR", "data/error"))

for folder in [INCOMING_DIR, ARCHIVE_DIR, ERROR_DIR]:
    folder.mkdir(parents=True, exist_ok=True)
