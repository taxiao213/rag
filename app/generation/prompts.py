"""Prompt 模板：RAG 问答系统提示，强制引用标注。"""

SYSTEM_PROMPT = """你是一个基于企业知识库的问答助手。规则：
1. 只能基于下方提供的「知识库上下文」回答，不得编造上下文中没有的信息。
2. 回答中的每个论断必须用引用编号标注来源，格式为 [1]、[2]，与上下文中的编号一一对应。
3. 上下文中没有相关信息时，直接说明"知识库中未找到相关内容"，不要强行回答。
4. 使用与用户相同的语言回答，表达简洁、结构化。

知识库上下文：
{context}
"""


def build_messages(query: str, context: str, history: list[dict] | None = None) -> list[dict]:
    """组装消息：系统提示（含知识库上下文）+ 历史对话（最近若干轮）+ 当前问题。"""
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT.format(context=context)}
    ]
    for msg in history or []:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": query})
    return messages
