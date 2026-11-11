"""生成层降级行为测试：检索不可用时对话不阻断。"""

import json

from app.generation import generator as gen


class FakeClient:
    """记录收到的 messages，按序产出 token。"""

    def __init__(self):
        self.seen_messages = None

    async def chat_stream(self, messages, **kwargs):
        self.seen_messages = messages
        for t in ["答", "案"]:
            yield t


def _fake_client(client):
    async def get_client():
        return client

    return get_client


def _parse_tokens(events):
    tokens = []
    for ev in events:
        if not ev.startswith("data: ") or ev == "data: [DONE]\n\n":
            continue
        parsed = json.loads(ev[len("data: ") :].strip())
        if parsed.get("type") == "token":
            tokens.append(parsed["content"])
    return tokens


async def test_all_retrieval_failed_degrades_to_direct_answer(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("embedding 批次 0 重试 3 次仍失败")

    monkeypatch.setattr(gen, "hybrid_search", boom)
    monkeypatch.setattr(gen, "bm25_search", boom)
    fake = FakeClient()
    monkeypatch.setattr(gen, "get_chat_client", _fake_client(fake))

    events = [e async for e in gen.answer_stream(None, "测试问题")]
    tokens = "".join(_parse_tokens(events))

    assert "检索服务暂不可用" in tokens  # 开头有降级提示
    assert "答案" in tokens  # LLM 正常产出，未被阻断
    assert events[-1] == "data: [DONE]\n\n"  # 流正常收尾
    assert "知识库上下文" not in fake.seen_messages[0]["content"]  # 系统提示词切为直答模式


async def test_bm25_fallback_keeps_grounded_answer(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("qdrant 不可用")

    async def bm25_ok(session, query, **kwargs):
        return [
            {
                "chunk_id": "c1",
                "content": "知识库内容片段",
                "score": 1.0,
                "modality": "text",
                "document_id": "d1",
                "filename": "doc.md",
                "file_type": "md",
                "page_no": None,
                "slide_no": None,
                "start_ts": None,
                "end_ts": None,
                "asset_id": None,
            }
        ]

    monkeypatch.setattr(gen, "hybrid_search", boom)
    monkeypatch.setattr(gen, "bm25_search", bm25_ok)
    fake = FakeClient()
    monkeypatch.setattr(gen, "get_chat_client", _fake_client(fake))

    events = [e async for e in gen.answer_stream(None, "测试问题")]
    tokens = "".join(_parse_tokens(events))

    assert "检索服务暂不可用" not in tokens  # BM25 兜底成功，不提示降级
    assert "答案" in tokens
    assert "知识库上下文" in fake.seen_messages[0]["content"]  # 仍走知识库提示词
    refs_event = next(ev for ev in events if '"refs"' in ev)
    assert "doc.md" in refs_event  # 引用元数据正常下发


async def test_retrieval_success_unchanged(monkeypatch):
    async def ok(*args, **kwargs):
        return []

    monkeypatch.setattr(gen, "hybrid_search", ok)
    fake = FakeClient()
    monkeypatch.setattr(gen, "get_chat_client", _fake_client(fake))

    events = [e async for e in gen.answer_stream(None, "测试问题")]
    tokens = "".join(_parse_tokens(events))

    assert "检索服务暂不可用" not in tokens
    assert "答案" in tokens
    assert "知识库上下文" in fake.seen_messages[0]["content"]
    assert events[-1] == "data: [DONE]\n\n"
