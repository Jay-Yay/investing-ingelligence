from __future__ import annotations


def classify_dart_report(report_nm: str) -> str | None:
    """report_nm(예: '반기보고서 (2025.06)')에서 정기보고서 종류를 판별한다.

    "사업보고서"를 "반기보고서"/"분기보고서"보다 먼저 검사해야 한다 - 사업보고서 안에도
    "반기"라는 단어가 들어가는 경우는 없지만, 방어적으로 순서를 명시한다.
    """
    if "사업보고서" in report_nm:
        return "연간"
    if "반기보고서" in report_nm:
        return "반기"
    if "분기보고서" in report_nm:
        return "분기"
    return None


def classify_sec_form(form: str) -> str | None:
    """SEC form 코드(예: '10-K', '10-K/A')에서 정기보고서 종류를 판별한다."""
    base = form.split("/")[0]
    if base in ("10-K", "20-F"):
        return "연간"
    if base == "10-Q":
        return "분기"
    return None


def title_prefix(kind: str | None) -> str:
    return f"[{kind}보고서] " if kind else ""
