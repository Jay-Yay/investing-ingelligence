from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel

from investor_intel.scoring.earnings_revision import EarningsRevisionInputs
from investor_intel.scoring.hysteresis import HysteresisState
from investor_intel.scoring.models import StockScoreResult
from investor_intel.scoring.valuation_scenarios import ValuationScenarios

_PROCESSED_DIR = "60_StockScore/processed"


class StockScoreSnapshot(BaseModel):
    """`60_StockScore/processed/<ticker>/<date>.json`에 저장되는 실제 내용.

    result와 hysteresis 상태를 함께 저장한다 - 다음 평가에서 "직전 신호가 언제부터였는지"를
    복원하려면 hysteresis.since가 필요하고, hysteresis.since는 그 자체로 point-in-time 정보라
    result와 분리하면 재구성이 불가능해진다(regime/models.py의 RegimeSnapshot과 동일한 이유).
    """

    result: StockScoreResult
    hysteresis: HysteresisState
    # 주간(LLM) 실행에서 산출된 뒤 일간(LLM-free) 실행이 그대로 이어받아 쓰는 값들 - 매일
    # 새로 계산하는 것은 오직 현재가/가격-수급 지표뿐이고, 밸류에이션 가정과 EPS 수정치는 다음
    # 주간 재평가 전까지 유지된다(섹션 17 daily/weekly 역할 분담).
    valuation_scenarios: ValuationScenarios | None = None
    earnings_revision_inputs: EarningsRevisionInputs | None = None


def _ticker_dir(vault_path: Path, ticker: str) -> Path:
    return vault_path / _PROCESSED_DIR / ticker.replace("/", "_")


def _processed_path(vault_path: Path, ticker: str, as_of: date) -> Path:
    return _ticker_dir(vault_path, ticker) / f"{as_of.isoformat()}.json"


def save_snapshot(vault_path: Path, snapshot: StockScoreSnapshot) -> Path:
    path = _processed_path(vault_path, snapshot.result.ticker, snapshot.result.as_of)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_snapshot(vault_path: Path, ticker: str, as_of: date) -> StockScoreSnapshot | None:
    path = _processed_path(vault_path, ticker, as_of)
    if not path.exists():
        return None
    return StockScoreSnapshot.model_validate_json(path.read_text(encoding="utf-8"))


def list_snapshot_dates(vault_path: Path, ticker: str) -> list[date]:
    directory = _ticker_dir(vault_path, ticker)
    if not directory.exists():
        return []
    dates: list[date] = []
    for path in directory.glob("*.json"):
        try:
            dates.append(date.fromisoformat(path.stem))
        except ValueError:
            continue
    return sorted(dates)


def score_at_or_before(vault_path: Path, ticker: str, target_date: date) -> float | None:
    """target_date 이전(포함) 가장 최근 스냅샷의 total_score.

    "이전(포함)" 이하만 조회한다는 것 자체가 백테스트/증분 비교에서 미래 정보를 참조하지 않게
    막는 장치다 - evaluation.py의 lookahead 방지 테스트가 이 함수를 직접 검증한다.
    """
    candidates = [d for d in list_snapshot_dates(vault_path, ticker) if d <= target_date]
    if not candidates:
        return None
    snapshot = load_snapshot(vault_path, ticker, max(candidates))
    return snapshot.result.total_score if snapshot else None


def compute_score_changes(
    vault_path: Path, ticker: str, as_of: date, current_score: float | None
) -> tuple[float | None, float | None, float | None]:
    """(1일 전, 1주 전, 1개월 전) 대비 점수 변화. 스냅샷이 없으면 해당 항목은 None."""
    if current_score is None:
        return None, None, None

    def _diff(days: int) -> float | None:
        prior = score_at_or_before(vault_path, ticker, as_of - timedelta(days=days))
        return None if prior is None else round(current_score - prior, 1)

    return _diff(1), _diff(7), _diff(30)


def load_latest_snapshot_before(
    vault_path: Path, ticker: str, before: date
) -> StockScoreSnapshot | None:
    candidates = [d for d in list_snapshot_dates(vault_path, ticker) if d < before]
    if not candidates:
        return None
    return load_snapshot(vault_path, ticker, max(candidates))


def load_previous_hysteresis(vault_path: Path, ticker: str, before: date) -> HysteresisState | None:
    candidates = [d for d in list_snapshot_dates(vault_path, ticker) if d < before]
    if not candidates:
        return None
    snapshot = load_snapshot(vault_path, ticker, max(candidates))
    return snapshot.hysteresis if snapshot else None
