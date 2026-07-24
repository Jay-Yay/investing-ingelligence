from pathlib import Path

from investor_intel.config.loaders import (
    load_companies_yaml,
    load_dart_companies_yaml,
    load_investors_yaml,
    load_settings_yaml,
    load_sources_yaml,
)


def test_load_sources_yaml(tmp_path: Path) -> None:
    path = tmp_path / "sources.yaml"
    path.write_text(
        """sources:
  - id: naver_engineerinvestor
    type: naver
    name: engineerinvestor
    enabled: true
    url: https://m.blog.naver.com/engineerinvestor
    author: engineerinvestor
    weight: 1.0
    collection_mode: full
    backfill_days: 365
    tags: [blog, korean]
""",
        encoding="utf-8",
    )
    sources = load_sources_yaml(path)
    assert len(sources) == 1
    assert sources[0].id == "naver_engineerinvestor"
    assert sources[0].weight == 1.0


def test_load_investors_yaml(tmp_path: Path) -> None:
    path = tmp_path / "investors.yaml"
    path.write_text(
        """investors:
  - id: duquesne_family_office
    name: Stanley Druckenmiller
    fund_name: Duquesne Family Office LLC
    cik: "0001536411"
    related_essay_url: null
  - id: situational_awareness_lp
    name: Leopold Aschenbrenner
    fund_name: Situational Awareness LP
    cik: "0002045724"
    related_essay_url: https://situational-awareness.ai/
""",
        encoding="utf-8",
    )
    investors = load_investors_yaml(path)
    ciks = {i.cik for i in investors}
    assert ciks == {"0001536411", "0002045724"}


def test_load_companies_yaml(tmp_path: Path) -> None:
    path = tmp_path / "companies.yaml"
    path.write_text(
        """companies:
  - ticker: NBIS
    cik: "0001513845"
    name: Nebius Group
    filing_types: [20-F, 6-K]
    is_foreign_private_issuer: true
""",
        encoding="utf-8",
    )
    companies = load_companies_yaml(path)
    assert companies[0].filing_types == ["20-F", "6-K"]
    assert companies[0].is_foreign_private_issuer is True


def test_load_dart_companies_yaml(tmp_path: Path) -> None:
    path = tmp_path / "dart_companies.yaml"
    path.write_text(
        """dart_companies:
  - ticker: "005930"
    corp_code: "00126380"
    name: 삼성전자
    report_types: [A, B]
""",
        encoding="utf-8",
    )
    companies = load_dart_companies_yaml(path)
    assert companies[0].corp_code == "00126380"
    assert companies[0].report_types == ["A", "B"]


def test_load_dart_companies_yaml_default_report_types(tmp_path: Path) -> None:
    path = tmp_path / "dart_companies.yaml"
    path.write_text(
        """dart_companies:
  - ticker: "005930"
    corp_code: "00126380"
    name: 삼성전자
""",
        encoding="utf-8",
    )
    companies = load_dart_companies_yaml(path)
    assert companies[0].report_types == ["A", "B"]


def test_load_settings_yaml_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text("vault_path: ./vault\n", encoding="utf-8")
    settings = load_settings_yaml(path)
    assert settings.timezone == "Asia/Seoul"
    assert settings.vault_path == "./vault"
