"""parser 单元测试：txt/md 标题层级、pdf 扫描件检测、xlsx 表头注入、pptx 按页。"""

import io

import openpyxl
import pytest

import app.parsers  # noqa: F401 触发注册
from app.parsers import ParseInput, get_parser, parse


def test_txt_parser_headings():
    data = "# 标题一\n第一段内容。\n\n第二段内容。\n## 子标题\n子段内容。"
    doc = parse(ParseInput(data=data.encode(), filename="a.md", file_type="md"))
    assert len(doc.blocks) >= 2
    assert doc.blocks[0].heading_text == "标题一"
    assert any(b.heading_text == "子标题" for b in doc.blocks)


def test_txt_parser_paragraph_split():
    data = "段落一。\n\n段落二。"
    doc = parse(ParseInput(data=data.encode(), filename="a.txt", file_type="txt"))
    assert len(doc.blocks) == 2


def test_unregistered_extension_raises():
    with pytest.raises(ValueError, match="未注册"):
        get_parser("exe")


def test_xlsx_header_repeated_in_row_blocks():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "销售数据"
    ws.append(["区域", "销售额"])
    for i in range(50):
        ws.append([f"区域{i}", i * 100])
    buf = io.BytesIO()
    wb.save(buf)

    doc = parse(ParseInput(data=buf.getvalue(), filename="s.xlsx", file_type="xlsx"))
    # 50 行 / 20 行块 = 3 块，每块都应包含表头
    assert len(doc.blocks) == 3
    for b in doc.blocks:
        assert "| 区域 | 销售额 |" in b.content
        assert "销售数据" in b.content


def test_pdf_scanned_page_detection(monkeypatch):
    """构造文本极少的 PDF，验证标记 needs_ocr 且产出 IMAGE_REF 块。"""
    import fitz

    pdf = fitz.open()
    page = pdf.new_page()
    # 空页（无文本）
    buf = pdf.tobytes()
    pdf.close()

    doc = parse(ParseInput(data=buf, filename="scan.pdf", file_type="pdf"))
    assert doc.needs_ocr is True
    assert all(b.type.value == "image_ref" for b in doc.blocks)


def test_pdf_text_page_normal():
    """用 ASCII 文本构造文字型 PDF（fitz 默认字体不支持 CJK 渲染，仅用 ASCII 验证管线）。"""
    import fitz

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "This is a long enough English text to test text-based PDF parsing. " * 5)
    buf = pdf.tobytes()
    pdf.close()

    doc = parse(ParseInput(data=buf, filename="text.pdf", file_type="pdf"))
    assert doc.needs_ocr is False
    text_blocks = [b for b in doc.blocks if b.type.value == "text"]
    assert len(text_blocks) >= 1
    assert text_blocks[0].page_no == 1
    assert "long enough English text" in text_blocks[0].content
