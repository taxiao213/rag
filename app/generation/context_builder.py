"""上下文组装：token 预算内贪心填充，分配引用编号 [1][2]...，输出引用元数据映射。"""

from app.chunking.chunker import estimate_tokens
from app.config import get_settings


def build_context(results: list[dict]) -> tuple[str, list[dict]]:
    """检索结果 → (拼接上下文文本, 引用列表)。

    引用列表每项：{ref_id, chunk_id, filename, page_no/slide_no/start_ts..., modality}
    """
    budget = get_settings().context_token_budget
    used = 0
    parts: list[str] = []
    refs: list[dict] = []

    for i, r in enumerate(results, start=1):
        tokens = estimate_tokens(r["content"])
        if used + tokens > budget and parts:
            break  # 至少保留第一条；超出预算停止填充
        used += tokens
        parts.append(f"[{i}] 来源《{r['filename']}》{_locator(r)}\n{r['content']}")
        refs.append(
            {
                "ref_id": i,
                "chunk_id": r["chunk_id"],
                "filename": r["filename"],
                "file_type": r["file_type"],
                "modality": r["modality"],
                "page_no": r.get("page_no"),
                "slide_no": r.get("slide_no"),
                "start_ts": r.get("start_ts"),
                "end_ts": r.get("end_ts"),
                "asset_id": r.get("asset_id"),
            }
        )
    return "\n\n---\n\n".join(parts), refs


def _locator(r: dict) -> str:
    """生成位置提示文本：页码/幻灯片/视频时间段。"""
    if r.get("start_ts") is not None:
        return f"（视频 {r['start_ts']:.0f}s-{r['end_ts']:.0f}s）" if r.get("end_ts") else ""
    if r.get("page_no"):
        return f"（第 {r['page_no']} 页）"
    if r.get("slide_no"):
        return f"（第 {r['slide_no']} 张幻灯片）"
    return ""
