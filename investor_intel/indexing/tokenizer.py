from __future__ import annotations

import re

from investor_intel.indexing.text_normalize import normalize

_HANGUL = re.compile(r"[가-힣]+")
_LATIN_NUM = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-/]*")
_SPLIT_ID = re.compile(r"[._\-/]+")


def _hangul_ngrams(run: str, n: int = 2) -> list[str]:
    """한글 어절을 문자 n-gram으로 쪼갠다.

    한국어는 교착어라 '삼성전자'가 본문에서는 '삼성전자의', '삼성전자는'으로 나타난다.
    공백 기준 토크나이저(SQLite unicode61 기본값 포함)는 이 셋을 완전히 다른 토큰으로
    색인하므로 '삼성전자'로 검색하면 하나도 매칭되지 않는다. 형태소 분석기(mecab 등)를
    쓰면 더 정확하지만 외부 사전·설치 의존성이 생기므로, 여기서는 의존성 없이 재현
    가능한 문자 bigram을 쓴다. bigram은 재현율을 크게 올리는 대신 '전자의' 같은 걸친
    조각도 만들어 정밀도를 일부 희생한다 - 그 손익은 평가 결과로 확인한다.
    """
    if len(run) < n:
        return [run]
    return [run[i : i + n] for i in range(len(run) - n + 1)]


def tokenize(text: str, korean_ngram: bool = True, korean_keep_word: bool = False) -> list[str]:
    """색인·질의에 공통으로 쓰는 토크나이저.

    korean_ngram=False면 한글을 어절 통째로 남긴다(= 현행 수준 재현).
    korean_keep_word=True면 bigram과 함께 어절 원형도 남긴다. bigram만 쓰면 '투자', '규모'
    같은 흔한 조각이 대량으로 매칭돼 정밀도가 떨어지는데, 어절 원형 토큰은 문서빈도가 낮아
    IDF가 높으므로 '정확히 그 단어가 있는 문서'에 점수를 몰아준다. 재현율(bigram)과
    정밀도(원형)를 한 색인 안에서 같이 쓰는 셈이다.
    """
    text = normalize(text).lower()
    tokens: list[str] = []
    pos = 0
    for m in re.finditer(r"[가-힣]+|[A-Za-z0-9][A-Za-z0-9._\-/]*", text):
        tok = m.group(0)
        if _HANGUL.fullmatch(tok):
            if not korean_ngram:
                tokens.append(tok)
            else:
                tokens.extend(_hangul_ngrams(tok))
                if korean_keep_word and len(tok) > 2:
                    tokens.append(tok)
        else:
            tokens.append(tok)
            # 0001664703-22-000015, 10-q, 005930.ks 같은 식별자는 통째로도,
            # 조각으로도 검색된다. 둘 다 색인해 둔다.
            parts = [p for p in _SPLIT_ID.split(tok) if p and p != tok]
            tokens.extend(parts)
    return tokens


_FTS_UNSAFE = re.compile(r'[^0-9A-Za-z가-힣]')


def to_fts_document(text: str, korean_ngram: bool = True, korean_keep_word: bool = False) -> str:
    """FTS5 컬럼에 넣을 '토큰 스트림' 문자열.

    FTS5의 기본 unicode61 토크나이저는 공백/구두점으로만 자르므로, 우리가 원하는
    토큰화를 미리 적용한 뒤 공백으로 이어 붙여 넣는다. 이렇게 하면 색인 구조(BM25,
    posting list)는 검증된 SQLite 구현을 그대로 쓰면서 토큰 정의만 우리가 통제한다.
    """
    return " ".join(
        _FTS_UNSAFE.sub("", t) or "_" for t in tokenize(text, korean_ngram, korean_keep_word)
    )


def to_fts_query(text: str, korean_ngram: bool = True, korean_keep_word: bool = False) -> str:
    """질의를 FTS5 MATCH 식으로. 토큰 OR 결합 후 BM25가 순위를 매긴다."""
    toks = {_FTS_UNSAFE.sub("", t) for t in tokenize(text, korean_ngram, korean_keep_word)}
    toks = {t for t in toks if t}
    if not toks:
        return ""
    return " OR ".join(f'"{t}"' for t in sorted(toks))
