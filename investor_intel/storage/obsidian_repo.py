from __future__ import annotations

import re
from pathlib import Path

import yaml

from investor_intel.models.source_document import SourceDocument

_FORBIDDEN_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

_SOURCE_TYPE_DIR = {
    "naver": "Naver",
    "telegram": "Telegram",
    "sec_filing": "SEC",
    "sec_13f": "13F",
    "dart": "DART",
    "essay": "Essays",
    "ib_insights": "IB",
    "web_search": "WebSearch",
    "earnings_transcript": "EarningsTranscript",
    "central_bank": "CentralBank",
}

_FRONTMATTER_FIELD_ORDER = [
    "id",
    "source_type",
    "source_name",
    "author",
    "title",
    "source_url",
    "source_specific_id",
    "published_at",
    "collected_at",
    "updated_at",
    "language",
    "content_hash",
    "content_capture",
    "assets",
    "companies",
    "themes",
    "document_type",
    "filing_type",
    "reporting_period",
    "accession_number",
    "llm_processed",
    "llm_model",
    "llm_prompt_version",
]


def sanitize_path_component(value: str) -> str:
    cleaned = _FORBIDDEN_CHARS.sub("_", value)
    cleaned = cleaned.strip(" .")
    return cleaned or "untitled"


def path_for_document(vault_path: Path, doc: SourceDocument) -> Path:
    source_type_dir = _SOURCE_TYPE_DIR[doc.source_type.value]
    source_name = sanitize_path_component(doc.source_name)
    year = f"{doc.published_at:%Y}"
    date_str = f"{doc.published_at:%Y-%m-%d}"
    filename = f"{date_str}-{sanitize_path_component(doc.id)}.md"
    return vault_path / "10_Sources" / source_type_dir / source_name / year / filename


def _frontmatter_dict(doc: SourceDocument) -> dict:
    data = doc.model_dump(mode="json", exclude={"assets"})
    data["assets"] = [asset.model_dump(mode="json") for asset in doc.assets]
    return {key: data[key] for key in _FRONTMATTER_FIELD_ORDER}


def render_document(doc: SourceDocument, body: str) -> str:
    frontmatter_yaml = yaml.safe_dump(
        _frontmatter_dict(doc), allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    return f"---\n{frontmatter_yaml}---\n\n{body}"


def parse_document(text: str) -> tuple[SourceDocument, str]:
    if not text.startswith("---\n"):
        raise ValueError("document missing frontmatter block")
    end_index = text.index("\n---\n", 4)
    frontmatter_yaml = text[4:end_index]
    body = text[end_index + len("\n---\n") :].removeprefix("\n")
    data = yaml.safe_load(frontmatter_yaml)
    return SourceDocument.model_validate(data), body


def write_document(vault_path: Path, doc: SourceDocument, body: str) -> Path:
    path = path_for_document(vault_path, doc)
    if path.exists():
        existing_doc, _ = parse_document(path.read_text(encoding="utf-8"))
        if existing_doc.content_hash == doc.content_hash:
            return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_document(doc, body), encoding="utf-8")
    return path


def read_document(path: Path) -> tuple[SourceDocument, str]:
    return parse_document(path.read_text(encoding="utf-8"))


def resolve_document_path(vault_path: Path, raw_file_path: str) -> Path | None:
    """`documents.file_path`가 실제로 vault_path 기준 상대경로인지, `vault_path`의 부모
    디렉터리(즉 "vault/..." 접두어 포함) 기준 상대경로인지가 `reindex()` 호출 시점의
    `--vault-path` 값에 따라 달라질 수 있어(이 저장소를 실제로 운영해보며 확인됨) 두 후보를
    모두 시도한다 - 절대경로로 이미 저장된 경우도 처리한다."""
    raw = Path(raw_file_path)
    candidates = (
        [raw]
        if raw.is_absolute()
        else [vault_path / raw, vault_path.parent / raw]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def list_documents(vault_path: Path) -> list[Path]:
    sources_dir = vault_path / "10_Sources"
    if not sources_dir.exists():
        return []
    return sorted(sources_dir.rglob("*.md"))
