"""docx 解析：保留 heading 层级，内嵌图片抽出为 IMAGE_REF 块。"""

import io

from docx import Document as DocxDocument
from docx.document import Document as _Doc
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.parsers.base import Block, BlockType, ParseInput, ParsedDocument, register

MIN_IMAGE_DIM = 200


def _iter_blocks(parent: _Doc):
    """按文档顺序产出段落与表格。"""
    from docx.oxml.ns import qn

    for child in parent.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            yield Table(child, parent)


def _table_to_markdown(table: Table) -> str:
    rows = []
    for row in table.rows:
        cells = [c.text.strip().replace("\n", " ") for c in row.cells]
        rows.append("| " + " | ".join(cells) + " |")
    if len(rows) > 1:
        cols = len(table.columns)
        rows.insert(1, "|" + " --- |" * cols)
    return "\n".join(rows)


@register("docx")
def parse_docx(input_: ParseInput) -> ParsedDocument:
    d = DocxDocument(io.BytesIO(input_.data))
    doc = ParsedDocument()
    heading_level = 0
    heading_text = ""

    for item in _iter_blocks(d):
        if isinstance(item, Paragraph):
            style = item.style.name if item.style else ""
            if style.startswith("Heading"):
                try:
                    heading_level = int(style.split()[-1])
                except (ValueError, IndexError):
                    heading_level = 1
                heading_text = item.text.strip()
                if heading_text:
                    doc.blocks.append(
                        Block(
                            type=BlockType.TEXT,
                            content=heading_text,
                            heading_level=heading_level,
                            heading_text=heading_text,
                        )
                    )
            elif item.text.strip():
                doc.blocks.append(
                    Block(
                        type=BlockType.TEXT,
                        content=item.text.strip(),
                        heading_level=heading_level,
                        heading_text=heading_text,
                    )
                )
        elif isinstance(item, Table):
            md = _table_to_markdown(item)
            if md:
                doc.blocks.append(
                    Block(
                        type=BlockType.TABLE,
                        content=md,
                        heading_level=heading_level,
                        heading_text=heading_text,
                    )
                )

    # 内嵌图片
    seen: set[bytes] = set()
    for rel in d.part.rels.values():
        if "image" not in rel.reltype:
            continue
        blob = rel.target_part.blob
        if blob in seen:
            continue
        seen.add(blob)
        doc.blocks.append(
            Block(
                type=BlockType.IMAGE_REF,
                content="[内嵌图片]",
                asset_bytes=blob,
                asset_ext=rel.target_part.partname.ext or "png",
            )
        )
    return doc
