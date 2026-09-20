"""检索融合与上下文组装单元测试：RRF 融合排序、token 预算裁剪、引用映射。"""

import os

os.environ.setdefault("API_KEY_QUERY", "q")
os.environ.setdefault("API_KEY_ADMIN", "a")
os.environ.setdefault("APP_SECRET", "s")

from app.generation.context_builder import build_context
from app.retrieval.hybrid_search import rrf_fuse


def test_rrf_prefers_items_in_both_rankings():
    vec = [{"chunk_id": "a"}, {"chunk_id": "b"}, {"chunk_id": "c"}]
    bm25 = [{"chunk_id": "b"}, {"chunk_id": "d"}, {"chunk_id": "a"}]
    fused = rrf_fuse([vec, bm25], top_n=4)
    # b 在向量第 2 + BM25 第 1，a 在向量第 1 + BM25 第 3 → b 略优
    assert fused[0] in ("a", "b")
    assert set(fused) == {"a", "b", "c", "d"}


def test_rrf_empty_rankings():
    assert rrf_fuse([], top_n=5) == []
    assert rrf_fuse([[], []], top_n=5) == []


def _result(i: int, content_len: int = 100) -> dict:
    return {
        "chunk_id": f"c{i}",
        "content": "字" * content_len,
        "score": 0.9,
        "modality": "text",
        "filename": f"文档{i}.md",
        "file_type": "md",
        "page_no": i,
        "slide_no": None,
        "start_ts": None,
        "end_ts": None,
        "asset_id": None,
    }


def test_context_budget_trimming(monkeypatch):
    # 每条约 50 token（100 字 / 2），预算 120 → 能放 2 条
    import app.generation.context_builder as cb

    monkeypatch.setattr(
        cb, "get_settings", lambda: type("S", (), {"context_token_budget": 120})()
    )
    results = [_result(i) for i in range(5)]
    context, refs = build_context(results)
    assert len(refs) == 2
    assert "[1]" in context and "[3]" not in context


def test_context_keeps_at_least_first(monkeypatch):
    import app.generation.context_builder as cb

    # 预算极小也应保留第一条
    monkeypatch.setattr(
        cb, "get_settings", lambda: type("S", (), {"context_token_budget": 1})()
    )
    _, refs = build_context([_result(1, content_len=1000)])
    assert len(refs) == 1


def test_context_ref_metadata_locator():
    r = _result(1)
    r["start_ts"], r["end_ts"] = 61.0, 90.0
    _, refs = build_context([r])
    assert refs[0]["start_ts"] == 61.0
    assert refs[0]["ref_id"] == 1
