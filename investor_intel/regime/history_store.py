from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from investor_intel.regime.models import IndicatorId, IndicatorObservation

_HISTORY_DIR = "60_MarketRegime/history"


def history_path(vault_path: Path, indicator_id: IndicatorId) -> Path:
    return vault_path / _HISTORY_DIR / f"{indicator_id.value}.jsonl"


def read_history(vault_path: Path, indicator_id: IndicatorId) -> list[IndicatorObservation]:
    path = history_path(vault_path, indicator_id)
    if not path.exists():
        return []
    observations: list[IndicatorObservation] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        observations.append(IndicatorObservation.model_validate(json.loads(stripped)))
    return observations


def latest_value_by_date(
    history: list[IndicatorObservation],
) -> dict[date, IndicatorObservation]:
    """observation_date별로 fetched_at이 가장 최근인 관측치(현재 알려진 최신값)만 남긴다."""
    resolved: dict[date, IndicatorObservation] = {}
    for obs in history:
        current = resolved.get(obs.observation_date)
        if current is None or obs.fetched_at > current.fetched_at:
            resolved[obs.observation_date] = obs
    return resolved


def latest_observation(history: list[IndicatorObservation]) -> IndicatorObservation | None:
    """가장 최근 observation_date의 현재 알려진 값 (오늘의 리포트에 쓸 "최신값")."""
    by_date = latest_value_by_date(history)
    if not by_date:
        return None
    latest_date = max(by_date)
    return by_date[latest_date]


def append_observations(
    vault_path: Path, indicator_id: IndicatorId, observations: list[IndicatorObservation]
) -> int:
    """새 관측치를 append한다.

    같은 observation_date에 대해 마지막으로 저장된 값과 동일하면(개정 없음, 같은 날 재실행
    등) 중복 저장하지 않는다 - "동일 날짜 재실행 시 중복 저장되지 않아야 한다"는 idempotent
    요구사항. 값이 실제로 달라졌으면(진짜 개정) is_revised=True로 새 줄을 추가하고 기존 줄은
    지우지 않는다 - 개정 이력 자체를 보존하기 위함(원본 지침 #4).
    """
    if not observations:
        return 0
    path = history_path(vault_path, indicator_id)
    existing = read_history(vault_path, indicator_id)
    latest = latest_value_by_date(existing)

    to_write: list[IndicatorObservation] = []
    for obs in observations:
        prior = latest.get(obs.observation_date)
        if prior is not None and prior.value == obs.value and prior.status == obs.status:
            continue
        is_revised = None if prior is None else prior.value != obs.value
        to_write.append(obs.model_copy(update={"is_revised": is_revised}))

    if not to_write:
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for obs in to_write:
            f.write(obs.model_dump_json() + "\n")
    return len(to_write)
