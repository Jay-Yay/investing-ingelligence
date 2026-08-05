# 모델 변경 이력

이 파일은 `config/scoring/*.yaml`의 가중치/임계값/하드게이트가 바뀔 때마다 사람이 직접
추가한다. LLM(Model Reviewer)은 여기에 직접 쓰지 않는다 - `pending_human_approval` 상태의
제안만 만들고, 실제로 반영하는 것은 사람이 이 파일에 새 항목을 추가하고
`model_registry/champion.yaml`을 갱신하는 것으로 확정한다.

## 2026-08-02 — v1.0.0 (초기 버전)

- `config/scoring/global_scoring.yaml`, `config/scoring/sector_memory.yaml` 최초 작성.
- 대분류 가중치: 매크로 15/수요 20/펀더멘털 25/실적 15/밸류 10/가격 10/리스크 5 (메모리
  섹터는 8: 매크로10/수급25/펀더멘털25/실적15/밸류10/가격10/리스크5).
- 히스테리시스 임계값(신규진입 72/유지 62/축소검토 55/매도검토 45, 대기 5거래일)은
  섹션 15 스펙 값을 그대로 채택 - 아직 백테스트로 검증되지 않았다.
- 백테스트/Champion-Challenger 비교 없이 시작 - 초기 버전이라 비교 대상이 없다.
