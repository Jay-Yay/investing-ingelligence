from investor_intel.storage.content_hash import (
    compute_content_hash,
    compute_stable_id,
    normalize_content,
)


def test_normalize_collapses_whitespace() -> None:
    assert normalize_content("  hello   world  \n\n") == "hello world"


def test_content_hash_is_deterministic() -> None:
    assert compute_content_hash("hello world") == compute_content_hash("hello world")


def test_content_hash_ignores_whitespace_differences() -> None:
    assert compute_content_hash("hello   world") == compute_content_hash("hello world")


def test_content_hash_differs_for_different_content() -> None:
    assert compute_content_hash("hello world") != compute_content_hash("goodbye world")


def test_stable_id_deterministic_and_distinct() -> None:
    id_a = compute_stable_id("telegram", "allbareun", "123", "https://t.me/allbareun/123")
    id_b = compute_stable_id("telegram", "allbareun", "123", "https://t.me/allbareun/123")
    id_c = compute_stable_id("telegram", "allbareun", "124", "https://t.me/allbareun/124")
    assert id_a == id_b
    assert id_a != id_c
    assert len(id_a) == 16


def test_stable_id_falls_back_to_canonical_url() -> None:
    id_a = compute_stable_id("naver", "engineerinvestor", None, "https://blog.naver.com/x/1")
    id_b = compute_stable_id("naver", "engineerinvestor", None, "https://blog.naver.com/x/2")
    assert id_a != id_b
