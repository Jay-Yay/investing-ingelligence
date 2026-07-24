# SEC 13F Collector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a SEC EDGAR 13F-HR collector that fetches, parses, and quarter-over-quarter
compares institutional holdings for the two tracked investors (Duquesne Family Office LLC /
Stanley Druckenmiller, Situational Awareness LP / Leopold Aschenbrenner), producing
`CollectItem`s that conform to the `Collector` protocol built in the Core Foundation phase.

**Architecture:** A rate-limited, retrying SEC EDGAR HTTP client → a namespace-agnostic XML/JSON
parser (submissions feed + informationTable XML) → a pure holding-change comparator (new/sold
out/increased/decreased/held, portfolio weight, concentration) → a Markdown body renderer → a
`ThirteenFCollector` that implements `backfill(days)`/`collect_incremental()` per the
`Collector` protocol from `investor_intel/collectors/base.py`. The collector does **not** write
to the Obsidian vault or SQLite index itself — per the Core Foundation's `Collector` protocol,
it only returns `CollectResult(items: list[CollectItem])`; turning those into `SourceDocument`s,
deduping, and writing to storage is the shared pipeline built in a later phase
(`docs/superpowers/plans/2026-07-24-00-roadmap.md` plan 09, the `collect` CLI command).

**Tech Stack:** httpx (new dependency), respx (new dev dependency, for HTTP mocking),
`xml.etree.ElementTree` (stdlib, namespace-agnostic parsing), freezegun (existing dev
dependency, for deterministic "today" in day-window tests).

## Global Constraints

Inherited from the Core Foundation phase (still binding):
- Python >= 3.12 via `uv`. Package management via `pyproject.toml`.
- Validation: Pydantic. Structured logging; never log API keys or full raw document bodies.
- All internal datetimes are timezone-aware; KST conversions explicit where relevant.
- `ANTHROPIC_MODEL` env var, default `claude-sonnet-5` — never hardcode the model id elsewhere
  (not touched by this phase, but no code here may hardcode any model id either).
- No placeholders, no `TODO`s in shipped code.
- No live network calls in tests — use `respx` to mock all `httpx` traffic.

New constraints specific to this phase:
- CIKs (exact, zero-padded 10-digit form as already stored in `config/investors.yaml`):
  Duquesne Family Office LLC `0001536411`, Situational Awareness LP `0002045724`.
- SEC EDGAR requires an identifiable `User-Agent` header on every request
  (`SEC_USER_AGENT` env var, already wired into `AppSettings` from the Core Foundation phase).
  A client constructed with an empty/missing user agent must raise, not silently send requests.
- Real (official) SEC EDGAR rate limit is 10 req/s; this project caps at **2 req/s or less**,
  with exponential backoff on 429/5xx responses.
- Every 13F document body must include the fixed limitations disclosure (spec: point-in-time
  snapshot with filing lag; may not reflect current holdings; does not show short positions,
  cash, or all derivatives/private assets; a disappeared position does not imply a bearish
  view; put/call-flagged positions must not be mixed into common-stock interpretation; reported
  value alone must not be used to estimate total net exposure).
- MVP scope: only `form == "13F-HR"` is processed. 13F-HR/A amendments are explicitly out of
  scope for this phase (a documented limitation, not an oversight — reconciling amendments
  against an original filing is materially more complex and deferred).
- Ticker/FIGI mapping from CUSIP is out of scope for this phase (no data source for it exists
  yet) — holdings are identified by issuer name + CUSIP only; `CollectItem.assets` stays empty
  for 13F items until a later phase adds CUSIP/ticker mapping.
- `ThirteenFCollector` must not read from or write to the Obsidian vault or SQLite index itself.

---

### Task 1: `ThirteenFHolding`/`ThirteenFFiling`/`HoldingChange` models

**Files:**
- Create: `investor_intel/models/thirteenf.py`
- Test: `tests/test_models_thirteenf.py`

**Interfaces:**
- Consumes: nothing new (stdlib `datetime.date`, `enum.StrEnum`, `pydantic.BaseModel`).
- Produces: `VotingAuthority(sole, shared, none)`, `ThirteenFHolding(issuer, title_of_class,
  cusip, figi, value_usd_thousands, shares_or_principal_amount, shares_or_principal_type,
  put_call, investment_discretion, other_manager, voting_authority)`,
  `ThirteenFFiling(investor_id, cik, accession_number, form_type, filing_date,
  period_of_report, holdings)` with a `.total_value_usd_thousands` property,
  `HoldingChangeType(StrEnum)` with values `new/sold_out/increased/decreased/held`,
  `HoldingChange(cusip, issuer, change_type, previous_shares, current_shares,
  shares_change_pct, previous_value_usd_thousands, current_value_usd_thousands,
  value_change_usd_thousands, portfolio_weight_pct, put_call)`. These exact names/fields are
  relied on by every later task in this plan.

- [x] **Step 1: Write the failing test**

`tests/test_models_thirteenf.py`:
```python
from datetime import date

from investor_intel.models.thirteenf import (
    HoldingChange,
    HoldingChangeType,
    ThirteenFFiling,
    ThirteenFHolding,
    VotingAuthority,
)


def _make_holding(value: int, shares: int, put_call: str | None = None) -> ThirteenFHolding:
    return ThirteenFHolding(
        issuer="NVIDIA CORP",
        title_of_class="COM",
        cusip="67066G104",
        value_usd_thousands=value,
        shares_or_principal_amount=shares,
        shares_or_principal_type="SH",
        put_call=put_call,
        investment_discretion="SOLE",
        voting_authority=VotingAuthority(sole=shares, shared=0, none=0),
    )


def test_holding_defaults() -> None:
    holding = _make_holding(1000, 100)
    assert holding.figi is None
    assert holding.put_call is None
    assert holding.other_manager is None


def test_filing_total_value_sums_holdings() -> None:
    filing = ThirteenFFiling(
        investor_id="duquesne_family_office",
        cik="0001536411",
        accession_number="0001536411-24-000007",
        form_type="13F-HR",
        filing_date=date(2024, 5, 15),
        period_of_report=date(2024, 3, 31),
        holdings=[_make_holding(1000, 100), _make_holding(2000, 200)],
    )
    assert filing.total_value_usd_thousands == 3000


def test_holding_change_type_values() -> None:
    assert {t.value for t in HoldingChangeType} == {
        "new",
        "sold_out",
        "increased",
        "decreased",
        "held",
    }


def test_holding_change_construction() -> None:
    change = HoldingChange(
        cusip="67066G104",
        issuer="NVIDIA CORP",
        change_type=HoldingChangeType.INCREASED,
        previous_shares=100,
        current_shares=150,
        shares_change_pct=50.0,
        previous_value_usd_thousands=1000,
        current_value_usd_thousands=1500,
        value_change_usd_thousands=500,
        portfolio_weight_pct=12.5,
    )
    assert change.put_call is None
```

- [x] **Step 2: Run test to verify it fails**

```bash
export PATH="/opt/homebrew/bin:$PATH"
uv run pytest tests/test_models_thirteenf.py -v
```
Expected: FAIL — module does not exist.

- [x] **Step 3: Write the implementation**

`investor_intel/models/thirteenf.py`:
```python
from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel


class VotingAuthority(BaseModel):
    sole: int
    shared: int
    none: int


class ThirteenFHolding(BaseModel):
    issuer: str
    title_of_class: str
    cusip: str
    figi: str | None = None
    value_usd_thousands: int
    shares_or_principal_amount: int
    shares_or_principal_type: str
    put_call: str | None = None
    investment_discretion: str
    other_manager: str | None = None
    voting_authority: VotingAuthority


class ThirteenFFiling(BaseModel):
    investor_id: str
    cik: str
    accession_number: str
    form_type: str
    filing_date: date
    period_of_report: date
    holdings: list[ThirteenFHolding]

    @property
    def total_value_usd_thousands(self) -> int:
        return sum(h.value_usd_thousands for h in self.holdings)


class HoldingChangeType(StrEnum):
    NEW = "new"
    SOLD_OUT = "sold_out"
    INCREASED = "increased"
    DECREASED = "decreased"
    HELD = "held"


class HoldingChange(BaseModel):
    cusip: str
    issuer: str
    change_type: HoldingChangeType
    previous_shares: int | None = None
    current_shares: int | None = None
    shares_change_pct: float | None = None
    previous_value_usd_thousands: int | None = None
    current_value_usd_thousands: int | None = None
    value_change_usd_thousands: int | None = None
    portfolio_weight_pct: float | None = None
    put_call: str | None = None
```

- [x] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_models_thirteenf.py -v
```
Expected: `4 passed`.

- [x] **Step 5: Commit**

```bash
git add investor_intel/models/thirteenf.py tests/test_models_thirteenf.py
git commit -m "feat: add 13F holding/filing/change Pydantic models"
```

---

### Task 2: SEC EDGAR HTTP client

**Files:**
- Modify: `pyproject.toml` (add `httpx` runtime dep, `respx` dev dep via `uv add`)
- Create: `investor_intel/collectors/sec_client.py`
- Test: `tests/test_sec_client.py`

**Interfaces:**
- Consumes: `RateLimiter` from `investor_intel/collectors/base.py` (Core Foundation phase).
- Produces: `SECClientError(Exception)`, `SECClient(user_agent, rate_limiter=None,
  http_client=None)` with `.get_json(url) -> dict`, `.get_text(url) -> str`, `.close() -> None`.
  These exact names are relied on by Task 6's `ThirteenFCollector`.

- [x] **Step 1: Add dependencies**

```bash
export PATH="/opt/homebrew/bin:$PATH"
uv add httpx
uv add --dev respx
```
Expected: `pyproject.toml` and `uv.lock` updated; `uv run python -c "import httpx, respx"`
succeeds.

- [x] **Step 2: Write the failing test**

`tests/test_sec_client.py`:
```python
import httpx
import pytest
import respx

from investor_intel.collectors.sec_client import SECClient, SECClientError


def test_empty_user_agent_raises() -> None:
    with pytest.raises(ValueError):
        SECClient(user_agent="")


@respx.mock
def test_get_json_sends_user_agent_header() -> None:
    route = respx.get("https://data.sec.gov/test.json").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    client = SECClient(user_agent="Investor Intel test@example.com")
    result = client.get_json("https://data.sec.gov/test.json")
    client.close()

    assert result == {"ok": True}
    assert route.calls.last.request.headers["User-Agent"] == "Investor Intel test@example.com"


@respx.mock
def test_get_text_retries_on_429_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    route = respx.get("https://www.sec.gov/test.xml").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(200, text="<root/>"),
        ]
    )
    client = SECClient(user_agent="Investor Intel test@example.com")
    result = client.get_text("https://www.sec.gov/test.xml")
    client.close()

    assert result == "<root/>"
    assert route.call_count == 2


@respx.mock
def test_persistent_429_raises_after_max_retries(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    respx.get("https://www.sec.gov/always429.xml").mock(return_value=httpx.Response(429))
    client = SECClient(user_agent="Investor Intel test@example.com")
    with pytest.raises(SECClientError):
        client.get_text("https://www.sec.gov/always429.xml")
    client.close()


@respx.mock
def test_rate_limiter_acquire_called_per_request() -> None:
    calls: list[None] = []

    class SpyRateLimiter:
        def acquire(self) -> None:
            calls.append(None)

    respx.get("https://data.sec.gov/spy.json").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    client = SECClient(user_agent="Investor Intel test@example.com", rate_limiter=SpyRateLimiter())
    client.get_json("https://data.sec.gov/spy.json")
    client.close()

    assert len(calls) == 1
```

- [x] **Step 2b: Run test to verify it fails**

```bash
uv run pytest tests/test_sec_client.py -v
```
Expected: FAIL — module does not exist.

- [x] **Step 3: Write the implementation**

`investor_intel/collectors/sec_client.py`:
```python
from __future__ import annotations

import time
from typing import Protocol

import httpx

from investor_intel.collectors.base import RateLimiter

_MAX_RETRIES = 3
_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


class SECClientError(Exception):
    pass


class _RateLimiterProtocol(Protocol):
    def acquire(self) -> None: ...


class SECClient:
    def __init__(
        self,
        user_agent: str,
        rate_limiter: _RateLimiterProtocol | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not user_agent:
            raise ValueError("SEC EDGAR requires an identifiable User-Agent")
        self._user_agent = user_agent
        self._rate_limiter: _RateLimiterProtocol = rate_limiter or RateLimiter(max_per_second=2.0)
        self._client = http_client or httpx.Client(timeout=30.0)

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": self._user_agent}

    def _request(self, url: str) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            self._rate_limiter.acquire()
            response = self._client.get(url, headers=self._headers())
            if response.status_code not in _RETRY_STATUS_CODES:
                response.raise_for_status()
                return response
            last_exc = SECClientError(
                f"SEC EDGAR request to {url} failed with status {response.status_code}"
            )
            if attempt < _MAX_RETRIES:
                time.sleep(2 ** (attempt - 1))
        assert last_exc is not None
        raise last_exc

    def get_json(self, url: str) -> dict:
        return self._request(url).json()

    def get_text(self, url: str) -> str:
        return self._request(url).text

    def close(self) -> None:
        self._client.close()
```

- [x] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_sec_client.py -v
```
Expected: `5 passed`.

- [x] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock investor_intel/collectors/sec_client.py tests/test_sec_client.py
git commit -m "feat: add rate-limited retrying SEC EDGAR HTTP client"
```

---

### Task 3: Submissions/informationTable XML parsing

**Files:**
- Create: `investor_intel/collectors/thirteenf_parser.py`
- Create fixtures: `tests/fixtures/sec/submissions_1536411.json`,
  `tests/fixtures/sec/index_0001536411-24-000007.json`,
  `tests/fixtures/sec/form13fInfoTable_current.xml`,
  `tests/fixtures/sec/form13fInfoTable_previous.xml`
- Test: `tests/test_thirteenf_parser.py`

**Interfaces:**
- Consumes: `ThirteenFHolding`, `VotingAuthority` (Task 1).
- Produces: `FilingRef(accession_number, filing_date, period_of_report, form,
  primary_document)` (dataclass), `parse_submissions_filings(submissions: dict,
  forms: frozenset[str] = frozenset({"13F-HR"})) -> list[FilingRef]`,
  `parse_information_table_xml(xml_text: str) -> list[ThirteenFHolding]`,
  `list_xml_document_candidates(index_json: dict, exclude: str) -> list[str]`. These exact
  names/signatures are relied on by Task 6's `ThirteenFCollector`.

- [x] **Step 1: Write the fixtures**

`tests/fixtures/sec/submissions_1536411.json`:
```json
{
  "cik": "1536411",
  "name": "Duquesne Family Office LLC",
  "filings": {
    "recent": {
      "accessionNumber": [
        "0001536411-24-000007",
        "0001536411-23-000004",
        "0001536411-22-000002"
      ],
      "filingDate": ["2024-05-15", "2023-11-14", "2022-11-14"],
      "reportDate": ["2024-03-31", "2023-09-30", "2022-09-30"],
      "form": ["13F-HR", "13F-HR", "13F-HR"],
      "primaryDocument": ["primary_doc.xml", "primary_doc.xml", "primary_doc.xml"]
    }
  }
}
```

`tests/fixtures/sec/index_0001536411-24-000007.json`:
```json
{
  "directory": {
    "item": [
      {"name": "primary_doc.xml", "type": "text.xml", "size": "12345"},
      {"name": "form13fInfoTable.xml", "type": "text.xml", "size": "45678"},
      {"name": "0001536411-24-000007-index.htm", "type": "text.htm", "size": "3456"}
    ],
    "name": "/Archives/edgar/data/1536411/000153641124000007"
  }
}
```

`tests/fixtures/sec/form13fInfoTable_current.xml`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>NVIDIA CORP</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>67066G104</cusip>
    <value>1250000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>15000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority>
      <Sole>15000</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>
  <infoTable>
    <nameOfIssuer>TESLA INC</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>88160R101</cusip>
    <value>520000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>5000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <putCall>Call</putCall>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority>
      <Sole>5000</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>
  <infoTable>
    <nameOfIssuer>ALPHABET INC</nameOfIssuer>
    <titleOfClass>CL A</titleOfClass>
    <cusip>02079K305</cusip>
    <value>400000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>3000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority>
      <Sole>3000</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>
</informationTable>
```

`tests/fixtures/sec/form13fInfoTable_previous.xml`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>NVIDIA CORP</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>67066G104</cusip>
    <value>900000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>12000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority>
      <Sole>12000</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>
  <infoTable>
    <nameOfIssuer>MICROSOFT CORP</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>594918104</cusip>
    <value>750000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>18000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority>
      <Sole>18000</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>
  <infoTable>
    <nameOfIssuer>TESLA INC</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>88160R101</cusip>
    <value>500000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>5000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <putCall>Call</putCall>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority>
      <Sole>5000</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>
</informationTable>
```

- [x] **Step 2: Write the failing test**

`tests/test_thirteenf_parser.py`:
```python
import json
from pathlib import Path

import pytest

from investor_intel.collectors.thirteenf_parser import (
    list_xml_document_candidates,
    parse_information_table_xml,
    parse_submissions_filings,
)

FIXTURES = Path(__file__).parent / "fixtures" / "sec"


def test_parse_submissions_filters_to_13f_hr_only() -> None:
    data = json.loads((FIXTURES / "submissions_1536411.json").read_text(encoding="utf-8"))
    refs = parse_submissions_filings(data)
    assert len(refs) == 3
    assert refs[0].accession_number == "0001536411-24-000007"
    assert refs[0].filing_date.isoformat() == "2024-05-15"
    assert refs[0].period_of_report.isoformat() == "2024-03-31"
    assert refs[0].form == "13F-HR"
    assert refs[0].primary_document == "primary_doc.xml"


def test_parse_submissions_excludes_other_forms() -> None:
    data = json.loads((FIXTURES / "submissions_1536411.json").read_text(encoding="utf-8"))
    data["filings"]["recent"]["form"][0] = "13F-HR/A"
    refs = parse_submissions_filings(data)
    assert len(refs) == 2
    assert all(r.form == "13F-HR" for r in refs)


def test_parse_information_table_current() -> None:
    xml_text = (FIXTURES / "form13fInfoTable_current.xml").read_text(encoding="utf-8")
    holdings = parse_information_table_xml(xml_text)
    assert len(holdings) == 3

    nvda = next(h for h in holdings if h.cusip == "67066G104")
    assert nvda.issuer == "NVIDIA CORP"
    assert nvda.value_usd_thousands == 1250000
    assert nvda.shares_or_principal_amount == 15000
    assert nvda.put_call is None

    tsla = next(h for h in holdings if h.cusip == "88160R101")
    assert tsla.put_call == "Call"
    assert tsla.voting_authority.sole == 5000


def test_parse_information_table_rejects_wrong_root() -> None:
    with pytest.raises(ValueError):
        parse_information_table_xml("<notInformationTable/>")


def test_list_xml_document_candidates_excludes_primary() -> None:
    index_json = json.loads(
        (FIXTURES / "index_0001536411-24-000007.json").read_text(encoding="utf-8")
    )
    candidates = list_xml_document_candidates(index_json, exclude="primary_doc.xml")
    assert candidates == ["form13fInfoTable.xml"]
```

- [x] **Step 2b: Run test to verify it fails**

```bash
uv run pytest tests/test_thirteenf_parser.py -v
```
Expected: FAIL — module does not exist.

- [x] **Step 3: Write the implementation**

`investor_intel/collectors/thirteenf_parser.py`:
```python
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from typing import Any

from investor_intel.models.thirteenf import ThirteenFHolding, VotingAuthority


@dataclass
class FilingRef:
    accession_number: str
    filing_date: date
    period_of_report: date
    form: str
    primary_document: str


def parse_submissions_filings(
    submissions: dict[str, Any], forms: frozenset[str] = frozenset({"13F-HR"})
) -> list[FilingRef]:
    recent = submissions["filings"]["recent"]
    refs: list[FilingRef] = []
    for i, form in enumerate(recent["form"]):
        if form not in forms:
            continue
        refs.append(
            FilingRef(
                accession_number=recent["accessionNumber"][i],
                filing_date=date.fromisoformat(recent["filingDate"][i]),
                period_of_report=date.fromisoformat(recent["reportDate"][i]),
                form=form,
                primary_document=recent["primaryDocument"][i],
            )
        )
    return refs


def _local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _find_child(parent: ET.Element, name: str) -> ET.Element | None:
    for child in parent:
        if _local_tag(child) == name:
            return child
    return None


def _find_child_text(parent: ET.Element, name: str) -> str | None:
    child = _find_child(parent, name)
    return child.text if child is not None else None


def parse_information_table_xml(xml_text: str) -> list[ThirteenFHolding]:
    root = ET.fromstring(xml_text)
    if _local_tag(root) != "informationTable":
        raise ValueError("not an informationTable document")

    holdings: list[ThirteenFHolding] = []
    for info_table in root:
        if _local_tag(info_table) != "infoTable":
            continue

        shrs_elem = _find_child(info_table, "shrsOrPrnAmt")
        if shrs_elem is None:
            raise ValueError("infoTable missing shrsOrPrnAmt")
        shares_amount = int(_find_child_text(shrs_elem, "sshPrnamt") or "0")
        shares_type = _find_child_text(shrs_elem, "sshPrnamtType") or ""

        voting_elem = _find_child(info_table, "votingAuthority")
        if voting_elem is None:
            raise ValueError("infoTable missing votingAuthority")
        voting_authority = VotingAuthority(
            sole=int(_find_child_text(voting_elem, "Sole") or "0"),
            shared=int(_find_child_text(voting_elem, "Shared") or "0"),
            none=int(_find_child_text(voting_elem, "None") or "0"),
        )

        holdings.append(
            ThirteenFHolding(
                issuer=_find_child_text(info_table, "nameOfIssuer") or "",
                title_of_class=_find_child_text(info_table, "titleOfClass") or "",
                cusip=_find_child_text(info_table, "cusip") or "",
                value_usd_thousands=int(_find_child_text(info_table, "value") or "0"),
                shares_or_principal_amount=shares_amount,
                shares_or_principal_type=shares_type,
                put_call=_find_child_text(info_table, "putCall"),
                investment_discretion=_find_child_text(info_table, "investmentDiscretion") or "",
                other_manager=_find_child_text(info_table, "otherManager"),
                voting_authority=voting_authority,
            )
        )
    return holdings


def list_xml_document_candidates(index_json: dict[str, Any], exclude: str) -> list[str]:
    items = index_json.get("directory", {}).get("item", [])
    return [
        item["name"]
        for item in items
        if item["name"].lower().endswith(".xml") and item["name"] != exclude
    ]
```

- [x] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_thirteenf_parser.py -v
```
Expected: `5 passed`.

- [x] **Step 5: Commit**

```bash
git add investor_intel/collectors/thirteenf_parser.py tests/test_thirteenf_parser.py tests/fixtures/sec
git commit -m "feat: add SEC submissions and 13F informationTable XML parsing"
```

---

### Task 4: Holding-change computation (new/sold-out/increased/decreased/held)

**Files:**
- Create: `investor_intel/collectors/thirteenf_changes.py`
- Test: `tests/test_thirteenf_changes.py`

**Interfaces:**
- Consumes: `ThirteenFHolding`, `HoldingChange`, `HoldingChangeType`, `VotingAuthority` (Task 1).
- Produces: `compute_holding_changes(previous_holdings: list[ThirteenFHolding] | None,
  current_holdings: list[ThirteenFHolding]) -> list[HoldingChange]`,
  `top_holdings(holdings: list[ThirteenFHolding], n: int = 10) -> list[ThirteenFHolding]`,
  `concentration_ratio(holdings: list[ThirteenFHolding], top_n: int = 5) -> float`. Relied on
  by Task 5 (rendering) and Task 6 (collector).

- [x] **Step 1: Write the failing test**

`tests/test_thirteenf_changes.py`:
```python
from investor_intel.collectors.thirteenf_changes import (
    compute_holding_changes,
    concentration_ratio,
    top_holdings,
)
from investor_intel.models.thirteenf import HoldingChangeType, ThirteenFHolding, VotingAuthority


def _holding(cusip: str, issuer: str, value: int, shares: int, put_call: str | None = None) -> ThirteenFHolding:
    return ThirteenFHolding(
        issuer=issuer,
        title_of_class="COM",
        cusip=cusip,
        value_usd_thousands=value,
        shares_or_principal_amount=shares,
        shares_or_principal_type="SH",
        put_call=put_call,
        investment_discretion="SOLE",
        voting_authority=VotingAuthority(sole=shares, shared=0, none=0),
    )


def test_new_holding_when_absent_from_previous() -> None:
    current = [_holding("AAA", "Alpha Co", 1000, 100)]
    changes = compute_holding_changes(None, current)
    assert len(changes) == 1
    assert changes[0].change_type == HoldingChangeType.NEW
    assert changes[0].current_shares == 100
    assert changes[0].previous_shares is None
    assert changes[0].portfolio_weight_pct == 100.0


def test_sold_out_when_absent_from_current() -> None:
    previous = [_holding("AAA", "Alpha Co", 1000, 100)]
    changes = compute_holding_changes(previous, [])
    assert len(changes) == 1
    assert changes[0].change_type == HoldingChangeType.SOLD_OUT
    assert changes[0].previous_shares == 100
    assert changes[0].current_shares is None


def test_increased_when_shares_go_up() -> None:
    previous = [_holding("AAA", "Alpha Co", 1000, 100)]
    current = [_holding("AAA", "Alpha Co", 1500, 150)]
    changes = compute_holding_changes(previous, current)
    assert changes[0].change_type == HoldingChangeType.INCREASED
    assert changes[0].shares_change_pct == 50.0
    assert changes[0].value_change_usd_thousands == 500


def test_decreased_when_shares_go_down() -> None:
    previous = [_holding("AAA", "Alpha Co", 1000, 100)]
    current = [_holding("AAA", "Alpha Co", 500, 50)]
    changes = compute_holding_changes(previous, current)
    assert changes[0].change_type == HoldingChangeType.DECREASED
    assert changes[0].shares_change_pct == -50.0


def test_held_when_shares_unchanged() -> None:
    previous = [_holding("AAA", "Alpha Co", 1000, 100)]
    current = [_holding("AAA", "Alpha Co", 1100, 100)]
    changes = compute_holding_changes(previous, current)
    assert changes[0].change_type == HoldingChangeType.HELD
    assert changes[0].shares_change_pct == 0.0


def test_put_call_flag_carried_through() -> None:
    previous = [_holding("AAA", "Alpha Co", 1000, 100, put_call="Call")]
    current = [_holding("AAA", "Alpha Co", 1000, 100, put_call="Call")]
    changes = compute_holding_changes(previous, current)
    assert changes[0].put_call == "Call"


def test_top_holdings_sorted_by_value_desc() -> None:
    holdings = [
        _holding("AAA", "Alpha", 100, 10),
        _holding("BBB", "Beta", 300, 30),
        _holding("CCC", "Gamma", 200, 20),
    ]
    top = top_holdings(holdings, n=2)
    assert [h.cusip for h in top] == ["BBB", "CCC"]


def test_concentration_ratio_top_n() -> None:
    holdings = [
        _holding("AAA", "Alpha", 600, 10),
        _holding("BBB", "Beta", 300, 30),
        _holding("CCC", "Gamma", 100, 20),
    ]
    assert concentration_ratio(holdings, top_n=1) == 60.0
    assert concentration_ratio(holdings, top_n=2) == 90.0


def test_concentration_ratio_empty_holdings_is_zero() -> None:
    assert concentration_ratio([], top_n=5) == 0.0
```

- [x] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_thirteenf_changes.py -v
```
Expected: FAIL — module does not exist.

- [x] **Step 3: Write the implementation**

`investor_intel/collectors/thirteenf_changes.py`:
```python
from __future__ import annotations

from investor_intel.models.thirteenf import HoldingChange, HoldingChangeType, ThirteenFHolding


def compute_holding_changes(
    previous_holdings: list[ThirteenFHolding] | None,
    current_holdings: list[ThirteenFHolding],
) -> list[HoldingChange]:
    previous_by_cusip = {h.cusip: h for h in (previous_holdings or [])}
    current_by_cusip = {h.cusip: h for h in current_holdings}
    current_total = sum(h.value_usd_thousands for h in current_holdings) or 1

    changes: list[HoldingChange] = []

    for cusip, current in current_by_cusip.items():
        previous = previous_by_cusip.get(cusip)
        portfolio_weight = round(current.value_usd_thousands / current_total * 100, 2)

        if previous is None:
            changes.append(
                HoldingChange(
                    cusip=cusip,
                    issuer=current.issuer,
                    change_type=HoldingChangeType.NEW,
                    current_shares=current.shares_or_principal_amount,
                    current_value_usd_thousands=current.value_usd_thousands,
                    portfolio_weight_pct=portfolio_weight,
                    put_call=current.put_call,
                )
            )
            continue

        shares_change_pct = None
        if previous.shares_or_principal_amount != 0:
            shares_change_pct = round(
                (current.shares_or_principal_amount - previous.shares_or_principal_amount)
                / previous.shares_or_principal_amount
                * 100,
                2,
            )

        if current.shares_or_principal_amount > previous.shares_or_principal_amount:
            change_type = HoldingChangeType.INCREASED
        elif current.shares_or_principal_amount < previous.shares_or_principal_amount:
            change_type = HoldingChangeType.DECREASED
        else:
            change_type = HoldingChangeType.HELD

        changes.append(
            HoldingChange(
                cusip=cusip,
                issuer=current.issuer,
                change_type=change_type,
                previous_shares=previous.shares_or_principal_amount,
                current_shares=current.shares_or_principal_amount,
                shares_change_pct=shares_change_pct,
                previous_value_usd_thousands=previous.value_usd_thousands,
                current_value_usd_thousands=current.value_usd_thousands,
                value_change_usd_thousands=(
                    current.value_usd_thousands - previous.value_usd_thousands
                ),
                portfolio_weight_pct=portfolio_weight,
                put_call=current.put_call,
            )
        )

    for cusip, previous in previous_by_cusip.items():
        if cusip in current_by_cusip:
            continue
        changes.append(
            HoldingChange(
                cusip=cusip,
                issuer=previous.issuer,
                change_type=HoldingChangeType.SOLD_OUT,
                previous_shares=previous.shares_or_principal_amount,
                previous_value_usd_thousands=previous.value_usd_thousands,
                put_call=previous.put_call,
            )
        )

    return changes


def top_holdings(holdings: list[ThirteenFHolding], n: int = 10) -> list[ThirteenFHolding]:
    return sorted(holdings, key=lambda h: h.value_usd_thousands, reverse=True)[:n]


def concentration_ratio(holdings: list[ThirteenFHolding], top_n: int = 5) -> float:
    total = sum(h.value_usd_thousands for h in holdings)
    if total == 0:
        return 0.0
    top_total = sum(h.value_usd_thousands for h in top_holdings(holdings, top_n))
    return round(top_total / total * 100, 2)
```

- [x] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_thirteenf_changes.py -v
```
Expected: `9 passed`.

- [x] **Step 5: Commit**

```bash
git add investor_intel/collectors/thirteenf_changes.py tests/test_thirteenf_changes.py
git commit -m "feat: add 13F holding-change comparator and concentration metrics"
```

---

### Task 5: Markdown body rendering

**Files:**
- Create: `investor_intel/collectors/thirteenf_document.py`
- Test: `tests/test_thirteenf_document.py`

**Interfaces:**
- Consumes: `ThirteenFFiling`, `HoldingChange` (Task 1); `top_holdings`, `concentration_ratio`
  (Task 4); `InvestorConfig` (Core Foundation, `investor_intel/models/config.py`).
- Produces: `THIRTEENF_LIMITATIONS_NOTE: str`, `render_thirteenf_body(filing: ThirteenFFiling,
  investor: InvestorConfig, changes: list[HoldingChange], canonical_url: str) -> str`. Relied
  on by Task 6's `ThirteenFCollector` to build `CollectItem.body_text`.

- [x] **Step 1: Write the failing test**

`tests/test_thirteenf_document.py`:
```python
from datetime import date

from investor_intel.collectors.thirteenf_changes import compute_holding_changes
from investor_intel.collectors.thirteenf_document import (
    THIRTEENF_LIMITATIONS_NOTE,
    render_thirteenf_body,
)
from investor_intel.models.config import InvestorConfig
from investor_intel.models.thirteenf import ThirteenFFiling, ThirteenFHolding, VotingAuthority


def _holding(cusip: str, issuer: str, value: int, shares: int) -> ThirteenFHolding:
    return ThirteenFHolding(
        issuer=issuer,
        title_of_class="COM",
        cusip=cusip,
        value_usd_thousands=value,
        shares_or_principal_amount=shares,
        shares_or_principal_type="SH",
        investment_discretion="SOLE",
        voting_authority=VotingAuthority(sole=shares, shared=0, none=0),
    )


def _investor() -> InvestorConfig:
    return InvestorConfig(
        id="duquesne_family_office",
        name="Stanley Druckenmiller",
        fund_name="Duquesne Family Office LLC",
        cik="0001536411",
    )


def test_render_includes_all_required_sections() -> None:
    filing = ThirteenFFiling(
        investor_id="duquesne_family_office",
        cik="0001536411",
        accession_number="0001536411-24-000007",
        form_type="13F-HR",
        filing_date=date(2024, 5, 15),
        period_of_report=date(2024, 3, 31),
        holdings=[_holding("AAA", "Alpha Co", 1000, 100)],
    )
    changes = compute_holding_changes(None, filing.holdings)
    body = render_thirteenf_body(
        filing, _investor(), changes, "https://www.sec.gov/Archives/edgar/data/1536411/x/x-index.htm"
    )

    for section in (
        "## 원문",
        "## 13F 해석 시 유의사항",
        "## 핵심 주장",
        "## 근거",
        "## 반대 근거",
        "## 언급 자산",
        "## 포트폴리오 관련성",
        "## 출처",
    ):
        assert section in body

    assert "Alpha Co" in body
    assert "0001536411-24-000007" in body
    assert "2024-03-31" in body
    assert "https://www.sec.gov/Archives/edgar/data/1536411/x/x-index.htm" in body


def test_render_includes_limitations_note_verbatim() -> None:
    filing = ThirteenFFiling(
        investor_id="duquesne_family_office",
        cik="0001536411",
        accession_number="0001536411-24-000007",
        form_type="13F-HR",
        filing_date=date(2024, 5, 15),
        period_of_report=date(2024, 3, 31),
        holdings=[],
    )
    body = render_thirteenf_body(filing, _investor(), [], "https://example.com")
    assert THIRTEENF_LIMITATIONS_NOTE in body


def test_render_flags_put_call_positions_distinctly() -> None:
    holding = _holding("AAA", "Alpha Co", 1000, 100)
    holding.put_call = "Call"
    filing = ThirteenFFiling(
        investor_id="duquesne_family_office",
        cik="0001536411",
        accession_number="0001536411-24-000007",
        form_type="13F-HR",
        filing_date=date(2024, 5, 15),
        period_of_report=date(2024, 3, 31),
        holdings=[holding],
    )
    changes = compute_holding_changes(None, filing.holdings)
    body = render_thirteenf_body(filing, _investor(), changes, "https://example.com")
    assert "Call" in body
```

- [x] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_thirteenf_document.py -v
```
Expected: FAIL — module does not exist.

- [x] **Step 3: Write the implementation**

`investor_intel/collectors/thirteenf_document.py`:
```python
from __future__ import annotations

from investor_intel.collectors.thirteenf_changes import concentration_ratio, top_holdings
from investor_intel.models.config import InvestorConfig
from investor_intel.models.thirteenf import HoldingChange, ThirteenFFiling

THIRTEENF_LIMITATIONS_NOTE = (
    "- 13F은 분기 말 기준 스냅샷이며 제출까지 최대 45일의 시차가 존재한다.\n"
    "- 현재 실제 보유 상태와 다를 수 있다.\n"
    "- 공매도, 현금, 일부 파생상품 및 비공개 자산은 13F에 나타나지 않는다.\n"
    "- 종목이 사라졌다고 해서 반드시 부정적 전망을 의미하지 않는다.\n"
    "- put/call 정보가 있는 포지션은 보통주 보유와 혼합해서 해석하지 않는다.\n"
    "- 보고 가치만으로 투자자의 전체 순노출을 추정하지 않는다.\n"
)


def _render_holdings_table(
    rows: list[tuple[object, HoldingChange]],
) -> str:
    lines = [
        "| 종목 | CUSIP | 수량 | 보고가치($천) | 비중 | 변화 | Put/Call |",
        "| --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for holding, change in rows:
        weight = (
            f"{change.portfolio_weight_pct:.2f}%"
            if change.portfolio_weight_pct is not None
            else "-"
        )
        lines.append(
            f"| {holding.issuer} | {holding.cusip} | {holding.shares_or_principal_amount:,} "
            f"| {holding.value_usd_thousands:,} | {weight} | {change.change_type.value} "
            f"| {holding.put_call or '-'} |"
        )
    return "\n".join(lines)


def render_thirteenf_body(
    filing: ThirteenFFiling,
    investor: InvestorConfig,
    changes: list[HoldingChange],
    canonical_url: str,
) -> str:
    holdings_by_cusip = {h.cusip: h for h in filing.holdings}
    rows = [(holdings_by_cusip[c.cusip], c) for c in changes if c.cusip in holdings_by_cusip]
    top = top_holdings(filing.holdings, n=10)
    concentration = concentration_ratio(filing.holdings, top_n=5)

    new_count = sum(1 for c in changes if c.change_type.value == "new")
    sold_out_count = sum(1 for c in changes if c.change_type.value == "sold_out")

    sections = [
        "## 원문",
        "",
        f"{investor.fund_name} ({investor.name}) {filing.form_type} — "
        f"보고 기준일 {filing.period_of_report.isoformat()}, "
        f"제출일 {filing.filing_date.isoformat()}, "
        f"accession {filing.accession_number}",
        "",
        f"총 보고 가치: {filing.total_value_usd_thousands:,}천 달러 / "
        f"보유 종목 수: {len(filing.holdings)} / "
        f"상위 5종목 집중도: {concentration:.2f}%",
        "",
        _render_holdings_table(rows),
        "",
        "## 13F 해석 시 유의사항",
        "",
        THIRTEENF_LIMITATIONS_NOTE,
        "## 핵심 주장",
        "",
        "## 근거",
        "",
        "## 반대 근거",
        "",
        "## 언급 자산",
        "",
        f"신규 {new_count}종목, 전량 매도 {sold_out_count}종목. "
        f"상위 보유: {', '.join(h.issuer for h in top[:5])}",
        "",
        "## 포트폴리오 관련성",
        "",
        "## 출처",
        "",
        f"- [원문]({canonical_url})",
        "",
    ]
    return "\n".join(sections)
```

- [x] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_thirteenf_document.py -v
```
Expected: `3 passed`.

- [x] **Step 5: Commit**

```bash
git add investor_intel/collectors/thirteenf_document.py tests/test_thirteenf_document.py
git commit -m "feat: add 13F Markdown body renderer with limitations disclosure"
```

---

### Task 6: `ThirteenFCollector`

**Files:**
- Create: `investor_intel/collectors/sec_thirteenf.py`
- Create fixtures: `tests/fixtures/sec/index_0001536411-23-000004.json` (mirrors the
  structure of `index_0001536411-24-000007.json` but for the previous-quarter accession)
- Test: `tests/test_sec_thirteenf.py`

**Interfaces:**
- Consumes: `CheckpointStore`, `CollectItem`, `CollectResult` (Core Foundation
  `investor_intel/collectors/base.py`); `SECClient` (Task 2); `FilingRef`,
  `list_xml_document_candidates`, `parse_information_table_xml`, `parse_submissions_filings`
  (Task 3); `compute_holding_changes` (Task 4); `render_thirteenf_body` (Task 5);
  `InvestorConfig` (Core Foundation).
- Produces: `ThirteenFCollector(investor: InvestorConfig, client: SECClient,
  checkpoint_store: CheckpointStore)` with `.source_id: str`, `.backfill(days: int) ->
  CollectResult`, `.collect_incremental() -> CollectResult` — conforms to the `Collector`
  protocol from the Core Foundation phase.

- [x] **Step 1: Write the fixture**

`tests/fixtures/sec/index_0001536411-23-000004.json`:
```json
{
  "directory": {
    "item": [
      {"name": "primary_doc.xml", "type": "text.xml", "size": "12000"},
      {"name": "form13fInfoTable.xml", "type": "text.xml", "size": "40000"},
      {"name": "0001536411-23-000004-index.htm", "type": "text.htm", "size": "3400"}
    ],
    "name": "/Archives/edgar/data/1536411/000153641123000004"
  }
}
```

- [x] **Step 2: Write the failing test**

`tests/test_sec_thirteenf.py`:
```python
from pathlib import Path

import httpx
import respx
from freezegun import freeze_time

from investor_intel.collectors.base import CheckpointStore
from investor_intel.collectors.sec_client import SECClient
from investor_intel.collectors.sec_thirteenf import ThirteenFCollector
from investor_intel.models.config import InvestorConfig
from investor_intel.storage.sqlite_index import connect, init_db

FIXTURES = Path(__file__).parent / "fixtures" / "sec"


def _investor() -> InvestorConfig:
    return InvestorConfig(
        id="duquesne_family_office",
        name="Stanley Druckenmiller",
        fund_name="Duquesne Family Office LLC",
        cik="0001536411",
    )


def _mock_sec_routes() -> None:
    respx.get("https://data.sec.gov/submissions/CIK0001536411.json").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "submissions_1536411.json").read_text(encoding="utf-8")
        )
    )
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/1536411/000153641124000007/index.json"
    ).mock(
        return_value=httpx.Response(
            200,
            text=(FIXTURES / "index_0001536411-24-000007.json").read_text(encoding="utf-8"),
        )
    )
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/1536411/000153641124000007/form13fInfoTable.xml"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "form13fInfoTable_current.xml").read_text(encoding="utf-8")
        )
    )
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/1536411/000153641123000004/index.json"
    ).mock(
        return_value=httpx.Response(
            200,
            text=(FIXTURES / "index_0001536411-23-000004.json").read_text(encoding="utf-8"),
        )
    )
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/1536411/000153641123000004/form13fInfoTable.xml"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "form13fInfoTable_previous.xml").read_text(encoding="utf-8")
        )
    )


@respx.mock
@freeze_time("2024-06-01")
def test_backfill_returns_only_in_window_filing_with_computed_changes(tmp_path) -> None:
    _mock_sec_routes()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SECClient(user_agent="Investor Intel test@example.com")
    collector = ThirteenFCollector(_investor(), client, CheckpointStore(conn))

    result = collector.backfill(days=180)
    client.close()

    assert result.success
    assert result.new_count == 1
    item = result.items[0]
    assert item.accession_number == "0001536411-24-000007"
    assert item.reporting_period == "2024-03-31"
    assert item.filing_type == "13F-HR"
    assert "ALPHABET INC" in item.body_text
    assert "new" in item.body_text  # ALPHABET is NEW vs previous quarter
    assert "sold_out" in item.body_text  # MICROSOFT sold out vs previous quarter
    assert "increased" in item.body_text  # NVIDIA increased vs previous quarter


@respx.mock
@freeze_time("2024-06-01")
def test_backfill_caches_previous_filing_fetch(tmp_path) -> None:
    _mock_sec_routes()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SECClient(user_agent="Investor Intel test@example.com")
    collector = ThirteenFCollector(_investor(), client, CheckpointStore(conn))

    collector.backfill(days=180)
    client.close()

    previous_xml_route = respx.get(
        "https://www.sec.gov/Archives/edgar/data/1536411/000153641123000004/form13fInfoTable.xml"
    )
    assert previous_xml_route.call_count == 1


@respx.mock
@freeze_time("2024-06-01")
def test_collect_incremental_advances_checkpoint_and_is_idempotent(tmp_path) -> None:
    _mock_sec_routes()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SECClient(user_agent="Investor Intel test@example.com")
    checkpoint_store = CheckpointStore(conn)

    first_collector = ThirteenFCollector(_investor(), client, checkpoint_store)
    first_result = first_collector.collect_incremental()
    assert first_result.new_count == 3  # all 3 filings are new on first run

    second_collector = ThirteenFCollector(_investor(), client, checkpoint_store)
    second_result = second_collector.collect_incremental()
    client.close()

    assert second_result.new_count == 0
    assert second_result.items == []


@respx.mock
@freeze_time("2024-06-01")
def test_source_id_includes_investor_id(tmp_path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SECClient(user_agent="Investor Intel test@example.com")
    collector = ThirteenFCollector(_investor(), client, CheckpointStore(conn))
    client.close()
    assert collector.source_id == "sec_13f_duquesne_family_office"
```

- [x] **Step 2b: Run test to verify it fails**

```bash
uv run pytest tests/test_sec_thirteenf.py -v
```
Expected: FAIL — module does not exist.

- [x] **Step 3: Write the implementation**

`investor_intel/collectors/sec_thirteenf.py`:
```python
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from investor_intel.collectors.base import CheckpointStore, CollectItem, CollectResult
from investor_intel.collectors.sec_client import SECClient
from investor_intel.collectors.thirteenf_changes import compute_holding_changes
from investor_intel.collectors.thirteenf_document import render_thirteenf_body
from investor_intel.collectors.thirteenf_parser import (
    FilingRef,
    list_xml_document_candidates,
    parse_information_table_xml,
    parse_submissions_filings,
)
from investor_intel.models.config import InvestorConfig
from investor_intel.models.thirteenf import ThirteenFFiling, ThirteenFHolding

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data/{cik_short}/{accession_nodashes}"


def _cik_short(cik: str) -> str:
    return cik.lstrip("0") or "0"


def _accession_nodashes(accession_number: str) -> str:
    return accession_number.replace("-", "")


def _archive_dir(cik: str, accession_number: str) -> str:
    return _ARCHIVES_BASE.format(
        cik_short=_cik_short(cik), accession_nodashes=_accession_nodashes(accession_number)
    )


def _filing_index_url(cik: str, accession_number: str) -> str:
    return f"{_archive_dir(cik, accession_number)}/index.json"


def _filing_index_page_url(cik: str, accession_number: str) -> str:
    return f"{_archive_dir(cik, accession_number)}/{accession_number}-index.htm"


def _document_url(cik: str, accession_number: str, filename: str) -> str:
    return f"{_archive_dir(cik, accession_number)}/{filename}"


class ThirteenFCollector:
    def __init__(
        self,
        investor: InvestorConfig,
        client: SECClient,
        checkpoint_store: CheckpointStore,
    ) -> None:
        self.source_id = f"sec_13f_{investor.id}"
        self._investor = investor
        self._client = client
        self._checkpoint_store = checkpoint_store
        self._holdings_cache: dict[str, list[ThirteenFHolding]] = {}

    def _fetch_all_filings(self) -> list[FilingRef]:
        submissions = self._client.get_json(_SUBMISSIONS_URL.format(cik=self._investor.cik))
        return parse_submissions_filings(submissions)

    def _fetch_holdings(self, filing: FilingRef) -> list[ThirteenFHolding]:
        if filing.accession_number in self._holdings_cache:
            return self._holdings_cache[filing.accession_number]

        index_url = _filing_index_url(self._investor.cik, filing.accession_number)
        index_json = self._client.get_json(index_url)
        candidates = list_xml_document_candidates(index_json, exclude=filing.primary_document)

        holdings: list[ThirteenFHolding] | None = None
        for candidate in candidates:
            doc_url = _document_url(self._investor.cik, filing.accession_number, candidate)
            xml_text = self._client.get_text(doc_url)
            try:
                holdings = parse_information_table_xml(xml_text)
                break
            except ValueError:
                continue

        if holdings is None:
            raise ValueError(
                f"could not find an information table document for accession "
                f"{filing.accession_number}"
            )

        self._holdings_cache[filing.accession_number] = holdings
        return holdings

    def _find_previous(
        self, filing: FilingRef, all_filings: list[FilingRef]
    ) -> FilingRef | None:
        return next(
            (f for f in all_filings if f.period_of_report < filing.period_of_report), None
        )

    def _build_item(self, filing: FilingRef, all_filings: list[FilingRef]) -> CollectItem:
        current_holdings = self._fetch_holdings(filing)

        previous_ref = self._find_previous(filing, all_filings)
        previous_holdings = (
            self._fetch_holdings(previous_ref) if previous_ref is not None else None
        )

        thirteenf_filing = ThirteenFFiling(
            investor_id=self._investor.id,
            cik=self._investor.cik,
            accession_number=filing.accession_number,
            form_type=filing.form,
            filing_date=filing.filing_date,
            period_of_report=filing.period_of_report,
            holdings=current_holdings,
        )
        changes = compute_holding_changes(previous_holdings, current_holdings)
        canonical_url = _filing_index_page_url(self._investor.cik, filing.accession_number)
        body = render_thirteenf_body(thirteenf_filing, self._investor, changes, canonical_url)

        published_at = datetime(
            filing.filing_date.year,
            filing.filing_date.month,
            filing.filing_date.day,
            tzinfo=timezone.utc,
        )

        return CollectItem(
            source_specific_id=filing.accession_number,
            canonical_url=canonical_url,
            title=(
                f"{self._investor.fund_name} {filing.form} "
                f"({filing.period_of_report.isoformat()})"
            ),
            author=self._investor.fund_name,
            published_at=published_at,
            updated_at=None,
            language="en",
            body_text=body,
            content_capture_mode="full",
            companies=[h.issuer for h in current_holdings],
            document_type="13f_filing",
            filing_type=filing.form,
            reporting_period=filing.period_of_report.isoformat(),
            accession_number=filing.accession_number,
        )

    def _collect(
        self, filings_to_process: list[FilingRef], all_filings: list[FilingRef]
    ) -> CollectResult:
        items: list[CollectItem] = []
        errors: list[str] = []
        for filing in filings_to_process:
            try:
                items.append(self._build_item(filing, all_filings))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{filing.accession_number}: {exc}")

        if items:
            self._checkpoint_store.record_success(
                self.source_id, last_seen_id=items[-1].accession_number
            )
        elif errors:
            self._checkpoint_store.record_failure(self.source_id)

        return CollectResult(
            source_id=self.source_id,
            success=not errors,
            items=items,
            errors=errors,
            new_count=len(items),
        )

    def backfill(self, days: int) -> CollectResult:
        all_filings = self._fetch_all_filings()
        cutoff = date.today() - timedelta(days=days)
        to_process = sorted(
            (f for f in all_filings if f.filing_date >= cutoff),
            key=lambda f: f.filing_date,
        )
        result = self._collect(to_process, all_filings)
        state = self._checkpoint_store.get_state(self.source_id)
        state.backfill_completed = True
        self._checkpoint_store.save_state(state)
        return result

    def collect_incremental(self) -> CollectResult:
        all_filings = self._fetch_all_filings()
        state = self._checkpoint_store.get_state(self.source_id)

        if state.last_seen_id is None:
            to_process = list(all_filings)
        else:
            last_seen_date = next(
                (
                    f.filing_date
                    for f in all_filings
                    if f.accession_number == state.last_seen_id
                ),
                None,
            )
            to_process = (
                list(all_filings)
                if last_seen_date is None
                else [f for f in all_filings if f.filing_date > last_seen_date]
            )

        to_process.sort(key=lambda f: f.filing_date)
        return self._collect(to_process, all_filings)
```

- [x] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_sec_thirteenf.py -v
```
Expected: `4 passed`.

- [x] **Step 5: Commit**

```bash
git add investor_intel/collectors/sec_thirteenf.py tests/test_sec_thirteenf.py tests/fixtures/sec/index_0001536411-23-000004.json
git commit -m "feat: add ThirteenFCollector implementing the Collector protocol"
```

---

### Task 7: Full verification pass

**Files:** none created; runs checks across everything built in Tasks 1–6.

- [x] **Step 1: Run the full test suite**

```bash
export PATH="/opt/homebrew/bin:$PATH"
uv run pytest -v
```
Expected: all tests pass (57 from Core Foundation + ~26 new from this phase).

- [x] **Step 2: Run ruff**

```bash
uv run ruff check .
```
Expected: `All checks passed!`. Fix any reported issues and re-run until clean.

- [x] **Step 3: Run mypy**

```bash
uv run mypy investor_intel
```
Expected: `Success: no issues found`. Fix any reported issues and re-run until clean.

- [x] **Step 4: Manual sanity check of URL construction**

```bash
uv run python -c "
from investor_intel.collectors.sec_thirteenf import _archive_dir, _filing_index_page_url
print(_archive_dir('0001536411', '0001536411-24-000007'))
print(_filing_index_page_url('0001536411', '0001536411-24-000007'))
"
```
Expected output:
```
https://www.sec.gov/Archives/edgar/data/1536411/000153641124000007
https://www.sec.gov/Archives/edgar/data/1536411/000153641124000007/0001536411-24-000007-index.htm
```
This confirms CIK zero-stripping and accession-dash-stripping produce real, well-formed SEC
EDGAR URLs (not just internally-consistent test fixtures).

- [x] **Step 5: Commit any fixes from steps 2–3**

```bash
git add -A
git commit -m "chore: fix lint/type issues found in full verification pass"
```
(Skip this commit if there was nothing to fix.)

---

## Self-Review Notes

- **Spec coverage:** covers spec §4.3's 13F extraction fields (reporting date, filing date,
  accession number, issuer, CUSIP, holdings quantity, reported value, put/call, investment
  discretion, voting authority, quarter-over-quarter new/sold-out/increased/decreased/held,
  quantity change %, value change, portfolio weight, top holdings, concentration) and the
  required limitations disclosure. FIGI mapping, ticker/CUSIP cross-referencing, and 13F-HR/A
  amendment handling are explicitly out of scope (documented above), matching spec's own
  acknowledgment that these are secondary concerns not blocking MVP collection.
- **Type/signature consistency:** `ThirteenFCollector` conforms exactly to the `Collector`
  protocol from Core Foundation (`source_id: str`, `backfill(days) -> CollectResult`,
  `collect_incremental() -> CollectResult`); `CollectItem` field usage matches the dataclass
  defined in `investor_intel/collectors/base.py` exactly (no invented fields).
- **No storage coupling:** verified the collector never imports `obsidian_repo` or
  `sqlite_index` for writing — `sqlite_index` is only used in tests to construct a
  `CheckpointStore`, matching the Core Foundation's checkpoint-persistence design.
