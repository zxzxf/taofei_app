"""RAG prompt 拼装模块。

职责：
- 把检索到的分块格式化为带来源标注的上下文文本。
"""


def build_rag_context(query: str, chunks: list[dict]) -> str:
    """把检索结果拼装为 RAG 提示词上下文。

    无分块时原样返回 query，保证调用方行为一致。
    """
    if not chunks:
        return query
    parts = ["请根据以下参考资料回答问题。参考资料可能包含与问题无关的内容，请只依据相关资料作答。", ""]
    for i, c in enumerate(chunks, 1):
        src = c.get("source_path", "未知来源")
        parts.append(f"--- 资料 {i}（来源：{src}）---")
        parts.append(c.get("content", ""))
        parts.append("")
    parts.append(f"用户问题：{query}")
    return "\n".join(parts)
