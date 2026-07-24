from __future__ import annotations

import hashlib
import re
import unicodedata


def normalize_content(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text)
    normalized = normalized.strip()
    return re.sub(r"\s+", " ", normalized)


def compute_content_hash(text: str) -> str:
    normalized = normalize_content(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_stable_id(
    source_type: str,
    source_name: str,
    source_specific_id: str | None,
    canonical_url: str,
) -> str:
    key_part = source_specific_id if source_specific_id else canonical_url
    key = f"{source_type}|{source_name}|{key_part}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
