import base64
import hashlib
import logging
import re
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy.types import String, Text, TypeDecorator

from locus.config import get_settings

logger = logging.getLogger(__name__)


def _derive_fernet_key(key_str: str) -> bytes:
    """Derive a valid 32-byte urlsafe base64-encoded Fernet key."""
    try:
        raw = base64.urlsafe_b64decode(key_str.encode("utf-8"))
        if len(raw) == 32:
            return key_str.encode("utf-8")
    except Exception:
        pass
    digest = hashlib.sha256(key_str.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=4)
def _get_fernet_cached(enc_key: str, secret_key: str) -> MultiFernet:
    key_bytes_list = []
    if enc_key:
        key_bytes_list.append(_derive_fernet_key(enc_key))
    if secret_key:
        sec_bytes = _derive_fernet_key(secret_key)
        if sec_bytes not in key_bytes_list:
            key_bytes_list.append(sec_bytes)
    if not key_bytes_list:
        key_bytes_list.append(_derive_fernet_key("locus_default_secret_key_fallback"))
    return MultiFernet([Fernet(k) for k in key_bytes_list])


def get_fernet() -> MultiFernet:
    """Get MultiFernet cipher instance with active key and fallback keys for rotation safety."""
    settings = get_settings()
    return _get_fernet_cached(
        (settings.ENCRYPTION_KEY or "").strip(),
        (settings.SECRET_KEY or "").strip(),
    )


def encrypt_string(value: Optional[str]) -> Optional[str]:
    """Encrypt a plaintext string using Fernet symmetric encryption."""
    if not value or not value.strip():
        return None
    cipher = get_fernet()
    return cipher.encrypt(value.strip().encode("utf-8")).decode("utf-8")


def decrypt_string(ciphertext: Optional[str]) -> Optional[str]:
    """Decrypt a Fernet ciphertext string.

    Returns None and logs a warning if ciphertext is invalid/tampered.
    Falls back to returning ciphertext directly if it is legacy unencrypted plaintext.
    """
    if not ciphertext:
        return None
    cleaned = ciphertext.strip()
    if not cleaned:
        return None
    cipher = get_fernet()
    try:
        return cipher.decrypt(cleaned.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception) as exc:
        if not cleaned.startswith("gAAAAA"):
            return cleaned
        logger.warning("Failed to decrypt ciphertext with active encryption key: %s", exc)
        return None


def format_whatsapp_url(phone: Optional[str]) -> Optional[str]:
    """Format teacher phone number into a valid WhatsApp click-to-chat URL.

    Strips non-digits and extensions, normalizes Russian 8XXXXXXXXXX and 10-digit formats to 7XXXXXXXXXX,
    and returns https://wa.me/<digits>. Returns None if phone has fewer than 10 digits.
    """
    if not phone or not phone.strip():
        return None

    trimmed = phone.strip()
    has_plus = trimmed.startswith("+")

    # Strip any extension notations like "доб.", "доб", "ext"
    clean_phone = re.split(r"(?i)\s*(?:доб|ext|внутр)[\.\s]*\d*", trimmed)[0]
    digits = re.sub(r"\D", "", clean_phone)
    if not digits or len(digits) < 10:
        return None

    # 10 digits (e.g. 9991234567) -> add Russia/Kazakhstan country code 7
    if len(digits) == 10:
        digits = "7" + digits
    # 11 digits starting with 8 without a leading plus (e.g. 89991234567) -> convert to 79991234567
    # (Preserves international numbers like +855... that start with country code 8)
    elif len(digits) == 11 and digits.startswith("8") and not has_plus:
        digits = "7" + digits[1:]

    return f"https://wa.me/{digits}"


class EncryptedString(TypeDecorator):
    """SQLAlchemy TypeDecorator for at-rest field encryption using Text column in DB.

    Note: Fernet uses a random IV for every encryption call, making ciphertexts
    non-deterministic. Equality lookups in SQL (e.g. WHERE teacher_phone = ...)
    will not match ciphertext.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Optional[str], dialect) -> Optional[str]:
        if value is None:
            return None
        return encrypt_string(value)

    def process_result_value(self, value: Optional[str], dialect) -> Optional[str]:
        if value is None:
            return None
        return decrypt_string(value)
