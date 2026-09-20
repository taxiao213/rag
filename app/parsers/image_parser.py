"""图片解析：原图保留为资产，VLM 描述在 indexing pipeline 生成（此处只产出 IMAGE_REF 块）。"""

from app.parsers.base import Block, BlockType, ParseInput, ParsedDocument, register


@register("png", "jpg", "jpeg", "webp")
def parse_image(input_: ParseInput) -> ParsedDocument:
    return ParsedDocument(
        blocks=[
            Block(
                type=BlockType.IMAGE_REF,
                content=f"[图片文件: {input_.filename}]",
                asset_bytes=input_.data,
                asset_ext=input_.file_type,
            )
        ]
    )
