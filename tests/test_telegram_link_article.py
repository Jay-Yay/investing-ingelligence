import httpx
import respx

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.collectors.telegram_link_article import (
    extract_article_urls,
    fetch_article,
)

# 아래 실제 텔레그램 메시지 원문들은 vault/10_Sources/Telegram/*에 이미 수집돼 있는 실데이터에서
# 그대로 가져왔다 - 유튜브/X 링크가 섞인 메시지, URL 뒤에 공백 없이 한글이 바로 붙는 메시지 등
# 실제로 걸렸던 패턴을 회귀 테스트로 고정한다.


def test_extracts_article_url_with_trailing_fragment() -> None:
    text = "[속보] 삼성전자 노사 성과급 협상 극적 타결\n\nhttps://www.hankyung.com/article/202605200099i#google_vignette"
    assert extract_article_urls(text) == [
        "https://www.hankyung.com/article/202605200099i#google_vignette"
    ]


def test_url_immediately_followed_by_korean_text_does_not_swallow_it() -> None:
    text = (
        "[단독] SK하이닉스, LTA 가격 상단 제한 없다… 주가 420만원 '가시권'  "
        "https://biz.newdaily.co.kr/site/data/html/2026/06/30/2026063000209.html주목할 점은 "
        "각 사별 LTA의 세부 조항이다."
    )
    assert extract_article_urls(text) == [
        "https://biz.newdaily.co.kr/site/data/html/2026/06/30/2026063000209.html"
    ]


def test_excludes_youtube_and_x_and_telegram_links() -> None:
    assert extract_article_urls('젠슨 황 "Vera Rubin is in Full Production"'
                                 "https://www.youtube.com/watch?v=wSp6AiNIrsY") == []
    assert extract_article_urls(
        "다 끝났다.\n\nhttps://x.com/firstadopter/status/2082825600582988262"
    ) == []
    assert extract_article_urls("공유: https://t.me/allbareun/9045") == []


def test_keeps_naver_blog_link() -> None:
    assert extract_article_urls("https://blog.naver.com/egzion/224326913555") == [
        "https://blog.naver.com/egzion/224326913555"
    ]


def test_deduplicates_and_caps_at_limit() -> None:
    text = (
        "https://n.news.naver.com/mnews/article/021/0002699187 "
        "https://n.news.naver.com/mnews/article/021/0002699187 "
        "https://n.news.naver.com/mnews/article/011/0004468372 "
        "https://www.yna.co.kr/view/AKR20260528167800530 "
        "https://www.newsis.com/view/NISX20260602_0003652715"
    )
    urls = extract_article_urls(text, limit=3)
    assert urls == [
        "https://n.news.naver.com/mnews/article/021/0002699187",
        "https://n.news.naver.com/mnews/article/011/0004468372",
        "https://www.yna.co.kr/view/AKR20260528167800530",
    ]


def test_no_urls_in_plain_text_message() -> None:
    text = "앞으로는 호르무즈 및 바브엘만데브 해협의 원유 탱커 통항 선박수로 업데이트합니다"
    assert extract_article_urls(text) == []


_ARTICLE_HTML = """
<html><head><title>테스트 기사 제목 | 테스트뉴스</title></head>
<body>
<nav>메뉴 구독 로그인 검색</nav>
<article>
<h1>테스트 기사 제목</h1>
<p>이것은 기사 본문 첫 문단이다. 실제 내용을 담고 있다.</p>
<p>이것은 두 번째 문단으로 조금 더 자세한 설명을 담고 있다.</p>
</article>
<footer>저작권 안내 및 광고</footer>
</body></html>
"""


@respx.mock
def test_fetch_article_extracts_title_and_body() -> None:
    respx.get("https://example.com/news/1").mock(
        return_value=httpx.Response(200, text=_ARTICLE_HTML)
    )
    client = SimpleHttpClient()
    article = fetch_article(client, "https://example.com/news/1")
    client.close()

    # trafilatura의 잡동사니(메뉴/광고) 제거는 통계적 휴리스틱이라 실제 크기의 페이지에서
    # 신뢰도 있게 작동한다(collectors/telegram_link_article.py 도입 시 실제 기사 URL로
    # 라이브 검증함) - 이 작은 합성 fixture에서는 그 판단을 재현할 만큼 신호가 없으므로,
    # 여기서는 본문 문단이 온전히 포함됐는지와 title 태그 추출만 검증한다.
    assert article.error is None
    assert article.title == "테스트 기사 제목 | 테스트뉴스"
    assert article.body_text is not None
    assert "기사 본문 첫 문단" in article.body_text
    assert "두 번째 문단" in article.body_text


@respx.mock
def test_fetch_article_records_error_when_extraction_yields_nothing() -> None:
    respx.get("https://example.com/empty").mock(
        return_value=httpx.Response(200, text="<html><body><script>var x=1;</script></body></html>")
    )
    client = SimpleHttpClient()
    article = fetch_article(client, "https://example.com/empty")
    client.close()

    assert article.body_text is None
    assert article.error is not None


@respx.mock
def test_fetch_article_records_error_on_http_failure() -> None:
    respx.get("https://example.com/blocked").mock(return_value=httpx.Response(403))
    client = SimpleHttpClient()
    article = fetch_article(client, "https://example.com/blocked")
    client.close()

    assert article.body_text is None
    assert article.error is not None


@respx.mock
def test_fetch_article_naver_blog_uses_dedicated_post_view_endpoint() -> None:
    post_html = """
    <div class="se-title-text"><p class="se-text-paragraph">블로그 제목</p></div>
    <div class="se-main-container">
      <p class="se-text-paragraph">블로그 본문 문단 하나.</p>
    </div>
    """
    respx.get(
        "https://blog.naver.com/PostView.naver?blogId=egzion&logNo=224326913555"
    ).mock(return_value=httpx.Response(200, text=post_html))
    client = SimpleHttpClient()
    article = fetch_article(client, "https://blog.naver.com/egzion/224326913555")
    client.close()

    assert article.error is None
    assert article.body_text == "블로그 본문 문단 하나."
