"""RAG embedding 模块。

职责：
- 提供统一的文本向量化接口（本地 sentence-transformers 模型）。
- 提供余弦相似度计算（内存检索用）。

设计原则：
- 本地模型优先，零外部向量服务依赖（可离线打包运行）。
- 首次调用时自动下载模型并缓存到 data/models/。
"""

import os
import sys
from pathlib import Path

import numpy as np

# 模型缓存目录：
# - 开发模式：项目根 data/models/
# - 打包模式：用户数据目录 data/models/（_MEIPASS 是只读临时目录，不可写）
#   与 db.py 的 USER_DATA_DIR 保持一致，卸载应用后模型缓存不丢失。
PACKAGED = hasattr(sys, "_MEIPASS")
if PACKAGED:
    _user_data = Path(
        os.environ.get("APPDATA", Path.home() / "AppData/Roaming")
    ) / "taofei_app"
else:
    _user_data = Path(__file__).resolve().parent.parent

MODEL_CACHE_DIR = _user_data / "data" / "models"
MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

LOCAL_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

_local_model = None


def _load_local_model():
    """懒加载本地 embedding 模型（进程内只加载一次）。"""
    global _local_model
    if _local_model is not None:
        return _local_model
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("sentence-transformers 未安装，请执行 pip install sentence-transformers") from exc
    _local_model = SentenceTransformer(LOCAL_MODEL_NAME, cache_folder=str(MODEL_CACHE_DIR))
    return _local_model


def is_loaded() -> bool:
    """模型是否已加载到内存（供 /api/health 与前端启动 loading 使用）。"""
    return _local_model is not None


def get_embedding(text: str) -> list[float]:
    """获取文本向量（L2 归一化后的 list[float]）。

    空文本返回全零向量，保证检索时不会因空输入崩溃。
    """
    if not text:
        return [0.0] * EMBEDDING_DIM
    model = _load_local_model()
    vec = model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
    return vec.tolist()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度；任一向量为零向量时返回 0。"""
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    if norm == 0:
        return 0.0
    return float(np.dot(a, b) / norm)
