"""集中管理的 prompt 模板（与 rag_prompt.py 分离，避免 main.py 膨胀）。"""

MEMORY_SUMMARY_SYSTEM = (
    "你是记忆提炼助手。根据【用户请求】和【Agent 结论】，提取一条可长期复用的记忆。"
    "要求：\n"
    "1. summary：一句话总结请求与核心结论（不超过 80 字）\n"
    "2. facts：列出 1-3 条可被未来引用的具体事实（路径、技术选型、决策、结果等）\n"
    "只输出 JSON，格式：{\"summary\": \"...\", \"facts\": [\"...\", \"...\"]}"
)


def build_memory_summary_messages(user_request: str, final_answer: str) -> list[dict]:
    """构造摘要生成的 messages。final_answer 超长时截断，避免 token 浪费。"""
    answer = final_answer if final_answer else "（无结论）"
    if len(answer) > 4000:
        answer = answer[:4000] + "…"
    return [
        {"role": "system", "content": MEMORY_SUMMARY_SYSTEM},
        {"role": "user", "content": f"【用户请求】\n{user_request}\n\n【Agent 结论】\n{answer}"},
    ]
