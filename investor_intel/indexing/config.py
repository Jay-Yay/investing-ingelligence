from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class IndexConfig:
    """인덱싱 파이프라인의 각 처리를 개별로 켜고 끄기 위한 설정.

    변형(variant)마다 하나씩 기능을 더해 인덱스를 새로 만들고 동일한 평가셋을 돌리면,
    '어떤 처리가 검색 품질을 얼마나 올렸는가'를 분리해서 볼 수 있다(ablation).
    """

    name: str
    label: str
    # --- Split ---
    chunking: bool = False           # False면 문서 전체가 곧 검색 단위
    target_chars: int = 700
    max_chars: int = 1200
    overlap_chars: int = 120
    # --- Normalize ---
    strip_boilerplate: bool = False  # 수집기가 모든 문서에 붙이는 고정 문구 제거
    # --- Tokenize ---
    korean_ngram: bool = False       # 한글을 문자 bigram으로 색인(어절 단위 색인의 한계 보완)
    korean_keep_word: bool = False   # bigram과 함께 어절 원형도 색인(정밀도 회복)
    # --- Contextualize ---
    context_header: bool = False     # 청크 앞에 출처/제목/섹션 경로를 결정론적으로 덧붙임
    # --- Store / Retrieve ---
    metadata_boost: bool = False     # 제목·티커·filing_type 등 필드 일치에 가중치
    separate_metadata_only: bool = False  # 본문 없는 문서를 별도 취급

    def evolve(self, **kw) -> "IndexConfig":
        return replace(self, **kw)


V0 = IndexConfig(
    name="V0",
    label="현행 수준 — 문서 단위 · 어절 토큰",
)
V1 = V0.evolve(name="V1", label="+ 구조 인식 청킹", chunking=True)
V2 = V1.evolve(name="V2", label="+ 한글 bigram 토크나이징", korean_ngram=True)
V3 = V2.evolve(name="V3", label="+ 문맥 헤더 · 보일러플레이트 제거",
               context_header=True, strip_boilerplate=True)
V4 = V3.evolve(name="V4", label="+ 메타데이터 가중 · 본문없음 분리",
               metadata_boost=True, separate_metadata_only=True)

# V4에서 두 가지를 동시에 켰더니 식별자 조회가 무너졌다. 어느 쪽이 원인인지 분리하려고
# '메타데이터 가중만' 켠 변형을 따로 둔다. 결과적으로 이쪽이 권장 구성이 된다.
V5 = V3.evolve(name="V5", label="+ 메타데이터 가중만 (본문없음 유지)",
               metadata_boost=True, separate_metadata_only=False)

# bigram만 쓰면 흔한 조각이 대량 매칭돼 패러프레이즈 질의에서 정밀도가 떨어졌다.
# 어절 원형 토큰을 함께 색인해 정밀도를 되찾는지 확인한다.
V6 = V5.evolve(name="V6", label="+ 어절 원형 토큰 병기 (권장)", korean_keep_word=True)

# V7부터는 색인 입력이 10_Sources 원본이 아니라 20_Knowledge OKF 번들이다.
# 청킹·토크나이징 설정은 V6와 완전히 동일하게 두어, 차이가 '지식 레이어와 그 메타데이터'
# 에서만 오도록 통제한다.
V7 = V6.evolve(name="V7", label="OKF 번들에서 색인 (메타데이터 필터 가능)")

VARIANTS = [V0, V1, V2, V3, V4, V5, V6]
OKF_VARIANTS = [V7]
ALL_VARIANTS = VARIANTS + OKF_VARIANTS
