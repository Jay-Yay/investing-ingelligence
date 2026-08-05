from __future__ import annotations

from pydantic import BaseModel


class SourceConfig(BaseModel):
    id: str
    type: str
    name: str
    enabled: bool = True
    url: str
    author: str | None = None
    weight: float = 1.0
    collection_mode: str = "full"
    backfill_days: int = 365
    tags: list[str] = []


class CompanyConfig(BaseModel):
    ticker: str
    cik: str
    name: str
    filing_types: list[str]
    is_foreign_private_issuer: bool = False


class KoreanCompanyConfig(BaseModel):
    ticker: str
    corp_code: str | None = None
    name: str
    report_types: list[str] = ["A", "B"]


class InvestorConfig(BaseModel):
    id: str
    name: str
    fund_name: str
    cik: str
    related_essay_url: str | None = None


class AppSettingsYaml(BaseModel):
    vault_path: str = "./vault"
    timezone: str = "Asia/Seoul"
    daily_report_time: str = "09:00"


class ScoringUniverseTicker(BaseModel):
    ticker: str
    name: str
    sector: str
    country: str
    benchmarks: list[str] = []


class ScoringUniverseConfig(BaseModel):
    """스코어링 대상 종목 레지스트리 (config/scoring/universe.yaml).

    portfolio.yaml과 의도적으로 분리되어 있다 - average_cost/quantity 필드가 없다. 기업의
    투자 매력도 점수는 실제 매수원가와 무관해야 한다."""

    model_version: str
    timezone: str = "Asia/Seoul"
    base_currency: str = "KRW"
    horizons_months: list[int] = [6, 12, 24]
    short_term_windows_days: list[int] = [5, 20]
    mid_term_windows_days: list[int] = [60, 120]
    default_benchmarks: list[str] = []
    foreign_benchmarks: list[str] = []
    tickers: list[ScoringUniverseTicker] = []


class ScoreBands(BaseModel):
    strong_buy_candidate: float
    accumulate_candidate: float
    hold_watch: float
    reduce_review: float


class HysteresisConfig(BaseModel):
    entry_new_buy: float
    maintain_buy: float
    reduce_review: float
    sell_review: float
    cooldown_trading_days: int


class NewBuyRequirements(BaseModel):
    min_total_score: float
    min_confidence: float
    min_consecutive_score_increases: int
    min_secondary_confirmations: int


class HardGateDefinition(BaseModel):
    id: str
    description: str


class ConfidenceConfig(BaseModel):
    low_threshold: float = 0.50
    high_threshold: float = 0.80
    stale_penalty_per_feature: float = 0.03
    rumor_or_social_source_cap: float = 0.40


class GlobalScoringConfig(BaseModel):
    """공통 스코어링 기준 (config/scoring/global_scoring.yaml). 섹터 오버레이가 있으면
    SectorScoringConfig의 category_weights가 이 값을 완전히 대체한다."""

    model_version: str
    category_weights: dict[str, float]
    score_bands: ScoreBands
    hysteresis: HysteresisConfig
    new_buy_requirements: NewBuyRequirements
    secondary_confirmation_signals: list[str] = []
    hard_gates: list[HardGateDefinition] = []
    confidence: ConfidenceConfig = ConfidenceConfig()


class MetricSpec(BaseModel):
    kind: str
    bad: float | None = None
    good: float | None = None


class SectorTickerOverlay(BaseModel):
    name: str
    extra_features: list[str] = []
    benchmarks: list[str] = []


class SectorScoringConfig(BaseModel):
    """섹터별 오버레이 (예: config/scoring/sector_memory.yaml). universe.yaml의 sector 필드로
    매칭된 종목은 global_scoring.yaml 대신 이 설정을 적용받는다."""

    model_version: str
    sector: str
    category_weights: dict[str, float]
    extra_hard_gates: list[HardGateDefinition] = []
    features: dict[str, list[str]] = {}
    metric_specs: dict[str, MetricSpec] = {}
    tickers: dict[str, SectorTickerOverlay] = {}
