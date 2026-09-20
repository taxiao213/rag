"""txt / md 解析：按标题行（# 语法）与空行切分为带层级的文本块。"""

import io

from app.parsers.base import Block, BlockType, ParseInput, ParsedDocument, register


def _heading_level(line: str) -> tuple[int, str] | None:
    stripped = line.lstrip()
    if stripped.startswith("#"):
        level = len(stripped) - len(stripped.lstrip("#"))
        if 1 <= level <= 6 and stripped[level : level + 1] == " ":
            return level, stripped[level:].strip()
    return None


@register("txt", "md")
def parse_text(input_: ParseInput) -> ParsedDocument:
    text = io.BytesIO(input_.data).read().decode("utf-8", errors="replace")
    doc = ParsedDocument()
    current: list[str] = []
    heading_level = 0
    heading_text = ""

    def flush() -> None:
        nonlocal current
        content = "\n".join(current).strip()
        if content:
            doc.blocks.append(
                Block(
                    type=BlockType.TEXT,
                    content=content,
                    heading_level=heading_level,
                    heading_text=heading_text,
                )
            )
        current = []

    for line in text.splitlines():
        h = _heading_level(line)
        if h:
            flush()
            heading_level, heading_text = h
        elif line.strip() == "":
            flush()
            heading_level, heading_text = 0, ""
        else:
            current.append(line)
    flush()
    return doc
