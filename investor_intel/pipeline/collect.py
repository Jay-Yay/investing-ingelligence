from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from investor_intel.collectors.base import CheckpointStore, CollectItem, Collector, CollectResult
from investor_intel.collectors.dart import DartCollector
from investor_intel.collectors.dart_client import DartClient
from investor_intel.collectors.dart_corp_code import resolve_corp_code
from investor_intel.collectors.essay import EssayCollector
from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.collectors.ib_insights import IB_INSIGHTS_SOURCES, IBInsightsCollector
from investor_intel.collectors.naver_blog import NaverBlogCollector
from investor_intel.collectors.naver_research import NaverResearchCollector
from investor_intel.collectors.naver_weekly_hot import NaverWeeklyHotCollector
from investor_intel.collectors.sec_client import SECClient
from investor_intel.collectors.sec_filings import SECFilingsCollector
from investor_intel.collectors.sec_thirteenf import ThirteenFCollector
from investor_intel.collectors.telegram import TelegramCollector
from investor_intel.config.loaders import (
    load_companies_yaml,
    load_dart_companies_yaml,
    load_investors_yaml,
    load_sources_yaml,
)
from investor_intel.config.settings import AppSettings
from investor_intel.models.common import ContentCaptureMode, SourceType
from investor_intel.models.source_document import AssetMention, ContentCapture, SourceDocument
from investor_intel.storage.content_hash import compute_content_hash, compute_stable_id
from investor_intel.storage.obsidian_repo import write_document
from investor_intel.storage.sqlite_index import find_duplicate, upsert_document


@dataclass
class PersistResult:
    count: int
    errors: list[str] = field(default_factory=list)


@dataclass
class SourceRunResult:
    source_id: str
    persisted: int
    errors: list[str] = field(default_factory=list)


def collect_item_to_source_document(
    item: CollectItem, source_type: SourceType, source_name: str
) -> tuple[SourceDocument, str]:
    content_hash = compute_content_hash(item.body_text)
    stable_id = compute_stable_id(
        source_type.value, source_name, item.source_specific_id, item.canonical_url
    )
    doc = SourceDocument(
        id=stable_id,
        source_type=source_type,
        source_name=source_name,
        author=item.author,
        title=item.title,
        source_url=item.canonical_url,
        source_specific_id=item.source_specific_id,
        published_at=item.published_at,
        collected_at=datetime.now(UTC),
        updated_at=item.updated_at,
        language=item.language,
        content_hash=content_hash,
        content_capture=ContentCapture(
            mode=ContentCaptureMode(item.content_capture_mode),
            reason=item.content_capture_reason,
        ),
        assets=[AssetMention(**asset) for asset in item.assets],
        companies=item.companies,
        themes=item.themes,
        document_type=item.document_type,
        filing_type=item.filing_type,
        reporting_period=item.reporting_period,
        accession_number=item.accession_number,
    )
    return doc, item.body_text


def persist_collect_result(
    result: CollectResult,
    source_type: SourceType,
    source_name: str,
    vault_path: Path,
    conn: sqlite3.Connection,
) -> PersistResult:
    count = 0
    errors: list[str] = []

    for item in result.items:
        try:
            doc, body = collect_item_to_source_document(item, source_type, source_name)

            existing_id = find_duplicate(
                conn,
                source_type=source_type.value,
                source_name=source_name,
                source_specific_id=item.source_specific_id,
                canonical_url=item.canonical_url,
                content_hash=doc.content_hash,
                title=item.title,
                author=item.author,
                published_at=item.published_at.isoformat(),
            )
            if existing_id is not None:
                doc = doc.model_copy(update={"id": existing_id})

            file_path = write_document(vault_path, doc, body)
            upsert_document(
                conn, doc, file_path=str(file_path), source_specific_id=item.source_specific_id
            )
            count += 1
        except Exception as exc:  # noqa: BLE001
            identifier = item.source_specific_id or item.canonical_url
            errors.append(f"{identifier}: {exc}")

    return PersistResult(count=count, errors=errors)


def run_collectors(
    entries: list[tuple[Collector, SourceType, str]],
    vault_path: Path,
    conn: sqlite3.Connection,
    backfill_days: int | None = None,
) -> list[SourceRunResult]:
    results: list[SourceRunResult] = []

    for collector, source_type, source_name in entries:
        errors: list[str] = []
        persisted = 0
        try:
            collect_result = (
                collector.backfill(backfill_days)
                if backfill_days is not None
                else collector.collect_incremental()
            )
            errors.extend(collect_result.errors)
            persist_result = persist_collect_result(
                collect_result, source_type, source_name, vault_path, conn
            )
            persisted = persist_result.count
            errors.extend(persist_result.errors)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

        results.append(
            SourceRunResult(source_id=collector.source_id, persisted=persisted, errors=errors)
        )

    return results


def build_collect_entries(
    config_dir: Path,
    settings: AppSettings,
    checkpoint_store: CheckpointStore,
    conn: sqlite3.Connection,
) -> tuple[list[tuple[Collector, SourceType, str]], list[str]]:
    entries: list[tuple[Collector, SourceType, str]] = []
    setup_errors: list[str] = []

    investors_path = config_dir / "investors.yaml"
    if investors_path.exists():
        investors = load_investors_yaml(investors_path)

        if settings.sec_user_agent:
            sec_client = SECClient(user_agent=settings.sec_user_agent)
            for investor in investors:
                thirteenf_collector = ThirteenFCollector(investor, sec_client, checkpoint_store)
                entries.append((thirteenf_collector, SourceType.SEC_13F, investor.id))
        else:
            setup_errors.append("investors.yaml 존재하지만 SEC_USER_AGENT 미설정 - 13F 수집 건너뜀")

        essayists = [investor for investor in investors if investor.related_essay_url]
        if essayists:
            essay_http_client = SimpleHttpClient()
            for investor in essayists:
                essay_collector = EssayCollector(
                    investor, essay_http_client, checkpoint_store, conn
                )
                entries.append((essay_collector, SourceType.ESSAY, investor.id))

    companies_path = config_dir / "companies.yaml"
    if companies_path.exists():
        if settings.sec_user_agent:
            sec_client = SECClient(user_agent=settings.sec_user_agent)
            for company in load_companies_yaml(companies_path):
                filings_collector = SECFilingsCollector(company, sec_client, checkpoint_store)
                entries.append((filings_collector, SourceType.SEC_FILING, company.ticker))
        else:
            setup_errors.append(
                "companies.yaml 존재하지만 SEC_USER_AGENT 미설정 - 공시 수집 건너뜀"
            )

    dart_companies_path = config_dir / "dart_companies.yaml"
    if dart_companies_path.exists():
        if settings.dart_api_key:
            dart_client = DartClient(api_key=settings.dart_api_key)
            for dart_company in load_dart_companies_yaml(dart_companies_path):
                if dart_company.corp_code is None:
                    resolved = resolve_corp_code(
                        conn,
                        dart_client,
                        settings.dart_api_key,
                        ticker=dart_company.ticker,
                        name=dart_company.name,
                    )
                    if resolved is None:
                        setup_errors.append(
                            f"{dart_company.ticker}({dart_company.name})의 DART corp_code를 "
                            "찾을 수 없음 - DART 수집 건너뜀"
                        )
                        continue
                    dart_company = dart_company.model_copy(update={"corp_code": resolved})

                dart_collector = DartCollector(
                    dart_company, dart_client, checkpoint_store, api_key=settings.dart_api_key
                )
                entries.append((dart_collector, SourceType.DART, dart_company.ticker))
        else:
            setup_errors.append(
                "dart_companies.yaml 존재하지만 DART_API_KEY 미설정 - DART 수집 건너뜀"
            )

    sources_path = config_dir / "sources.yaml"
    if sources_path.exists():
        http_client = SimpleHttpClient()
        for source in load_sources_yaml(sources_path):
            if not source.enabled:
                continue
            if source.type == "naver":
                naver_collector = NaverBlogCollector(source, http_client, checkpoint_store)
                entries.append((naver_collector, SourceType.NAVER, source.name))
            elif source.type == "telegram":
                telegram_collector = TelegramCollector(source, http_client, checkpoint_store)
                entries.append((telegram_collector, SourceType.TELEGRAM, source.name))
            elif source.type == "naver_research":
                naver_research_collector = NaverResearchCollector(
                    source, http_client, checkpoint_store
                )
                entries.append((naver_research_collector, SourceType.IB_INSIGHTS, source.name))
            elif source.type == "naver_weekly_hot":
                naver_weekly_hot_collector = NaverWeeklyHotCollector(
                    source, http_client, checkpoint_store
                )
                entries.append(
                    (naver_weekly_hot_collector, SourceType.IB_INSIGHTS, source.name)
                )
            elif source.type in IB_INSIGHTS_SOURCES:
                ib_source = IB_INSIGHTS_SOURCES[source.type]
                ib_collector = IBInsightsCollector(
                    source,
                    http_client,
                    checkpoint_store,
                    ib_source.index_url,
                    ib_source.parse_index,
                    base_url=ib_source.base_url,
                    pdf_link_finder=ib_source.pdf_link_finder,
                    language=ib_source.language,
                )
                entries.append((ib_collector, SourceType.IB_INSIGHTS, source.name))
            elif source.type == "telegram_private":
                if settings.telegram_api_id and settings.telegram_api_hash and (
                    settings.telegram_session
                ):
                    # lazy import: `telethon` is an optional extra, not a hard dependency of
                    # this module - only pay for it when a telegram_private source is configured
                    from investor_intel.collectors.telegram_private import (
                        TelethonPrivateChannelCollector,
                    )
                    from investor_intel.collectors.telethon_client import RealTelethonClient

                    telethon_client = RealTelethonClient(
                        session=settings.telegram_session,
                        api_id=int(settings.telegram_api_id),
                        api_hash=settings.telegram_api_hash,
                    )
                    telethon_collector = TelethonPrivateChannelCollector(
                        source, telethon_client, checkpoint_store
                    )
                    entries.append((telethon_collector, SourceType.TELEGRAM, source.name))
                else:
                    setup_errors.append(
                        f"{source.id}: TELEGRAM_API_ID/HASH/SESSION 미설정 - "
                        "비공개 채널 수집 건너뜀"
                    )

    return entries, setup_errors
