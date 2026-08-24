"""Vault 문서를 검색 가능한 청크 인덱스로 만드는 Indexing 계층.

기존 `storage/sqlite_index.py`는 '문서 메타데이터 카탈로그'다(중복제거·수집상태 추적용).
이 패키지는 그것과 별개로 '검색용 인덱스'를 만든다. Load -> Split -> Contextualize ->
Store 네 단계이며, 각 단계는 독립적으로 켜고 끌 수 있어(IndexConfig) 어떤 처리가 검색
품질에 얼마나 기여하는지 측정할 수 있다.
"""
from investor_intel.indexing.config import IndexConfig, VARIANTS
from investor_intel.indexing.loader import LoadedDocument, load_vault
from investor_intel.indexing.splitter import Chunk, split_document
from investor_intel.indexing.bm25_index import Bm25Index

__all__ = ["IndexConfig", "VARIANTS", "LoadedDocument", "load_vault", "Chunk",
           "split_document", "Bm25Index"]
