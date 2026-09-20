"""导入即注册所有 parser（副作用导入）。"""

from app.parsers.base import (  # noqa: F401
    Block,
    BlockType,
    ParseInput,
    ParsedDocument,
    get_parser,
    parse,
    register,
)

# 副作用导入：触发各 @register 装饰器
from app.parsers import (  # noqa: F401
    docx_parser,
    image_parser,
    pdf_parser,
    pptx_parser,
    text_parser,
    xlsx_parser,
)
