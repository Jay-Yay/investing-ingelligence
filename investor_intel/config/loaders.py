from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from investor_intel.models.config import (
    AppSettingsYaml,
    CompanyConfig,
    GlobalScoringConfig,
    InvestorConfig,
    KoreanCompanyConfig,
    ScoringUniverseConfig,
    SectorScoringConfig,
    SourceConfig,
)
from investor_intel.models.portfolio import Portfolio


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def load_settings_yaml(path: Path) -> AppSettingsYaml:
    return AppSettingsYaml.model_validate(_load_yaml(path))


def load_sources_yaml(path: Path) -> list[SourceConfig]:
    data = _load_yaml(path)
    return [SourceConfig.model_validate(item) for item in data.get("sources", [])]


def load_companies_yaml(path: Path) -> list[CompanyConfig]:
    data = _load_yaml(path)
    return [CompanyConfig.model_validate(item) for item in data.get("companies", [])]


def load_investors_yaml(path: Path) -> list[InvestorConfig]:
    data = _load_yaml(path)
    return [InvestorConfig.model_validate(item) for item in data.get("investors", [])]


def load_dart_companies_yaml(path: Path) -> list[KoreanCompanyConfig]:
    data = _load_yaml(path)
    return [KoreanCompanyConfig.model_validate(item) for item in data.get("dart_companies", [])]


def load_portfolio_yaml(path: Path) -> Portfolio:
    return Portfolio.model_validate(_load_yaml(path))


def load_scoring_universe_yaml(path: Path) -> ScoringUniverseConfig:
    return ScoringUniverseConfig.model_validate(_load_yaml(path))


def load_global_scoring_yaml(path: Path) -> GlobalScoringConfig:
    return GlobalScoringConfig.model_validate(_load_yaml(path))


def load_sector_scoring_yaml(path: Path) -> SectorScoringConfig:
    return SectorScoringConfig.model_validate(_load_yaml(path))
