"""LLM 错误转用户可读文案的纯函数测试。"""

import httpx

from app.llm.client import describe_llm_error


def _status_error(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://example.com/v1/embeddings")
    resp = httpx.Response(status, request=req)
    return httpx.HTTPStatusError(f"{status}", request=req, response=resp)


def test_describe_401_as_auth_failure():
    msg = describe_llm_error(_status_error(401))
    assert "401" in msg and "API Key" in msg


def test_describe_404_as_config_hint():
    msg = describe_llm_error(_status_error(404))
    assert "404" in msg and ("地址" in msg or "模型" in msg)


def test_describe_429_as_rate_limit():
    msg = describe_llm_error(_status_error(429))
    assert "429" in msg and "频率" in msg


def test_describe_connect_error_as_network():
    msg = describe_llm_error(httpx.ConnectError("connection refused"))
    assert "网络" in msg or "连接" in msg


def test_describe_timeout():
    msg = describe_llm_error(httpx.ReadTimeout("timed out"))
    assert "超时" in msg


def test_describe_unknown_includes_detail():
    msg = describe_llm_error(RuntimeError("embedding 批次 0 重试 3 次仍失败"))
    assert "embedding" in msg


def test_describe_uses_cause_of_wrapped_runtime_error():
    wrapped = RuntimeError("embedding 批次 0 重试 3 次仍失败")
    wrapped.__cause__ = _status_error(401)
    msg = describe_llm_error(wrapped)
    assert "401" in msg and "API Key" in msg


def test_describe_streaming_response_never_crashes(monkeypatch):
    """流式响应未读 body 时 .text 会抛 ResponseNotRead，describe 必须兜底不崩。"""
    req = httpx.Request("POST", "https://example.com/v1/chat/completions")
    resp = httpx.Response(400, request=req)

    def _raise(_self):
        raise httpx.ResponseNotRead()

    monkeypatch.setattr(httpx.Response, "text", property(_raise))
    err = httpx.HTTPStatusError("400", request=req, response=resp)
    msg = describe_llm_error(err)  # 不应抛异常
    assert "400" in msg  # 状态码仍然可见
