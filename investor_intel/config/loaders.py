from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from investor_intel.models.config import (
    AppSettingsYaml,
    CompanyConfig,
    InvestorConfig,
    SourceConfig,
)


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
