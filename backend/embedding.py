"""RAG embedding 模块。

职责：
- 提供统一的文本向量化接口（本地 sentence-transformers 模型）。
- 提供余弦相似度计算（内存检索用）。

设计原则：
- 本地模型优先，零外部向量服务依赖（可离线打包运行）。
- 首次调用时自动下载模型并缓存到 data/models/。
- 当本地模型不可用时，使用纯 Python 实现的字符 n-gram hash embedding 兜底，
  保证知识库上传、RAG 检索在离线环境仍可运行（效果弱于深度学习模型）。
"""

import os
import sys
from pathlib import Path

import numpy as np

# HuggingFace 镜像 endpoint：国内环境无法直连 huggingface.co 时可配置
# .env 中设置 HF_ENDPOINT=https://hf-mirror.com
HF_ENDPOINT = os.environ.get("HF_ENDPOINT", "").strip()

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
_use_fallback = False  # 当 sentence-transformers 模型不可用时启用兜底 embedding


def _fallback_embedding(text: str) -> list[float]:
    """纯 Python 实现的字符 n-gram hash embedding（离线兜底方案）。

    将文本按字符 2-gram 切片后 hash 到 EMBEDDING_DIM 维稀疏向量，
    再 L2 归一化。无需外部模型或网络，适合完全离线环境。
    """
    if not text:
        return [0.0] * EMBEDDING_DIM
    vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    s = text.strip()
    for i in range(len(s) - 1):
        bigram = s[i : i + 2]
        idx = hash(bigram) % EMBEDDING_DIM
        vec[idx] += 1.0
    # 同时加入单字信息，避免短文本全 0
    for ch in s:
        idx = hash(ch) % EMBEDDING_DIM
        vec[idx] += 0.5
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec = vec / norm
    return vec.tolist()


def _is_model_cached() -> bool:
    """检查本地缓存是否已包含目标模型（按 sentence-transformers 目录结构）。"""
    model_dir_name = LOCAL_MODEL_NAME.replace("/", "_")
    candidate = MODEL_CACHE_DIR / model_dir_name
    if candidate.exists() and any(candidate.iterdir()):
        return True
    # sentence-transformers 也会把模型放在 cache_dir/models--sentence-transformers--... 下
    for item in MODEL_CACHE_DIR.iterdir():
        if item.is_dir() and model_dir_name.replace("_", "-") in item.name:
            return True
    return False


def _load_local_model():
    """懒加载本地 embedding 模型（进程内只加载一次）。

    首次调用且本地无缓存时，会尝试通过 HF_ENDPOINT（默认 hf-mirror.com）
    下载模型；下载成功后会强制走本地缓存加载，避免后续网络请求。
    若本地无模型且无法联网下载，则启用纯 Python fallback embedding，
    保证离线环境仍可正常使用知识库功能。
    """
    global _local_model, _use_fallback
    if _local_model is not None or _use_fallback:
        return _local_model
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("sentence-transformers 未安装，请执行 pip install sentence-transformers") from exc

    # 国内环境优先使用 HF_ENDPOINT 镜像下载
    if HF_ENDPOINT:
        os.environ["HF_ENDPOINT"] = HF_ENDPOINT
        os.environ.setdefault("HF_HUB_OFFLINE", "0")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "0")
    else:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    # 本地无缓存时允许联网下载；下载成功后会缓存到 MODEL_CACHE_DIR
    local_only = _is_model_cached()
    if not local_only:
        print(f"[embedding] 本地未找到模型 {LOCAL_MODEL_NAME}，尝试从 {os.environ.get('HF_ENDPOINT', 'https://huggingface.co')} 下载...")

    try:
        _local_model = SentenceTransformer(
            LOCAL_MODEL_NAME,
            cache_folder=str(MODEL_CACHE_DIR),
            local_files_only=local_only,
        )
        # 下载完成后切换为离线模式，避免后续 transformers 对网络文件的 HEAD 检查导致卡顿
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        return _local_model
    except Exception as exc:
        # 下载/加载失败时启用 fallback embedding，而不是直接崩溃
        _use_fallback = True
        print(
            f"[embedding] 警告：无法加载深度学习 embedding 模型（{exc}）。"
            f"已启用离线兜底 embedding，知识库上传/检索仍可继续运行，但语义召回效果会下降。"
        )
        return None


def is_loaded() -> bool:
    """embedding 是否可用（本地模型或 fallback 任一就绪）。"""
    return _local_model is not None or _use_fallback


def get_embedding(text: str) -> list[float]:
    """获取文本向量（L2 归一化后的 list[float]）。

    空文本返回全零向量，保证检索时不会因空输入崩溃。
    当深度学习模型不可用时，自动使用 fallback hash embedding。
    """
    if not text:
        return [0.0] * EMBEDDING_DIM
    if _use_fallback:
        return _fallback_embedding(text)
    model = _load_local_model()
    if model is None:
        return _fallback_embedding(text)
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
