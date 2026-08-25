from __future__ import annotations

import re
import zipfile
from io import BytesIO

from investor_intel.collectors.dart_client import DartClient
from investor_intel.collectors.table_markdown import convert_tables_to_markdown
from investor_intel.collectors.text_extract import strip_markup, truncate

_DOCUMENT_URL = (
    "https://opendart.fss.or.kr/api/document.xml?crtfc_key={api_key}&rcept_no={rcept_no}"
)

# XML 선언의 encoding 속성. 선언은 정의상 ASCII 호환 범위로 시작하므로 앞부분만 latin-1로
# 읽어 찾아도 안전하다.
_XML_DECL_ENCODING = re.compile(rb"""<\?xml[^>]*?encoding\s*=\s*["']([\w.\-]+)["']""", re.I)

# 실제 원문에서 확인된 후보 순서. EUC-KR은 CP949의 부분집합이라 CP949만 시도하면 된다.
_FALLBACK_ENCODINGS = ("utf-8", "cp949", "utf-16")

# DART 원문은 줄바꿈을 `&cr;`이라는 자체 엔티티로 쓴다. HTML 표준 엔티티가 아니라서
# `html.unescape`가 손대지 않고, 그대로 두면 본문에 "&cr;&cr;&cr;" 같은 문자열이 남는다.
_DART_CR = re.compile(r"&cr;", re.I)


def decode_document_xml(raw: bytes) -> str:
    """DART 원문 XML 바이트를 문자열로 디코딩한다.

    OpenDART의 `document.xml` ZIP 안에 든 XML은 상당수가 EUC-KR/CP949다. 이걸 UTF-8로
    강제 디코딩하면(예전 구현이 `decode("utf-8", errors="replace")`를 썼다) 한글 한 글자마다
    치환문자 U+FFFD 두 개가 박혀 본문의 절반이 통째로 못 읽는 문자가 된다 - 실제로 vault의
    DART 문서 211건이 이 상태로 저장됐고, 그중에는 본문의 50.9%가 U+FFFD인 것도 있었다
    (에이피알 2022-05-16 분기보고서). 검색 인덱스는 그 깨진 문자를 그대로 색인하므로
    "찾을 수는 있는데 읽을 수는 없는 문서"가 된다.

    그래서 인코딩을 추정하되, 추정이 틀렸을 때 조용히 깨진 문자를 만들지 않도록 후보를
    `errors="strict"`로만 시도한다. 순서는 (1) XML 선언이 스스로 밝힌 인코딩,
    (2) UTF-8, (3) CP949, (4) UTF-16. UTF-8을 CP949보다 먼저 두는 이유는 CP949가
    UTF-8로 인코딩된 한글 바이트열도 (뜻이 깨진 채로) 성공적으로 디코딩해버리기 때문이다.
    전부 실패하면 마지막에야 치환을 허용한다.
    """
    candidates: list[str] = []
    match = _XML_DECL_ENCODING.search(raw[:200])
    if match:
        candidates.append(match.group(1).decode("latin-1"))
    candidates.extend(_FALLBACK_ENCODINGS)

    seen: set[str] = set()
    for encoding in candidates:
        key = encoding.lower().replace("_", "-")
        if key in seen:
            continue
        seen.add(key)
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue

    # 어느 후보로도 온전히 읽히지 않는 원문. 여기까지 오면 치환문자가 섞이는 것을 막을 수
    # 없으므로, 내용을 버리지 않되 호출부가 품질을 판정할 수 있도록 그대로 넘긴다
    # (`ingest.quality`가 U+FFFD 비율로 corrupt를 판정한다).
    return raw.decode("utf-8", errors="replace")


def fetch_full_text(client: DartClient, api_key: str, rcept_no: str) -> str | None:
    """OpenDART document.xml에서 공시 원문 전체 텍스트를 가져온다.

    document.xml은 원문 XML을 담은 ZIP을 반환한다. 실패(네트워크 오류, 잘못된 ZIP, 빈 본문 등)
    시 예외를 던지지 않고 None을 반환한다 - 호출부가 metadata_only로 폴백할 수 있도록.
    """
    try:
        zip_bytes = client.get_bytes(_DOCUMENT_URL.format(api_key=api_key, rcept_no=rcept_no))
        with zipfile.ZipFile(BytesIO(zip_bytes)) as archive:
            xml_names = [name for name in archive.namelist() if name.lower().endswith(".xml")]
            if not xml_names:
                return None
            raw_xml = decode_document_xml(archive.read(xml_names[0]))
    except Exception:  # noqa: BLE001
        return None

    raw_xml = _DART_CR.sub("\n", raw_xml)
    text = strip_markup(convert_tables_to_markdown(raw_xml))
    if not text:
        return None
    return truncate(text)
