import os
import re
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()


def _origin(value):
    text = (value or "").strip()
    if not text:
        return None
    parsed = urlsplit(text if "://" in text else f"https://{text}")
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def cors_origins():
    values = []
    for value in os.getenv("FRONTEND_ORIGIN", "").split(","):
        origin = _origin(value)
        if origin and origin not in values:
            values.append(origin)
    for key in ("VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
        origin = _origin(os.getenv(key, ""))
        if origin and origin not in values:
            values.append(origin)
    return values


def origin_is_allowed(origin):
    normalized = _origin(origin)
    if not normalized:
        return False
    if normalized in cors_origins():
        return True
    return re.fullmatch(r"https?://(?:localhost|127\.0\.0\.1)(?::[0-9]{1,5})?", normalized) is not None


def cookie_is_secure():
    return os.getenv("VERCEL", "") == "1" or os.getenv("ENVIRONMENT", "").lower() == "production"


def required_env(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required.")
    return value
