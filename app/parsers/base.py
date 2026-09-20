"""解析层统一中间表示：所有 parser 输出 Block 流，切片器不感知文件格式。

新增格式 = 注册一个新 parser 函数，无需改动切片/索引管线。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class BlockType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    IMAGE_REF = "image_ref"
    TRANSCRIPT_SEGMENT = "transcript_segment"
    FRAME_REF = "frame_ref"


@dataclass
class Block:
    """一个语义单元。content 为纯文本/表格 Markdown；图片帧等以引用形式出现。"""

    type: BlockType
    content: str = ""
    # 溯源
    page_no: int | None = None
    slide_no: int | None = None
    start_ts: float | None = None
    end_ts: float | None = None
    # 图片/帧等二进制资产（bytes）与其存储提示
    asset_bytes: bytes | None = None
    asset_ext: str | None = None
    # 标题层级（切片器用于保持标题上下文）
    heading_level: int = 0
    heading_text: str = ""
    # 表格上下文（xlsx 表头注入用）
    table_header: str = ""


@dataclass
class ParsedDocument:
    blocks: list[Block] = field(default_factory=list)
    needs_ocr: bool = False


@dataclass
class ParseInput:
    """parser 输入：原始字节 + 来源信息。"""

    data: bytes
    filename: str
    file_type: str  # 规范化扩展名


ParserFn = Callable[[ParseInput], ParsedDocument]

_REGISTRY: dict[str, ParserFn] = {}


def register(*extensions: str) -> Callable[[ParserFn], ParserFn]:
    """装饰器：将 parser 注册到一组扩展名。"""

    def deco(fn: ParserFn) -> ParserFn:
        for ext in extensions:
            _REGISTRY[ext] = fn
        return fn

    return deco


def get_parser(file_type: str) -> ParserFn:
    ext = file_type.lower().lstrip(".")
    if ext not in _REGISTRY:
        raise ValueError(f"未注册的解析器: .{ext}")
    return _REGISTRY[ext]


def parse(input_: ParseInput) -> ParsedDocument:
    return get_parser(input_.file_type)(input_)
