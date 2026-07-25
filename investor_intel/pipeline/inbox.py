from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from investor_intel.collectors.dart_client import DartClient
from investor_intel.collectors.dart_corp_code import resolve_dart_company
from investor_intel.collectors.ib_insights import IB_INSIGHTS_SOURCES
from investor_intel.collectors.naver_research import LIST_URL as NAVER_RESEARCH_LIST_URL
from investor_intel.collectors.sec_client import SECClient
from investor_intel.config.loaders import (
    load_companies_yaml,
    load_dart_companies_yaml,
    load_investors_yaml,
    load_sources_yaml,
)
from investor_intel.models.config import (
    CompanyConfig,
    InvestorConfig,
    KoreanCompanyConfig,
    SourceConfig,
)

_CHECKLIST_RE = re.compile(r"^-\s\[([ xX])\]\s*(.*)$")
_ENTRY_RE = re.compile(r"^(\w+):\s*(.+)$")

IB_INSIGHTS_TYPES = set(IB_INSIGHTS_SOURCES.keys()) | {"naver_research"}
SUPPORTED_TYPES = {
    "naver",
    "telegram",
    "telegram_private",
    "sec",
    "dart",
    "investor",
    *IB_INSIGHTS_TYPES,
}

_SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_SEC_TICKER_CACHE_TTL_SECONDS = 24 * 60 * 60

_DART_COMPANIES_HEADER = (
    "  # corp_code는 생략 가능하다 - 최초 수집 시 ticker/name으로 OpenDART corpCode.xml에서\n"
    "  # 자동 조회 후 캐시된다. 직접 알고 있다면 채워도 된다.\n"
)


class InboxResolveError(Exception):
    pass


@dataclass
class InboxLine:
    line_no: int
    checked: bool
    type: str | None
    value: str | None
    extra: str | None
    raw: str


@dataclass
class InboxResult:
    line_no: int
    status: Literal["added", "skipped_duplicate", "failed", "parse_error"]
    type: str | None
    identifier: str | None
    message: str


def parse_inbox_lines(text: str) -> list[InboxLine]:
    lines: list[InboxLine] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        checklist_match = _CHECKLIST_RE.match(raw.strip())
        if not checklist_match:
            continue

        checked = checklist_match.group(1).lower() == "x"
        body = checklist_match.group(2).strip()
        entry_match = _ENTRY_RE.match(body)
        if not entry_match:
            lines.append(InboxLine(i, checked, None, None, None, raw))
            continue

        type_ = entry_match.group(1)
        rest = entry_match.group(2).strip()
        value, _, extra = rest.partition("|")
        lines.append(
            InboxLine(i, checked, type_, value.strip(), extra.strip() or None, raw)
        )
    return lines


def _slug_from_url(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def resolve_naver(value: str) -> SourceConfig:
    slug = _slug_from_url(value)
    return SourceConfig(
        id=f"naver_{slug}",
        type="naver",
        name=slug,
        enabled=True,
        url=value,
        author=slug,
        weight=1.0,
        collection_mode="full",
        backfill_days=365,
        tags=["blog"],
    )


def resolve_telegram(value: str) -> SourceConfig:
    slug = _slug_from_url(value)
    # the public-preview collector only understands t.me/s/{channel} - normalize a bare
    # t.me/{channel} link (what users naturally copy) to that shape.
    url = f"https://t.me/s/{slug}"
    return SourceConfig(
        id=f"telegram_{slug}",
        type="telegram",
        name=slug,
        enabled=True,
        url=url,
        author=None,
        weight=1.0,
        collection_mode="full",
        backfill_days=365,
        tags=["telegram"],
    )


def resolve_telegram_private(value: str) -> SourceConfig:
    slug = _slug_from_url(value)
    return SourceConfig(
        id=f"telegram_private_{slug}",
        type="telegram_private",
        name=slug,
        enabled=True,
        url=value,
        author=None,
        weight=1.0,
        collection_mode="full",
        backfill_days=365,
        tags=["telegram", "private"],
    )


def resolve_ib_insights(type_: str, value: str) -> SourceConfig:
    # unlike naver/telegram, there is exactly one fixed index page per bank - `value` is just a
    # free-text label for the id/name (e.g. the bank's short name), not a URL the user supplies.
    # naver_research isn't in IB_INSIGHTS_SOURCES (it uses its own dedicated collector, not the
    # generic IBInsightsCollector), so its display URL is looked up separately.
    if type_ == "naver_research":
        index_url = NAVER_RESEARCH_LIST_URL
    else:
        index_url = IB_INSIGHTS_SOURCES[type_].index_url
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_") or type_
    return SourceConfig(
        id=f"{type_}_{slug}",
        type=type_,
        name=value.strip() or type_,
        enabled=True,
        url=index_url,
        author=None,
        weight=1.0,
        collection_mode="full",
        backfill_days=365,
        tags=["ib_insights"],
    )


def _load_sec_ticker_map(sec_client: SECClient, cache_path: Path) -> dict:
    if cache_path.exists():
        age_seconds = time.time() - cache_path.stat().st_mtime
        if age_seconds < _SEC_TICKER_CACHE_TTL_SECONDS:
            return json.loads(cache_path.read_text(encoding="utf-8"))

    data = sec_client.get_json(_SEC_TICKERS_URL)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(data), encoding="utf-8")
    return data


def resolve_sec(value: str, sec_client: SECClient, cache_path: Path) -> CompanyConfig:
    ticker = value.strip().upper()
    try:
        ticker_map = _load_sec_ticker_map(sec_client, cache_path)
    except Exception as exc:  # noqa: BLE001 - surfaced as InboxResolveError to the caller
        raise InboxResolveError(f"SEC 티커 목록 조회 실패: {exc}") from exc

    match = next(
        (entry for entry in ticker_map.values() if entry.get("ticker", "").upper() == ticker),
        None,
    )
    if match is None:
        raise InboxResolveError(f"SEC 티커 '{ticker}'를 찾을 수 없음")

    cik = f"{int(match['cik_str']):010d}"
    return CompanyConfig(
        ticker=ticker,
        cik=cik,
        name=match["title"],
        filing_types=["10-K", "10-Q", "8-K"],
        is_foreign_private_issuer=False,
    )


def resolve_dart(
    value: str, conn: sqlite3.Connection, dart_client: DartClient, api_key: str
) -> KoreanCompanyConfig:
    stock_code = value.strip()
    try:
        result = resolve_dart_company(conn, dart_client, api_key, stock_code=stock_code)
    except Exception as exc:  # noqa: BLE001 - surfaced as InboxResolveError to the caller
        raise InboxResolveError(f"DART 종목코드 '{stock_code}' 조회 실패: {exc}") from exc
    if result is None:
        raise InboxResolveError(f"DART 종목코드 '{stock_code}'를 찾을 수 없음")

    corp_code, corp_name = result
    return KoreanCompanyConfig(
        ticker=stock_code,
        corp_code=corp_code,
        name=corp_name,
        report_types=["A", "B"],
    )


def resolve_investor(
    value: str, extra: str | None, sec_client: SECClient
) -> InvestorConfig:
    digits = re.sub(r"\D", "", value)
    if not digits:
        raise InboxResolveError(f"CIK 형식이 올바르지 않음: '{value}'")
    cik = f"{int(digits):010d}"

    try:
        data = sec_client.get_json(_SEC_SUBMISSIONS_URL.format(cik=cik))
    except Exception as exc:  # noqa: BLE001 - surfaced as InboxResolveError to the caller
        raise InboxResolveError(f"SEC submissions 조회 실패 (CIK {cik}): {exc}") from exc

    name = data.get("name")
    if not name:
        raise InboxResolveError(f"CIK {cik}에 대한 entityName을 찾을 수 없음")

    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return InvestorConfig(
        id=slug,
        name=name,
        fund_name=name,
        cik=cik,
        related_essay_url=extra,
    )


class _IndentDumper(yaml.SafeDumper):
    def increase_indent(  # type: ignore[override]
        self, flow: bool = False, indentless: bool = False
    ) -> int:
        return super().increase_indent(flow, False)  # type: ignore[return-value]


def _dump(key: str, items: list) -> str:
    payload = {key: [item.model_dump(mode="json") for item in items]}
    return yaml.dump(
        payload, Dumper=_IndentDumper, allow_unicode=True, sort_keys=False, default_flow_style=False
    )


def _mark_checked(raw_line: str) -> str:
    return re.sub(r"\[[ xX]\]", "[x]", raw_line, count=1)


@dataclass
class InboxDeps:
    config_dir: Path
    sec_client: SECClient | None = None
    sec_ticker_cache_path: Path = Path("./data/sec_company_tickers.json")
    dart_conn: sqlite3.Connection | None = None
    dart_client: DartClient | None = None
    dart_api_key: str | None = None


def sync_inbox(inbox_path: Path, deps: InboxDeps) -> tuple[list[InboxResult], str]:
    text = inbox_path.read_text(encoding="utf-8") if inbox_path.exists() else ""
    raw_lines = text.splitlines()
    parsed_lines = parse_inbox_lines(text)

    sources_path = deps.config_dir / "sources.yaml"
    companies_path = deps.config_dir / "companies.yaml"
    dart_path = deps.config_dir / "dart_companies.yaml"
    investors_path = deps.config_dir / "investors.yaml"

    sources = load_sources_yaml(sources_path) if sources_path.exists() else []
    companies = load_companies_yaml(companies_path) if companies_path.exists() else []
    dart_companies = load_dart_companies_yaml(dart_path) if dart_path.exists() else []
    investors = load_investors_yaml(investors_path) if investors_path.exists() else []

    dirty = {"sources": False, "companies": False, "dart": False, "investors": False}
    results: list[InboxResult] = []

    for line in parsed_lines:
        if line.checked:
            continue

        if line.type is None:
            message = "체크리스트 형식이 아님 (- [ ] type: value)"
            results.append(InboxResult(line.line_no, "parse_error", None, None, message))
            continue

        if line.type not in SUPPORTED_TYPES:
            message = f"지원하지 않는 타입: {line.type}"
            results.append(InboxResult(line.line_no, "parse_error", line.type, None, message))
            continue

        assert line.value is not None
        try:
            result = _resolve_and_apply(
                line, sources, companies, dart_companies, investors, dirty, deps
            )
        except InboxResolveError as exc:
            results.append(InboxResult(line.line_no, "failed", line.type, line.value, str(exc)))
            continue

        results.append(result)
        if result.status in ("added", "skipped_duplicate"):
            raw_lines[line.line_no - 1] = _mark_checked(raw_lines[line.line_no - 1])

    if dirty["sources"]:
        sources_path.write_text(_dump("sources", sources), encoding="utf-8")
    if dirty["companies"]:
        companies_path.write_text(_dump("companies", companies), encoding="utf-8")
    if dirty["dart"]:
        dumped = _dump("dart_companies", dart_companies)
        header, _, body = dumped.partition("\n")
        dart_path.write_text(f"{header}\n{_DART_COMPANIES_HEADER}{body}", encoding="utf-8")
    if dirty["investors"]:
        investors_path.write_text(_dump("investors", investors), encoding="utf-8")

    new_text = "\n".join(raw_lines)
    if text.endswith("\n") or not text:
        new_text += "\n"
    if new_text != text:
        inbox_path.write_text(new_text, encoding="utf-8")

    return results, new_text


def _resolve_and_apply(
    line: InboxLine,
    sources: list[SourceConfig],
    companies: list[CompanyConfig],
    dart_companies: list[KoreanCompanyConfig],
    investors: list[InvestorConfig],
    dirty: dict[str, bool],
    deps: InboxDeps,
) -> InboxResult:
    value = line.value
    assert value is not None

    if line.type in ("naver", "telegram", "telegram_private", *IB_INSIGHTS_TYPES):
        return _apply_source(line, value, sources, dirty)
    if line.type == "sec":
        return _apply_sec(line, value, companies, dirty, deps)
    if line.type == "dart":
        return _apply_dart(line, value, dart_companies, dirty, deps)
    if line.type == "investor":
        return _apply_investor(line, value, investors, dirty, deps)

    raise AssertionError(f"unreachable: unsupported type {line.type}")


def _apply_source(
    line: InboxLine, value: str, sources: list[SourceConfig], dirty: dict[str, bool]
) -> InboxResult:
    if line.type == "naver":
        entry = resolve_naver(value)
    elif line.type == "telegram_private":
        entry = resolve_telegram_private(value)
    elif line.type == "telegram":
        entry = resolve_telegram(value)
    else:
        assert line.type is not None
        entry = resolve_ib_insights(line.type, value)

    if any(existing.url == entry.url for existing in sources):
        message = "이미 sources.yaml에 존재"
        return InboxResult(line.line_no, "skipped_duplicate", line.type, entry.url, message)
    sources.append(entry)
    dirty["sources"] = True
    return InboxResult(line.line_no, "added", line.type, entry.id, "sources.yaml에 추가")


def _apply_sec(
    line: InboxLine,
    value: str,
    companies: list[CompanyConfig],
    dirty: dict[str, bool],
    deps: InboxDeps,
) -> InboxResult:
    if deps.sec_client is None:
        raise InboxResolveError("SEC_USER_AGENT 미설정으로 sec 타입 처리 불가")
    entry = resolve_sec(value, deps.sec_client, deps.sec_ticker_cache_path)
    if any(existing.ticker == entry.ticker for existing in companies):
        message = "이미 companies.yaml에 존재"
        return InboxResult(line.line_no, "skipped_duplicate", line.type, entry.ticker, message)
    companies.append(entry)
    dirty["companies"] = True
    return InboxResult(
        line.line_no,
        "added",
        line.type,
        entry.ticker,
        "companies.yaml에 추가 (외국민간발행인이면 filing_types를 20-F/6-K로 직접 수정)",
    )


def _apply_dart(
    line: InboxLine,
    value: str,
    dart_companies: list[KoreanCompanyConfig],
    dirty: dict[str, bool],
    deps: InboxDeps,
) -> InboxResult:
    if deps.dart_client is None or deps.dart_api_key is None or deps.dart_conn is None:
        raise InboxResolveError("DART_API_KEY 미설정으로 dart 타입 처리 불가")
    entry = resolve_dart(value, deps.dart_conn, deps.dart_client, deps.dart_api_key)
    if any(existing.ticker == entry.ticker for existing in dart_companies):
        message = "이미 dart_companies.yaml에 존재"
        return InboxResult(line.line_no, "skipped_duplicate", line.type, entry.ticker, message)
    dart_companies.append(entry)
    dirty["dart"] = True
    return InboxResult(line.line_no, "added", line.type, entry.ticker, "dart_companies.yaml에 추가")


def _apply_investor(
    line: InboxLine,
    value: str,
    investors: list[InvestorConfig],
    dirty: dict[str, bool],
    deps: InboxDeps,
) -> InboxResult:
    if deps.sec_client is None:
        raise InboxResolveError("SEC_USER_AGENT 미설정으로 investor 타입 처리 불가")
    entry = resolve_investor(value, line.extra, deps.sec_client)
    if any(existing.cik == entry.cik for existing in investors):
        message = "이미 investors.yaml에 존재"
        return InboxResult(line.line_no, "skipped_duplicate", line.type, entry.cik, message)
    investors.append(entry)
    dirty["investors"] = True
    return InboxResult(line.line_no, "added", line.type, entry.cik, "investors.yaml에 추가")
