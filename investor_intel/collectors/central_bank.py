from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from investor_intel.collectors import central_bank_parser as parser
from investor_intel.collectors.base import CheckpointStore, CollectItem, CollectResult
from investor_intel.collectors.central_bank_document import render_central_bank_body
from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.collectors.pdf_extract import PdfExtractError, extract_pdf_text
from investor_intel.collectors.text_extract import truncate
from investor_intel.models.config import SourceConfig

CentralBankArticle = parser.CentralBankArticle
FetchArticlesFn = Callable[[SimpleHttpClient], list[CentralBankArticle]]
# HTML 상세페이지에서 본문을 뽑는 함수. PDF만 있는 소스(Fed/BOJ/BOK 회의록·성명서 다수)는
# article.pdf_url이 이미 있으므로 이 함수를 쓰지 않는다.
ExtractHtmlFn = Callable[[str], str | None]


@dataclass
class CentralBankSource:
    bank_label: str  # 문서 제목/본문에 쓰는 표기 (예: "Fed", "ECB", "BOK")
    country: str  # themes 태깅용 국가 코드 (US/EU/GB/JP/KR)
    doc_kind: str  # "statement" | "minutes"
    fetch_articles: FetchArticlesFn
    extract_html: ExtractHtmlFn | None = None
    language: str = "en"


def _current_and_previous_years() -> list[int]:
    current = datetime.now(UTC).year
    return [current, current - 1]


def _fetch_fed_statements(client: SimpleHttpClient) -> list[CentralBankArticle]:
    html = client.get_text(parser.FED_CALENDAR_URL)
    return parser.parse_fed_statements_index(html)


def _fetch_fed_minutes(client: SimpleHttpClient) -> list[CentralBankArticle]:
    html = client.get_text(parser.FED_CALENDAR_URL)
    return parser.parse_fed_minutes_index(html)


def _fetch_ecb_statements(client: SimpleHttpClient) -> list[CentralBankArticle]:
    index_html = client.get_text(parser.ECB_STATEMENTS_INDEX_URL)
    snippet_urls = parser.parse_ecb_snippet_urls(index_html, parser.ECB_STATEMENTS_INDEX_URL)
    years = {str(y) for y in _current_and_previous_years()}
    articles: list[CentralBankArticle] = []
    for url in snippet_urls:
        if not any(f"/{y}/html/" in url for y in years):
            continue
        articles.extend(parser.parse_ecb_statements_snippet(client.get_text(url)))
    # each snippet is independently sorted, but concatenation order across snippets follows
    # whatever order ECB's own data-snippets list happens to use (unverified) - re-sort so
    # collect_incremental's checkpoint logic doesn't depend on that assumption.
    return parser.dedupe_sort_desc(articles)


def _fetch_ecb_accounts(client: SimpleHttpClient) -> list[CentralBankArticle]:
    index_html = client.get_text(parser.ECB_ACCOUNTS_INDEX_URL)
    snippet_urls = parser.parse_ecb_snippet_urls(index_html, parser.ECB_ACCOUNTS_INDEX_URL)
    years = {str(y) for y in _current_and_previous_years()}
    articles: list[CentralBankArticle] = []
    for url in snippet_urls:
        if not any(f"/{y}/html/" in url for y in years):
            continue
        articles.extend(parser.parse_ecb_accounts_snippet(client.get_text(url)))
    return parser.dedupe_sort_desc(articles)


def _fetch_boe_index(client: SimpleHttpClient) -> list[CentralBankArticle]:
    html = client.get_text(parser.BOE_INDEX_URL)
    return parser.parse_boe_index(html)


def _fetch_boj_statements(client: SimpleHttpClient) -> list[CentralBankArticle]:
    articles: list[CentralBankArticle] = []
    for year in _current_and_previous_years():
        html = client.get_text(parser.boj_statements_index_url(year))
        articles.extend(parser.parse_boj_statements_index(html))
    # per-year pages are each sorted desc, but concatenating current-year-then-previous-year
    # only happens to stay globally sorted because of the loop order above - re-sort so that
    # invariant isn't load-bearing.
    return parser.dedupe_sort_desc(articles)


def _fetch_boj_minutes(client: SimpleHttpClient) -> list[CentralBankArticle]:
    articles: list[CentralBankArticle] = []
    for year in _current_and_previous_years():
        html = client.get_text(parser.boj_minutes_index_url(year))
        articles.extend(parser.parse_boj_minutes_index(html))
    return parser.dedupe_sort_desc(articles)


def _fetch_bok_statements(client: SimpleHttpClient) -> list[CentralBankArticle]:
    articles: list[CentralBankArticle] = []
    for year in _current_and_previous_years():
        html = client.get_text(parser.bok_meetings_index_url(year))
        articles.extend(parser.parse_bok_statements_index(html, year))
    return parser.dedupe_sort_desc(articles)


def _fetch_bok_minutes(client: SimpleHttpClient) -> list[CentralBankArticle]:
    articles: list[CentralBankArticle] = []
    for year in _current_and_previous_years():
        html = client.get_text(parser.bok_meetings_index_url(year))
        articles.extend(parser.parse_bok_minutes_index(html, year))
    return parser.dedupe_sort_desc(articles)


# source.type(sources.yaml) -> registry entry. PBOC는 robots.txt(Disallow: /)로 직접 스크래핑이
#막혀 있어 여기 없다 - collectors/central_bank_pboc_web.py(web_search 기반)에서 별도 처리.
CENTRAL_BANK_SOURCES: dict[str, CentralBankSource] = {
    "fed_statements": CentralBankSource(
        bank_label="Fed", country="US", doc_kind="statement",
        fetch_articles=_fetch_fed_statements, extract_html=parser.extract_fed_statement_text,
    ),
    "fed_minutes": CentralBankSource(
        bank_label="Fed", country="US", doc_kind="minutes", fetch_articles=_fetch_fed_minutes,
    ),
    "ecb_statements": CentralBankSource(
        bank_label="ECB", country="EU", doc_kind="statement",
        fetch_articles=_fetch_ecb_statements, extract_html=parser.extract_ecb_main_text,
    ),
    "ecb_accounts": CentralBankSource(
        bank_label="ECB", country="EU", doc_kind="minutes",
        fetch_articles=_fetch_ecb_accounts, extract_html=parser.extract_ecb_main_text,
    ),
    "boe_summary_minutes": CentralBankSource(
        bank_label="BOE", country="GB", doc_kind="minutes",
        fetch_articles=_fetch_boe_index, extract_html=parser.extract_boe_content_text,
    ),
    "boj_statements": CentralBankSource(
        bank_label="BOJ", country="JP", doc_kind="statement",
        fetch_articles=_fetch_boj_statements, extract_html=parser.extract_boj_text,
    ),
    "boj_minutes": CentralBankSource(
        bank_label="BOJ", country="JP", doc_kind="minutes",
        fetch_articles=_fetch_boj_minutes, extract_html=parser.extract_boj_text,
    ),
    "bok_statements": CentralBankSource(
        bank_label="BOK", country="KR", doc_kind="statement",
        fetch_articles=_fetch_bok_statements, language="ko",
    ),
    "bok_minutes": CentralBankSource(
        bank_label="BOK", country="KR", doc_kind="minutes",
        fetch_articles=_fetch_bok_minutes, language="ko",
    ),
}  # fmt: skip

_DOC_KIND_LABEL_KO = {"statement": "성명서", "minutes": "의사록"}


class CentralBankCollector:
    def __init__(
        self,
        source: SourceConfig,
        client: SimpleHttpClient,
        checkpoint_store: CheckpointStore,
        bank: CentralBankSource,
    ) -> None:
        self.source_id = source.id
        self._client = client
        self._checkpoint_store = checkpoint_store
        self._bank = bank

    def _resolve_body(self, article: CentralBankArticle) -> tuple[str, str, str | None]:
        # 정책성명은 몇 문단 수준이지만 회의록/계정(minutes/accounts)은 종종 수십 페이지에
        # 달하므로(ECB accounts 8만자+ 관측), dart/sec 공시와 동일하게 40,000자로 자른다 -
        # 안 그러면 다음 analyze 실행에서 이 문서 하나가 LLM 예산을 크게 잠식한다.
        if article.pdf_url:
            try:
                response = self._client.get(article.pdf_url)
            except Exception:  # noqa: BLE001
                response = None
            if response is not None and response.content.startswith(b"%PDF-"):
                try:
                    return truncate(extract_pdf_text(response.content)), "full", None
                except PdfExtractError:
                    pass
        elif self._bank.extract_html is not None:
            try:
                html = self._client.get_text(article.url)
                text = self._bank.extract_html(html)
                if text:
                    return truncate(text), "full", None
            except Exception:  # noqa: BLE001
                pass
        return (
            f"{article.title}\n\n{article.url}",
            "metadata_only",
            "본문 추출 실패 - 제목/링크만 캡처 (원문은 출처 링크 참고)",
        )

    def _build_item(self, article: CentralBankArticle) -> CollectItem:
        raw_body, mode, reason = self._resolve_body(article)
        doc_kind_ko = _DOC_KIND_LABEL_KO[self._bank.doc_kind]
        title = f"[{self._bank.bank_label} {doc_kind_ko}] {article.title}"
        source_url = article.pdf_url or article.url
        # ib_insights_document.py와 동일한 "## 핵심 주장/근거/반대 근거/..." 빈 섹션 템플릿을
        # 씌운다 - claims_splice.py는 이 헤더가 본문에 이미 있어야만 analyze가 추출한 claim을
        # 그 자리에 채워 넣는다(헤더가 없으면 원문 그대로 남는다).
        body = render_central_bank_body(title, source_url, raw_body, mode, reason)
        now = datetime.now(UTC)
        return CollectItem(
            source_specific_id=f"{self._bank.country}-{self._bank.doc_kind}-{article.meeting_date.isoformat()}",
            canonical_url=source_url,
            title=title,
            author=self._bank.bank_label,
            # 발행 시각을 회의일이 아니라 수집 시각으로 잡는다 - 회의록은 회의일로부터 몇 주
            # 뒤에야 공개되므로, published_at을 회의일로 두면 analyze의 "최근 N일" 팔로업
            # 창(pipeline/analyze.py)에 안 걸리고 조용히 누락된다.
            published_at=now,
            updated_at=None,
            language=self._bank.language,
            body_text=body,
            content_capture_mode=mode,
            content_capture_reason=reason,
            companies=[],
            themes=["macro", "central_bank", self._bank.country],
            document_type=f"central_bank_{self._bank.doc_kind}",
            reporting_period=article.meeting_date.isoformat(),
        )

    def _collect(
        self, articles_to_process: list[CentralBankArticle], checkpoint_id: str | None
    ) -> CollectResult:
        items: list[CollectItem] = []
        errors: list[str] = []
        for article in articles_to_process:
            try:
                items.append(self._build_item(article))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{article.url}: {exc}")

        if checkpoint_id is not None:
            self._checkpoint_store.record_success(self.source_id, last_seen_id=checkpoint_id)
        elif errors:
            self._checkpoint_store.record_failure(self.source_id)

        return CollectResult(
            source_id=self.source_id, success=not errors, items=items, errors=errors,
            new_count=len(items),
        )  # fmt: skip

    def backfill(self, days: int) -> CollectResult:
        del days  # 조회 가능한 인덱스 범위(과거 1~2년) 전체를 그냥 다 처리한다.
        all_articles = self._bank.fetch_articles(self._client)
        checkpoint_id = all_articles[0].url if all_articles else None
        result = self._collect(all_articles, checkpoint_id)
        state = self._checkpoint_store.get_state(self.source_id)
        state.backfill_completed = True
        self._checkpoint_store.save_state(state)
        return result

    def collect_incremental(self) -> CollectResult:
        all_articles = self._bank.fetch_articles(self._client)
        state = self._checkpoint_store.get_state(self.source_id)

        if state.last_seen_id is None:
            to_process = list(all_articles)
        else:
            to_process = []
            for article in all_articles:
                if article.url == state.last_seen_id:
                    break
                to_process.append(article)

        checkpoint_id = all_articles[0].url if all_articles else state.last_seen_id
        return self._collect(to_process, checkpoint_id)
