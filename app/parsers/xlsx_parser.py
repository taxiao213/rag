"""xlsx 解析：逐 sheet 转 Markdown 表；小表整块，大表按行块切片且每块重复注入表头。

行块大小按估算 token 控制（目标 ~350 token/块），保证单独命中某行时上下文完整。
"""

import io

import openpyxl

from app.parsers.base import Block, BlockType, ParseInput, ParsedDocument, register

# 每行块的目标行数（可后续按 token 自适应，MVP 固定）
ROWS_PER_BLOCK = 20


def _row_to_cells(row) -> list[str]:
    return [str(c.value).strip() if c.value is not None else "" for c in row]


def _to_md(header: list[str], rows: list[list[str]]) -> str:
    def fmt(cells: list[str]) -> str:
        return "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |"

    lines = [fmt(header), "|" + " --- |" * len(header)]
    lines += [fmt(r) for r in rows]
    return "\n".join(lines)


@register("xlsx")
def parse_xlsx(input_: ParseInput) -> ParsedDocument:
    wb = openpyxl.load_workbook(io.BytesIO(input_.data), read_only=True, data_only=True)
    doc = ParsedDocument()
    try:
        for ws in wb.worksheets:
            rows_iter = ws.iter_rows()
            header_row = next(rows_iter, None)
            if header_row is None:
                continue
            header = _row_to_cells(header_row)
            header_md = _to_md(header, [])
            # 收集数据行
            data_rows = [_row_to_cells(r) for r in rows_iter]
            data_rows = [r for r in data_rows if any(c for c in r)]

            if not data_rows:
                doc.blocks.append(
                    Block(
                        type=BlockType.TABLE,
                        content=f"[工作表: {ws.title}]\n{header_md}",
                        table_header=header_md,
                    )
                )
                continue

            for i in range(0, len(data_rows), ROWS_PER_BLOCK):
                batch = data_rows[i : i + ROWS_PER_BLOCK]
                md = _to_md(header, batch)
                doc.blocks.append(
                    Block(
                        type=BlockType.TABLE,
                        content=f"[工作表: {ws.title} · 行{i + 2}-{i + 1 + len(batch)}]\n{md}",
                        table_header=header_md,
                    )
                )
    finally:
        wb.close()
    return doc
