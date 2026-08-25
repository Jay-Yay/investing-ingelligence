"""수집 시점에 본문의 종목 관계를 해소한다.

## 왜 여기서 하는가

텔레그램·네이버·IB 문서는 원본에 종목 정보가 전혀 없다(`companies: []`). 실측으로 그런
문서가 2,860건(텔레그램 1,990 + 네이버 517 + IB 353)이고, 그래서 `document_assets`
테이블이 0행이었다 - 티커로 문서를 찾는 모든 조회가 빈 결과를 냈다.

지금까지 이 복원은 OKF 번들 빌더에서만 했다. 번들을 만들기 전에는 관계가 존재하지 않으므로
Metadata Filter도, 티커 조회도 쓸 수 없었다. 확정할 수 있는 사실을 수집 시점에 확정해
frontmatter에 남기면, 번들·색인·`analyze`가 모두 같은 값을 보게 된다.

## 분석 주체와 분석 대상을 나눈다

"교보증권이 제시한 에이피알 목표주가"에서 교보증권은 리포트를 쓴 쪽이고 에이피알이 분석
대상이다. 둘을 한 `companies` 목록에 섞으면 교보증권으로 필터링해 정답을 지우거나, 교보증권의
다른 종목 리포트가 상위를 차지한다(실측으로 확인된 실패 사례다). 그래서 본문 매칭 결과를
`mentions`와 `analyst_house`로 나눠 담는다.

## 재현성

매칭 결과는 사전(상장법인 명부)에 의존하므로 사전이 바뀌면 결과도 바뀐다. 어떤 사전으로
뽑은 값인지 `lexicon_version`에 남겨야 나중에 결과 차이를 설명할 수 있다.
"""

from __future__ import annotations

import re
import sqlite3

from investor_intel.knowledge.registry import ANALYST_HOUSE, CompanyRegistry
from investor_intel.models.source_document import DocumentEntities

__all__ = ["ANALYST_HOUSE", "EntityResolver", "merge_mentions"]

# 수집기가 밝힌 종목은 `000660`처럼 코드만, 본문 매칭 결과는 `kr-000660`처럼 시장 접두어를
# 달고 온다. 같은 종목을 두 번 넣지 않으려면 비교는 접두어를 뗀 값으로 해야 한다.
_MARKET_PREFIX = re.compile(r"^(?:kr|us)-")


def merge_mentions(declared: list[str], matched: list[str]) -> list[str]:
    """수집기가 확정한 종목을 앞에 두고, 본문에서 찾은 종목을 뒤에 붙인다.

    수집기가 종목을 밝혔다고 해서 본문 매칭을 건너뛰면 안 된다 - IB 리서치 107건이 그
    경우였고, 수집기는 리포트의 주 종목 하나만 밝히지만 본문에는 여러 종목이 나온다.
    """
    out = list(dict.fromkeys(declared))
    seen = {_MARKET_PREFIX.sub("", key) for key in out}
    for key in matched:
        bare = _MARKET_PREFIX.sub("", key)
        if bare not in seen:
            seen.add(bare)
            out.append(key)
    return out


def _load_dart_names(conn: sqlite3.Connection) -> dict[str, str]:
    """열려 있는 연결에서 상장법인 명부를 읽는다.

    `knowledge.registry.load_dart_names`는 경로를 받아 스스로 연결을 열지만, 수집 경로는
    이미 열린 연결을 들고 있다(그리고 그 연결에는 아직 커밋되지 않은 corp_code 캐시가 있을
    수 있다).
    """
    try:
        rows = conn.execute(
            "SELECT stock_code, corp_name FROM dart_corp_codes "
            "WHERE stock_code IS NOT NULL AND stock_code != ''"
        ).fetchall()
    except sqlite3.Error:
        return {}
    return {row[0]: row[1] for row in rows}


class EntityResolver:
    """본문에서 종목을 찾아 관계로 돌려준다. 수집 실행당 한 번만 만들면 된다."""

    def __init__(self, dart_names: dict[str, str]) -> None:
        self._registry = CompanyRegistry()
        for code, name in dart_names.items():
            self._registry.add_lexicon(name, "kr", code)
        # 사전이 바뀌면 매칭 결과도 바뀐다. 규모를 남겨 두면 나중에 결과 차이를 설명할 수 있다.
        self.lexicon_version = f"dart-corp-codes:{len(dart_names)}"

    @classmethod
    def from_connection(cls, conn: sqlite3.Connection) -> EntityResolver:
        return cls(_load_dart_names(conn))

    @property
    def is_empty(self) -> bool:
        """사전이 비어 있으면(DART 캐시 미구축) 어떤 관계도 복원할 수 없다."""
        return self._registry.lexicon_size == 0

    def resolve(self, body: str, subject: str | None = None, limit: int = 10) -> DocumentEntities:
        found = self._registry.find_mentions(body, limit=limit)
        return DocumentEntities(
            subject=subject,
            mentions=[ref.key for ref in found if not ANALYST_HOUSE.search(ref.name)],
            analyst_house=[ref.key for ref in found if ANALYST_HOUSE.search(ref.name)],
            lexicon_version=self.lexicon_version,
        )
