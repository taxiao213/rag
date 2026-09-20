"""PDF 解析：文字型按页提取文本+内嵌图片；扫描件检测后整页标记走 VLM 管线。

策略：
- pymupdf 逐页提取文本；页均字符数低于阈值判为扫描件
- 文字型：按页产出 TEXT 块（页内文本合并且保留页码），内嵌图片抽出为 IMAGE_REF 块
- 扫描件/混合件：needs_ocr 的页整页渲染为 PNG，产出 IMAGE_REF 块（asset_type=scanned_page），
  由 indexing pipeline 送 VLM 生成描述后入索引——免独立 OCR 管线
"""

import io

import fitz  # pymupdf

from app.parsers.base import Block, BlockType, ParseInput, ParsedDocument, register

# 页文本字符数低于该值视为扫描页
SCAN_MIN_CHARS = 50
# 内嵌图片最小尺寸（像素），过小的图标/装饰不抽
MIN_IMAGE_DIM = 200


@register("pdf")
def parse_pdf(input_: ParseInput) -> ParsedDocument:
    pdf = fitz.open(stream=input_.data, filetype="pdf")
    doc = ParsedDocument()
    try:
        for page in pdf:
            text = page.get_text("text").strip()
            is_scanned = len(text) < SCAN_MIN_CHARS

            if is_scanned:
                doc.needs_ocr = True
                pix = page.get_pixmap(dpi=150)
                doc.blocks.append(
                    Block(
                        type=BlockType.IMAGE_REF,
                        content=f"[扫描页 第{page.number + 1}页]",
                        page_no=page.number + 1,
                        asset_bytes=pix.tobytes("png"),
                        asset_ext="png",
                    )
                )
            else:
                doc.blocks.append(
                    Block(
                        type=BlockType.TEXT,
                        content=text,
                        page_no=page.number + 1,
                    )
                )

            # 内嵌图片（仅文字型页抽取；扫描页整页已覆盖）
            if not is_scanned:
                for img in page.get_images(full=True):
                    try:
                        xref = img[0]
                        info = pdf.extract_image(xref)
                        w, h = info.get("width", 0), info.get("height", 0)
                        if w < MIN_IMAGE_DIM or h < MIN_IMAGE_DIM:
                            continue
                        doc.blocks.append(
                            Block(
                                type=BlockType.IMAGE_REF,
                                content=f"[内嵌图片 第{page.number + 1}页]",
                                page_no=page.number + 1,
                                asset_bytes=info["image"],
                                asset_ext=info.get("ext", "png"),
                            )
                        )
                    except Exception:
                        continue  # 单张图片失败不阻塞整页
    finally:
        pdf.close()
    return doc
