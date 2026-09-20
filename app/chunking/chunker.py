"""切片器：Block 流 → Chunk。

规则：
- TEXT/TABLE 块按 token 目标合并小段落、拆分超长块，标题上下文注入每个 chunk 前缀
- IMAGE_REF/FRAME_REF/TRANSCRIPT_SEGMENT 块独立成 chunk（内容后续由 pipeline 填充 VLM 描述/转录）
- 表格块不再拆分（parser 已按行块切好）
- token 估算：按字符数 /2 粗估（中英混合场景误差可接受，避免引入分词器依赖）
"""

from app.parsers.base import Block, BlockType

from app.config import get_settings


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 2)


class ChunkRecord:
    """切片结果（尚未入库）。与 chunk 表字段对应。"""

    __slots__ = (
        "content",
        "modality",
        "page_no",
        "slide_no",
        "start_ts",
        "end_ts",
        "asset_bytes",
        "asset_ext",
        "block",
    )

    def __init__(self, *, content: str, modality: str, block: Block) -> None:
        self.content = content
        self.modality = modality
        self.page_no = block.page_no
        self.slide_no = block.slide_no
        self.start_ts = block.start_ts
        self.end_ts = block.end_ts
        self.asset_bytes = block.asset_bytes
        self.asset_ext = block.asset_ext
        self.block = block


def _with_heading(block: Block, content: str) -> str:
    if block.heading_text:
        return f"[{block.heading_text}]\n{content}"
    return content


def chunk_blocks(blocks: list[Block]) -> list[ChunkRecord]:
    settings = get_settings()
    target = settings.chunk_token_target
    max_tokens = settings.chunk_token_max

    chunks: list[ChunkRecord] = []
    buffer: list[str] = []
    buffer_block: Block | None = None
    buffer_tokens = 0

    def flush() -> None:
        nonlocal buffer, buffer_block, buffer_tokens
        if buffer and buffer_block is not None:
            chunks.append(
                ChunkRecord(
                    content="\n\n".join(buffer),
                    modality="text",
                    block=buffer_block,
                )
            )
        buffer, buffer_block, buffer_tokens = [], None, 0

    for block in blocks:
        if block.type in (
            BlockType.IMAGE_REF,
            BlockType.FRAME_REF,
            BlockType.TRANSCRIPT_SEGMENT,
        ):
            flush()
            modality = (
                "image" if block.type is BlockType.IMAGE_REF else "video_transcript"
            )
            if block.type is BlockType.FRAME_REF:
                modality = "video_frame"
            chunks.append(ChunkRecord(content=block.content, modality=modality, block=block))
            continue

        # 表格块：parser 已按行块切好，直接独立成 chunk
        if block.type is BlockType.TABLE:
            flush()
            chunks.append(
                ChunkRecord(
                    content=block.content,
                    modality="text",
                    block=block,
                )
            )
            continue

        # TEXT 块
        content = _with_heading(block, block.content)
        tokens = estimate_tokens(content)

        # 超长块硬拆分（按句子近似拆分）
        if tokens > max_tokens:
            flush()
            for piece in _split_long(content, max_tokens):
                chunks.append(ChunkRecord(content=piece, modality="text", block=block))
            continue

        # 合并小段落，达到 target 即 flush
        if buffer_tokens + tokens > target and buffer:
            flush()
        if buffer_block is None:
            buffer_block = block
        buffer.append(content)
        buffer_tokens += tokens
        if buffer_tokens >= target:
            flush()

    flush()
    return chunks


def _split_long(content: str, max_tokens: int) -> list[str]:
    """按中文/英文句号、换行切分超长文本，近似均分到 max_tokens 以内。"""
    import re

    sentences = re.split(r"(?<=[。！？.!?\n])", content)
    pieces: list[str] = []
    current = ""
    for s in sentences:
        if estimate_tokens(current + s) > max_tokens and current:
            pieces.append(current.strip())
            current = s
        else:
            current += s
    if current.strip():
        pieces.append(current.strip())
    return [p for p in pieces if p]
