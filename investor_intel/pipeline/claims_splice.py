from __future__ import annotations

import re

from investor_intel.models.analysis import Claim, ExtractionResult

_HEADER_RE = re.compile(r"^## (.+)$", re.MULTILINE)


def _render_claims(claims: list[Claim]) -> str:
    if not claims:
        return "\n(추출된 핵심 주장 없음)\n\n"
    lines = [f"- {c.claim} ({c.direction.value}, 확신도: {c.confidence.value})" for c in claims]
    return "\n" + "\n".join(lines) + "\n\n"


def _render_evidence(claims: list[Claim]) -> str:
    lines = [f"- {evidence}" for claim in claims for evidence in claim.evidence]
    if not lines:
        return "\n(근거 없음)\n\n"
    return "\n" + "\n".join(lines) + "\n\n"


def _render_counter_evidence(claims: list[Claim]) -> str:
    lines = [f"- {evidence}" for claim in claims for evidence in claim.counter_evidence]
    if not lines:
        return "\n(반대 근거 없음)\n\n"
    return "\n" + "\n".join(lines) + "\n\n"


def _render_assets(claims: list[Claim]) -> str:
    seen: list[str] = []
    for claim in claims:
        for asset in claim.assets:
            if asset not in seen:
                seen.append(asset)
    if not seen:
        return "\n(언급 자산 없음)\n\n"
    return "\n" + ", ".join(seen) + "\n\n"


_SECTION_RENDERERS = {
    "핵심 주장": _render_claims,
    "근거": _render_evidence,
    "반대 근거": _render_counter_evidence,
    "언급 자산": _render_assets,
}


def _split_sections(body: str) -> list[tuple[str | None, str]]:
    matches = list(_HEADER_RE.finditer(body))
    sections: list[tuple[str | None, str]] = []
    if not matches:
        return [(None, body)]
    if matches[0].start() > 0:
        sections.append((None, body[: matches[0].start()]))
    for i, match in enumerate(matches):
        header = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections.append((header, body[start:end]))
    return sections


def splice_claims_into_body(body: str, extraction: ExtractionResult) -> str:
    sections = _split_sections(body)
    out: list[str] = []
    for header, content in sections:
        if header is None:
            out.append(content)
            continue
        out.append(f"## {header}")
        renderer = _SECTION_RENDERERS.get(header)
        out.append(renderer(extraction.claims) if renderer else content)
    return "".join(out)
