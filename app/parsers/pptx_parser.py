"""pptx 解析：每页一个块（文本 + 备注），页内图片抽出为 IMAGE_REF 块，slide_no 入元数据。"""

import io

from pptx import Presentation

from app.parsers.base import Block, BlockType, ParseInput, ParsedDocument, register

MIN_IMAGE_DIM = 200


@register("pptx")
def parse_pptx(input_: ParseInput) -> ParsedDocument:
    prs = Presentation(io.BytesIO(input_.data))
    doc = ParsedDocument()

    for idx, slide in enumerate(prs.slides, start=1):
        parts: list[str] = []
        # 文本形状
        for shape in slide.shapes:
            if shape.has_text_frame:
                text = shape.text_frame.text.strip()
                if text:
                    parts.append(text)
        # 备注
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                parts.append(f"[备注]\n{notes}")

        content = "\n".join(parts)
        if content:
            doc.blocks.append(
                Block(type=BlockType.TEXT, content=content, slide_no=idx)
            )

        # 页内图片
        for shape in slide.shapes:
            if shape.shape_type == 13:  # PICTURE
                try:
                    image = shape.image
                    if image.size[0] < MIN_IMAGE_DIM or image.size[1] < MIN_IMAGE_DIM:
                        continue
                    doc.blocks.append(
                        Block(
                            type=BlockType.IMAGE_REF,
                            content=f"[幻灯片图片 第{idx}页]",
                            slide_no=idx,
                            asset_bytes=image.blob,
                            asset_ext=image.ext or "png",
                        )
                    )
                except Exception:
                    continue
    return doc
