"""技能生命周期管理模块。

提供对 SQLite skills 表的完整生命周期操作：
- create_skill / update_skill / delete_skill / list_my_skills / bump_usage
- suggest_skill_after_task：在一轮对话结束后调用 LLM 判断是否提炼出可复用技能。

存储约定：
- skills 表结构为 (id TEXT PRIMARY KEY, data TEXT)，data 是整行 JSON。
- 新写入的技能，其 id（uuid hex 前 12 位）只存在主键列中；
  data JSON 内含 name/description/content/source/version/usage_count/enabled/created_at/updated_at。

数据存取说明（为什么不用 db.load_skills/save_skills）：
- db.load_skills() 只 SELECT data 列，取不到主键 id；
- db.save_skills() 是全表 DELETE 后重写，属于"整表覆盖写"，在并发/多进程场景下
  会把别的进程刚插入的记录一起删掉，且有读-改-写竞态风险。
因此本模块所有单条读写都走 db._get_conn() 拿 db 模块自己的连接，执行精确的单行 SQL，
与 db.py 内部实现方式保持一致（连接工厂、事务风格均复用 db 模块）。
"""

import json
import re
import uuid
from datetime import datetime
from typing import Any, Callable, Optional

import db

# 字段长度上限（与校验规则保持一致）
MAX_NAME_LEN = 60
MAX_DESC_LEN = 300
MAX_CONTENT_LEN = 8000

# 不允许通过 update_skill 外部覆盖的内部维护字段
_PROTECTED_FIELDS = {"id", "version", "usage_count", "fail_count", "created_at", "updated_at"}


def _now() -> str:
    """当前时间（本地时区 ISO 8601，秒精度）。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _parse_data(raw: str) -> Optional[dict]:
    """解析 data 列的 JSON 字符串，失败或非对象时返回 None。"""
    try:
        obj = json.loads(raw)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _fetch_skill(skill_id: str) -> Optional[tuple[str, dict]]:
    """按 id 读取一条技能原始记录，返回 (id, data_dict)；不存在返回 None。"""
    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT id, data FROM skills WHERE id = ?", (skill_id,)
        ).fetchone()
    if row is None:
        return None
    data = _parse_data(row["data"]) or {}
    return row["id"], data


def _skill_names(exclude_id: Optional[str] = None) -> set[str]:
    """收集所有技能的名称（用于查重），可排除指定 id 自身。"""
    names: set[str] = set()
    with db._get_conn() as conn:
        rows = conn.execute("SELECT id, data FROM skills").fetchall()
    for r in rows:
        if exclude_id is not None and r["id"] == exclude_id:
            continue
        data = _parse_data(r["data"])
        if data and data.get("name"):
            names.add(str(data["name"]).strip())
    return names


def create_skill(name: str, description: str = "", content: str = "", source: str = "manual") -> dict:
    """创建技能。

    校验规则（任一不满足即返回 {'ok': False, 'error': '...'}，不写库）：
    - name 非空、content 非空；
    - name 长度 ≤ 60、description 长度 ≤ 300、content 长度 ≤ 8000（按字符计）；
    - name 不能与已有技能重名（重名返回 error='技能已存在'）。

    成功后写入 skills 表，id 取 uuid4().hex 前 12 位，
    data JSON 初始字段：name/description/content/source/version=1/usage_count=0/
    enabled=true/created_at/updated_at。
    """
    name = (name or "").strip()
    description = (description or "").strip()
    content = content or ""
    source = (source or "manual").strip() or "manual"

    # ---- 参数校验（顺序与需求一致）----
    if not name:
        return {"ok": False, "error": "技能名称不能为空"}
    if not content.strip():
        return {"ok": False, "error": "技能内容不能为空"}
    if len(name) > MAX_NAME_LEN:
        return {"ok": False, "error": f"技能名称长度不能超过{MAX_NAME_LEN}个字符"}
    if len(description) > MAX_DESC_LEN:
        return {"ok": False, "error": f"技能描述长度不能超过{MAX_DESC_LEN}个字符"}
    if len(content) > MAX_CONTENT_LEN:
        return {"ok": False, "error": f"技能内容长度不能超过{MAX_CONTENT_LEN}个字符"}

    # ---- 重名检查 ----
    if name in _skill_names():
        return {"ok": False, "error": "技能已存在"}

    now = _now()
    payload: dict[str, Any] = {
        "name": name,
        "description": description,
        "content": content,
        "source": source,
        "version": 1,
        "usage_count": 0,
        "enabled": True,
        "created_at": now,
        "updated_at": now,
    }
    skill_id = uuid.uuid4().hex[:12]
    with db._get_conn() as conn:
        conn.execute(
            "INSERT INTO skills (id, data) VALUES (?, ?)",
            (skill_id, json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()
    return {"ok": True, "skill_id": skill_id, "skill": {**payload, "id": skill_id}}


def update_skill(skill_id: str, **fields: Any) -> dict:
    """按 id 更新技能。

    fields 中除内部维护字段（id/version/usage_count/fail_count/created_at/updated_at）
    外的键会写进 data JSON（含 name/description/content/source/enabled 及扩展字段），
    更新成功后 version 自动 +1、updated_at 刷新。
    修改 name 时会重新做重名与长度校验。
    """
    current = _fetch_skill(skill_id)
    if current is None:
        return {"ok": False, "error": "技能不存在"}
    _, data = current

    # ---- 过滤受保护字段，并做规范化 ----
    patch: dict[str, Any] = {}
    for k, v in fields.items():
        if k in _PROTECTED_FIELDS:
            continue  # 内部计数/时间戳不允许外部直接改
        if v is None:
            continue
        if k == "name":
            v = str(v).strip()
            if not v:
                return {"ok": False, "error": "技能名称不能为空"}
            if len(v) > MAX_NAME_LEN:
                return {"ok": False, "error": f"技能名称长度不能超过{MAX_NAME_LEN}个字符"}
        elif k == "description":
            v = str(v).strip()
            if len(v) > MAX_DESC_LEN:
                return {"ok": False, "error": f"技能描述长度不能超过{MAX_DESC_LEN}个字符"}
        elif k == "content":
            v = str(v)
            if not v.strip():
                return {"ok": False, "error": "技能内容不能为空"}
            if len(v) > MAX_CONTENT_LEN:
                return {"ok": False, "error": f"技能内容长度不能超过{MAX_CONTENT_LEN}个字符"}
        elif k == "enabled":
            v = bool(v)
        elif k == "source":
            v = str(v).strip() or "manual"
        patch[k] = v

    # 改名时排除自身做重名检查
    if "name" in patch and patch["name"] in _skill_names(exclude_id=skill_id):
        return {"ok": False, "error": "技能已存在"}

    if not patch:
        # 没有有效字段可更新，原样返回不 bump 版本（返回结构保持一致，含 version）
        return {"ok": True, "skill_id": skill_id, "version": int(data.get("version", 0)),
                "skill": {**data, "id": skill_id}, "changed": False}

    data.update(patch)
    data["version"] = int(data.get("version", 0)) + 1
    data["updated_at"] = _now()
    with db._get_conn() as conn:
        conn.execute(
            "UPDATE skills SET data = ? WHERE id = ?",
            (json.dumps(data, ensure_ascii=False), skill_id),
        )
        conn.commit()
    return {"ok": True, "skill_id": skill_id, "version": data["version"],
            "skill": {**data, "id": skill_id}, "changed": True}


def delete_skill(skill_id: str) -> dict:
    """按 id 删除技能；不存在返回 {'ok': False, 'error': '技能不存在'}。"""
    with db._get_conn() as conn:
        cur = conn.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
        conn.commit()
    if cur.rowcount == 0:
        return {"ok": False, "error": "技能不存在"}
    return {"ok": True, "skill_id": skill_id}


def list_my_skills() -> list[dict]:
    """返回全部技能：data JSON 解析后补上主键 id（按插入顺序）。"""
    items: list[dict] = []
    with db._get_conn() as conn:
        rows = conn.execute("SELECT id, data FROM skills ORDER BY rowid").fetchall()
    for r in rows:
        data = _parse_data(r["data"])
        if data is None:
            continue
        data["id"] = r["id"]  # 以主键列为准
        items.append(data)
    return items


def bump_usage(skill_id: str, failed: bool = False) -> None:
    """技能被调用一次：usage_count +1；failed=True 时另记 data['fail_count'] +1。

    技能不存在时静默忽略（函数签名返回 None）。
    """
    try:
        current = _fetch_skill(skill_id)
        if current is None:
            return
        _, data = current
        data["usage_count"] = int(data.get("usage_count", 0)) + 1
        if failed:
            data["fail_count"] = int(data.get("fail_count", 0)) + 1
        with db._get_conn() as conn:
            conn.execute(
                "UPDATE skills SET data = ? WHERE id = ?",
                (json.dumps(data, ensure_ascii=False), skill_id),
            )
            conn.commit()
    except Exception as exc:  # 记录类操作不抛给上层
        print(f"[ERROR] 技能使用计数更新失败：{exc}", flush=True)


def _extract_json_object(text: str) -> Optional[dict]:
    """容错解析 LLM 输出：剥离 ```json ... ``` 等 markdown 围栏与前后杂文，取首个 {...}。"""
    if not text or not isinstance(text, str):
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)  # 贪婪匹配到最后一个 }
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def suggest_skill_after_task(
    user_request: str,
    final_answer: str,
    llm_call: Callable[[list[dict]], str],
) -> Optional[dict]:
    """判断本轮对话是否蕴含可复用流程/方法论，是则给出技能建议。

    - llm_call：外部传入的可调用对象，入参为 OpenAI 风格 messages 列表
      （本函数只发一条 role='user' 的中文提示词），返回回答字符串。
    - 返回：LLM 判定包含可复用方法时返回
      {'name', 'description', 'content', 'confidence'(0-1)}；
      判定不包含时返回 {'skip': True}；LLM 输出无法解析成合法 JSON
      或关键字段缺失时返回 None。
    - 容错：自动剥离 ```json 代码围栏、容忍前后多余文字。
    """
    if not user_request or not final_answer:
        return None

    prompt = (
        "你是一名\"技能提取器\"。请分析下面这轮\"用户请求\"与\"助手最终回答\"，"
        "判断其中是否包含**可复用的流程/方法论**（例如可以套用到后续相似任务的"
        "操作步骤、规则、技巧、检查清单或工作流）。\n\n"
        "输出要求（只输出 JSON，不要用 markdown 代码块包裹，不要输出其他文字）：\n"
        "1) 如果包含可复用方法，输出如下 JSON：\n"
        "{\"name\": \"技能名称，简短概括，不超过60字\", "
        "\"description\": \"技能描述，不超过300字\", "
        "\"content\": \"可复用的步骤/方法论正文，分步骤写清楚，不超过2000字\", "
        "\"confidence\": 0到1之间的小数（表示你的把握）}\n"
        "2) 如果不包含（如一次性问答、寒暄、闲聊、纯信息查询、无通用方法），输出：\n"
        "{\"skip\": true}\n\n"
        f"用户请求：\n{user_request}\n\n助手最终回答：\n{final_answer}"
    )

    try:
        raw = llm_call([{"role": "user", "content": prompt}])
    except Exception:
        return None  # LLM 调用异常一律视为无法建议

    obj = _extract_json_object(raw)
    if obj is None:
        return None

    # LLM 明确给出 skip 标记 → 不提炼
    if obj.get("skip") is True:
        return {"skip": True}

    # 提取并规范化三个字段
    name = str(obj.get("name") or "").strip()
    description = str(obj.get("description") or "").strip()
    content = str(obj.get("content") or "").strip()
    if not name or not content:
        return None  # 关键字段缺失，视为无效输出

    # 截断到创建技能允许的长度上限，避免后续 create_skill 失败
    name = name[:MAX_NAME_LEN]
    description = description[:MAX_DESC_LEN]
    content = content[:MAX_CONTENT_LEN]

    # confidence 归一化到 [0, 1]
    try:
        confidence = float(obj.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    return {
        "name": name,
        "description": description,
        "content": content,
        "confidence": confidence,
    }
