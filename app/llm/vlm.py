"""VLM 图片描述：prompt 要求客观描述内容 + 可见文字 + 图表数据，兼顾 OCR。"""

import base64

from app.llm.client import get_index_client, load_index_config

DESCRIBE_PROMPT = (
    "请客观描述这张图片的内容，要求：\n"
    "1. 概述图片主题和主要元素；\n"
    "2. 转录图片中可见的文字（原文转录，保持准确）；\n"
    "3. 如是图表/表格，描述其数据结构和关键数值；\n"
    "4. 如是界面截图，描述界面功能和关键信息；\n"
    "用简体中文，200 字以内。"
)

MIME_MAP = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}


async def describe_image(image_bytes: bytes, ext: str) -> str:
    client = await get_index_client()
    config = await load_index_config()
    mime = MIME_MAP.get(ext.lower(), "image/png")
    b64 = base64.b64encode(image_bytes).decode()
    resp = await client.chat(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": DESCRIBE_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            }
        ],
        model=config.vlm_model,
        max_tokens=512,
    )
    return resp["choices"][0]["message"]["content"].strip()
