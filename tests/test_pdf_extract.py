import pytest

from investor_intel.collectors.pdf_extract import PdfExtractError, extract_pdf_text

_VALID_PDF_WITH_TEXT = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/Resources<</Font<</F1 4 0 R>>>>
/MediaBox[0 0 200 200]/Contents 5 0 R>>endobj
4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
5 0 obj<</Length 44>>
stream
BT /F1 12 Tf 10 100 Td (Hello PDF World) Tj ET
endstream
endobj
xref
0 6
trailer<</Size 6/Root 1 0 R>>
startxref
0
%%EOF"""

_VALID_PDF_WITH_NO_TEXT = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R>>endobj
4 0 obj<</Length 0>>
stream
endstream
endobj
xref
0 5
trailer<</Size 5/Root 1 0 R>>
startxref
0
%%EOF"""


def test_extract_pdf_text_returns_page_text() -> None:
    text = extract_pdf_text(_VALID_PDF_WITH_TEXT)
    assert "Hello PDF World" in text


def test_extract_pdf_text_raises_for_malformed_bytes() -> None:
    with pytest.raises(PdfExtractError):
        extract_pdf_text(b"not a pdf at all")


def test_extract_pdf_text_raises_when_no_extractable_text() -> None:
    with pytest.raises(PdfExtractError):
        extract_pdf_text(_VALID_PDF_WITH_NO_TEXT)
