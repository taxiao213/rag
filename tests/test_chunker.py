"""切片器单元测试：标题注入、token 目标合并、超长拆分、表格整块、图片独立成 chunk。"""

import os

os.environ.setdefault("API_KEY_QUERY", "q")
os.environ.setdefault("API_KEY_ADMIN", "a")
os.environ.setdefault("APP_SECRET", "s")

from app.chunking.chunker import chunk_blocks, estimate_tokens
from app.parsers.base import Block, BlockType


def _text_block(content: str, heading: str = "") -> Block:
    return Block(type=BlockType.TEXT, content=content, heading_text=heading)


def test_heading_context_injected():
    blocks = [_text_block("正文第一段。", heading="验收标准"), _text_block("正文第二段。")]
    chunks = chunk_blocks(blocks)
    assert chunks[0].content.startswith("[验收标准]")


def test_small_paragraphs_merged():
    blocks = [_text_block("短段落" + str(i)) for i in range(5)]
    chunks = chunk_blocks(blocks)
    assert len(chunks) == 1
    assert "短段落0" in chunks[0].content and "短段落4" in chunks[0].content


def test_oversized_block_split():
    long_text = "这是一个测试句子。" * 200  # 远超 max_tokens
    blocks = [_text_block(long_text)]
    chunks = chunk_blocks(blocks)
    assert len(chunks) > 1
    for c in chunks:
        assert estimate_tokens(c.content) <= 550  # 留一点估算余量


def test_table_block_not_split():
    table = Block(type=BlockType.TABLE, content="| a | b |\n| --- | --- |\n" + "| x | y |\n" * 30)
    chunks = chunk_blocks([table])
    assert len(chunks) == 1
    assert chunks[0].content == table.content


def test_image_ref_independent_chunk():
    img = Block(
        type=BlockType.IMAGE_REF,
        content="[内嵌图片]",
        asset_bytes=b"\x89PNG",
        asset_ext="png",
    )
    chunks = chunk_blocks([_text_block("正文"), img])
    assert len(chunks) == 2
    assert chunks[1].modality == "image"
    assert chunks[1].asset_bytes == b"\x89PNG"


def test_flushes_between_merge_and_image():
    blocks = [
        _text_block("段一"),
        Block(type=BlockType.IMAGE_REF, content="[图]", asset_bytes=b"x", asset_ext="png"),
        _text_block("段二"),
    ]
    chunks = chunk_blocks(blocks)
    assert [c.modality for c in chunks] == ["text", "image", "text"]


def test_estimate_tokens_nonzero():
    assert estimate_tokens("ab") >= 1
    assert estimate_tokens("中文测试四个字") == 3
