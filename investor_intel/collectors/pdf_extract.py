from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader


class PdfExtractError(Exception):
    pass


def extract_pdf_text(pdf_bytes: bytes) -> str:
    # pypdf raises more than just PdfReadError for malformed/encrypted input (e.g. a bare
    # NotImplementedError/ValueError from the crypto backend when a PDF's encryption scheme
    # isn't supported) - catch broadly so any parse failure degrades to metadata_only in the
    # collector instead of aborting the whole document.
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # noqa: BLE001
        raise PdfExtractError(f"PDF 파싱 실패: {exc}") from exc

    text = "\n\n".join(page.strip() for page in pages if page.strip())
    if not text:
        raise PdfExtractError("PDF에서 텍스트를 추출하지 못함 (스캔본이거나 빈 문서)")
    return text
