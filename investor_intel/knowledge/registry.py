from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from investor_intel.knowledge.schema import EntityRef

# 본문에 나오는 이 이름들은 '분석 대상 종목'이 아니라 '리포트를 쓴 곳'이다. 둘을 한 목록에
# 섞으면 분석 주체로 필터링해 정답 문서를 지우게 된다.
ANALYST_HOUSE = re.compile(r"(증권|투자증권|자산운용|캐피탈|금융투자)$")

# 회사명으로 오탐이 나기 쉬운 짧은/일반적인 이름. 본문 언급 매칭에서 제외한다.
_STOP_NAMES = {"대한", "한국", "미래", "삼성", "현대", "신세계", "이지", "아이", "우리",
               "케이", "에스", "디에스", "지에스", "제이", "네오", "코리아", "글로벌"}


@dataclass
class Company:
    key: str      # kr-005930 / us-NBIS
    name: str
    market: str   # kr | us
    code: str
    aliases: list[str]

    def ref(self) -> EntityRef:
        return EntityRef("company", self.key, self.name)


class CompanyRegistry:
    """종목 레지스트리.

    DART 공시(종목코드+회사명)와 SEC 공시(티커+회사명)에서 실제로 등장한 종목만 모은다.
    dart_corp_codes 캐시에는 118,535개 법인이 있지만, 코퍼스에 한 번도 안 나오는 법인까지
    concept 파일로 만들면 번들이 검색되지 않는 빈 노드로 부풀 뿐이다. OKF 번들은
    '조직이 실제로 쓰는 지식'을 담는 것이지 마스터 데이터 덤프가 아니다.
    """

    def __init__(self) -> None:
        self.by_key: dict[str, Company] = {}
        self._alias_index: dict[str, str] = {}
        self._lexicon: dict[str, tuple[str, str, str, str]] = {}
        # 관계 키로 사전을 되찾기 위한 역인덱스. 사전이 10만 건이라 선형 탐색은 못 한다.
        self._lexicon_by_key: dict[str, tuple[str, str, str, str]] = {}

    def add(self, key: str, name: str, market: str, code: str, aliases: list[str] | None = None) -> Company:
        c = self.by_key.get(key)
        if c is None:
            c = Company(key, name, market, code, aliases or [])
            self.by_key[key] = c
        for a in {name, *(aliases or [])}:
            a = a.strip()
            if len(a) >= 3 and a not in _STOP_NAMES:
                self._alias_index.setdefault(a, key)
        return c

    def get(self, key: str) -> Company | None:
        return self.by_key.get(key)

    @property
    def lexicon_size(self) -> int:
        """매칭 사전에 올라 있는 이름 수. 사전이 비면 관계 복원이 불가능하다."""
        return len(self._lexicon)

    def add_lexicon(self, name: str, market: str, code: str) -> None:
        """매칭 사전에만 등록한다(concept 파일은 만들지 않는다).

        상장법인 명부 전체를 concept으로 만들면 번들이 한 번도 언급되지 않는 빈 노드
        10만 개로 부푼다. 사전에만 넣어두고, 본문에서 실제로 언급된 종목만
        `promote()`로 concept으로 승격한다 - 그래야 마크다운 링크에 깨진 대상이 없다.
        """
        name = name.strip()
        if len(name) < 4 or name in _STOP_NAMES:
            return
        entry = (company_key(market, code), name, market, code)
        self._lexicon.setdefault(name, entry)
        self._lexicon_by_key.setdefault(entry[0], entry)

    def promote_key(self, key: str) -> Company | None:
        """관계 키(`kr-278470`)로 사전을 뒤져 concept으로 승격한다.

        수집 시점에 해소된 관계는 이름이 아니라 키로 저장된다. 그 키를 번들에서 다시 링크로
        쓰려면 대상 concept이 실제로 있어야 한다 - 없으면 끊어진 링크가 된다.
        """
        entry = self._lexicon_by_key.get(key)
        if entry is None:
            return None
        _, name, market, code = entry
        return self.add(key, name, market, code)

    def promote(self, name: str) -> Company | None:
        entry = self._lexicon.get(name)
        if entry is None:
            return None
        key, nm, market, code = entry
        return self.add(key, nm, market, code)

    def find_mentions(self, text: str, limit: int = 8) -> list[EntityRef]:
        """본문에서 등록된 회사명을 찾아 관계로 승격한다.

        텔레그램·블로그·IB 문서는 frontmatter에 종목 정보가 전혀 없다(companies: []).
        원본 메타데이터에 없는 관계를 지식 레이어에서 복원하는 지점이 여기다.
        긴 이름부터 매칭해 '삼성전자'가 '삼성'으로 잘못 잡히는 것을 막는다.
        """
        hits: dict[str, EntityRef] = {}
        head = text[:8000]
        # 한글 어절을 뽑아 원형과 조사 1~2자를 뗀 형태까지 사전에서 찾는다.
        # 사전이 10만 건이라 전체 문자열 스캔은 못 하고, 반대로 문서에서 후보를 만들어
        # 사전을 조회한다(어절당 조회 3회).
        # 후보를 set으로 돌면 파이썬 문자열 해시가 실행마다 달라져(PYTHONHASHSEED) 후보가
        # limit를 넘는 문서에서 매번 다른 종목이 살아남는다. 수집 시점에 확정해 frontmatter에
        # 적는 값이 실행마다 달라지면 안 되므로, 본문에 먼저 나온 순서로 고정한다
        # (앞에 나온 종목이 그 문서의 주제일 가능성도 더 높다).
        for run in dict.fromkeys(re.findall(r"[가-힣A-Za-z0-9]{4,20}", head)):
            for cand in (run, run[:-1], run[:-2]):
                if len(cand) < 4:
                    break
                key = self._alias_index.get(cand)
                if key is not None:
                    c = self.by_key[key]
                    hits.setdefault(key, EntityRef("company", c.key, c.name))
                    break
                if cand in self._lexicon:
                    c = self.promote(cand)
                    if c is not None:
                        hits.setdefault(c.key, EntityRef("company", c.key, c.name))
                    break
            if len(hits) >= limit:
                break
        return list(hits.values())


_TICKER = re.compile(r"^[A-Z][A-Z.\-]{0,6}$")


def company_key(market: str, code: str) -> str:
    return f"{market}-{code}"


def load_dart_names(db_path: Path) -> dict[str, str]:
    """stock_code -> corp_name (기존 dart_corp_codes 캐시 재사용)."""
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT stock_code, corp_name FROM dart_corp_codes WHERE stock_code IS NOT NULL "
            "AND stock_code != ''"
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    return {r[0]: r[1] for r in rows}
