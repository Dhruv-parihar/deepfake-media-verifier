import os

from dotenv import load_dotenv

load_dotenv()

DEEPWARE_API_KEY = os.getenv("DEEPWARE_API_KEY", "").strip()
DEEPWARE_BASE_URL = os.getenv("DEEPWARE_BASE_URL", "https://api.deepware.ai/api/v1").strip()
DEEPWARE_FILE_FIELD = os.getenv("DEEPWARE_FILE_FIELD", "file").strip()
DEEPWARE_POLL_SECONDS = int(os.getenv("DEEPWARE_POLL_SECONDS", "10"))
DEEPWARE_TIMEOUT_SECONDS = int(os.getenv("DEEPWARE_TIMEOUT_SECONDS", "600"))
DEEPWARE_WEB_SCANNER = "https://scanner.deepware.ai"
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "reports_out")
