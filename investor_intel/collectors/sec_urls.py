from __future__ import annotations

_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data/{cik_short}/{accession_nodashes}"


def cik_short(cik: str) -> str:
    return cik.lstrip("0") or "0"


def accession_nodashes(accession_number: str) -> str:
    return accession_number.replace("-", "")


def archive_dir(cik: str, accession_number: str) -> str:
    return _ARCHIVES_BASE.format(
        cik_short=cik_short(cik), accession_nodashes=accession_nodashes(accession_number)
    )


def filing_index_url(cik: str, accession_number: str) -> str:
    return f"{archive_dir(cik, accession_number)}/index.json"


def filing_index_page_url(cik: str, accession_number: str) -> str:
    return f"{archive_dir(cik, accession_number)}/{accession_number}-index.htm"


def document_url(cik: str, accession_number: str, filename: str) -> str:
    return f"{archive_dir(cik, accession_number)}/{filename}"
