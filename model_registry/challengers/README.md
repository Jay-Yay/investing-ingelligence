# Challengers

승인 대기 중인 후보 모델 설정을 여기에 둔다. 형식은 `config/scoring/global_scoring.yaml` /
`sector_memory.yaml`과 동일하되 파일명에 후보 버전을 붙인다 (예:
`global_scoring.v1.1.0-oversupply-weight.yaml`).

절차:

1. Model Reviewer의 `pending_human_approval` 제안 또는 사람이 직접 새 후보를 이 디렉터리에
   추가한다.
2. `scoring/evaluation.compare_champion_challenger()`로 기존 champion과 워크포워드 비교한다
   (최소 표본 20건 미만이면 비교 자체를 보류한다 - `evaluation.py` 참고).
3. 경제적으로 유의미한 개선이 확인되고 사람이 승인하면, `model_registry/champion.yaml`을
   갱신하고 `changelog.md`에 항목을 추가한 뒤 실제 `config/scoring/*.yaml`을 교체한다.
4. 승인되지 않은 후보는 이 디렉터리에 그대로 남겨 다음 재검토 때 참고한다.
