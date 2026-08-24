from __future__ import annotations

import re
import unicodedata

# 수집 과정에서 섞여 들어온 눈에 안 보이는 문자들. 남겨두면 토큰 경계가 깨지고
# 같은 단어가 서로 다른 토큰으로 색인된다.
_INVISIBLE = re.compile(r"[​‌‍﻿­⁠]")
_HTML_ARTIFACT = re.compile(r"&(?:cr|nbsp|amp|lt|gt|quot|#\d+);")
_REPLACEMENT = re.compile(r"�+")
_WS = re.compile(r"[ \t ]+")
_MULTINL = re.compile(r"\n{3,}")


def normalize(text: str) -> str:
    """색인·질의 양쪽에 동일하게 적용하는 정규화.

    NFKC로 전각/반각을 통일하지 않으면 '１０-Ｋ'와 '10-K'가 다른 토큰이 된다.
    """
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE.sub("", text)
    text = _HTML_ARTIFACT.sub(" ", text)
    text = _REPLACEMENT.sub(" ", text)
    text = _WS.sub(" ", text)
    text = _MULTINL.sub("\n\n", text)
    return text.strip()
