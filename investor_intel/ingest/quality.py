"""수집한 본문의 품질을 **측정**한다.

## 왜 수집 시점에 재야 하는가

지금까지 이 판정은 OKF 번들 빌더(`knowledge/builder.py`)에서만 했다. 그러면 번들을 만들지
않는 소비자 - `analyze` 단계와, vault의 마크다운을 직접 읽어 브리핑을 쓰는 경로 - 는 본문이
깨졌는지 알 방법이 없다. 실제로 DART 문서 211건이 본문의 3~50%가 치환문자(U+FFFD)인 상태로
저장돼 있었고, 원문 frontmatter에는 그 사실을 알려주는 필드가 하나도 없었다.

## 측정과 판정을 분리하는 이유

frontmatter에는 **측정값**(`readable_ratio`, `truncated`, `original_chars`)만 넣는다.
"이 문서는 corrupt다" 같은 임계값 판정은 넣지 않는다 - 임계값은 언제든 바뀔 수 있고,
바뀔 때마다 4,818건을 재수집해야 한다면 그 필드는 유지될 수 없다. 판정이 필요한 소비자는
`is_corrupt(doc.readable_ratio)`를 부르면 된다.
"""

from __future__ import annotations

import re

# 디코딩 실패 지점에 들어가는 치환문자.
REPLACEMENT_CHAR = "�"

# 본문의 이 비율 이상이 치환문자면 근거로 인용할 수 없는 문서로 본다. OKF 번들 빌더가
# 쓰던 값(0.05)을 그대로 옮겨왔다 - 임계값이 두 곳에 따로 있으면 반드시 어긋난다.
CORRUPT_RATIO_THRESHOLD = 0.05

# `text_extract.truncate`가 본문 끝에 붙이는 문구. 절단 사실이 지금까지 본문 안 한국어
# 문장으로만 남아 있어서, 구조화된 소비자가 "이 문서에는 근거가 없을 수 있다"를 판단할 수
# 없었다. 이미 수집된 문서에도 적용되도록 본문에서 되읽는다.
_TRUNCATION_MARKER = re.compile(r"\[\.\.\.이하 생략, 원문 총 ([\d,]+)자 중 [\d,]+자까지만 캡처됨")


def readable_ratio(text: str) -> float:
    """본문 중 실제로 읽을 수 있는 문자의 비율. 빈 본문은 1.0으로 둔다.

    치환문자는 원래 문자 하나가 여러 개로 불어나기도 하므로(EUC-KR 한글 한 글자가 U+FFFD
    두 개가 된다) 이 값은 "얼마나 깨졌나"의 하한이 아니라 관측된 비율 그대로다.
    """
    if not text:
        return 1.0
    return round(1.0 - text.count(REPLACEMENT_CHAR) / len(text), 4)


def is_corrupt(ratio: float | None) -> bool:
    """측정된 가독 비율이 인용 불가 수준인지."""
    return ratio is not None and ratio < 1.0 - CORRUPT_RATIO_THRESHOLD


def truncation_of(text: str) -> tuple[bool, int | None]:
    """본문이 절단됐는지와, 절단 전 원문 길이를 돌려준다."""
    match = _TRUNCATION_MARKER.search(text)
    if match is None:
        return False, None
    return True, int(match.group(1).replace(",", ""))
