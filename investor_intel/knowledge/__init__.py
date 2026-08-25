"""OKF(Open Knowledge Format) 지식 레이어.

원본 vault(10_Sources)는 '증거'로 그대로 두고, 그 위에 검색·공유 가능한 지식 레이어를
20_Knowledge/ 아래 OKF 번들로 만든다.

OKF v0.1 규약 중 이 구현이 지키는 것:
  - 지식을 'YAML frontmatter가 붙은 마크다운 파일의 디렉터리'로 표현한다
  - 모든 concept 파일에 `type` 필드를 반드시 둔다 (OKF가 요구하는 유일한 필수 필드)
  - concept 간 관계를 일반 마크다운 링크로 표현해 디렉터리를 그래프로 만든다
  - 디렉터리마다 index.md(점진적 탐색용), 번들 루트에 log.md(변경 이력)를 둔다
  - 표준 필드(type/title/description/resource/tags/timestamp) 위에 도메인 확장 필드를 얹는다
"""
from investor_intel.knowledge.schema import Concept, ConceptType, EntityRef, Period, Provenance
from investor_intel.knowledge.registry import CompanyRegistry
from investor_intel.knowledge.builder import build_bundle

__all__ = ["Concept", "ConceptType", "EntityRef", "Period", "Provenance",
           "CompanyRegistry", "build_bundle"]
