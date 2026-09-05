"""RAG embedding 模块（onnxruntime CPU 推理）。

职责：
- 提供统一的文本向量化接口（本地 ONNX MiniLM 模型，onnxruntime 推理）。
- 提供余弦相似度计算（内存检索用）。

设计原则（2026-09 启动优化阶段重构）：
- 本地 ONNX 模型优先（int8 量化 all-MiniLM-L6-v2，约 23MB），零外部向量服务依赖。
- 替代原 sentence-transformers(torch) 实现：向量余弦对齐实测 ~0.986（RAG 语义
  检索排序稳定性足够），省去 torch 全家桶 ~330MB 打包体积与启动/预热开销。
- 首次调用自动从 HuggingFace（Xenova 仓库，含 onnx 导出）下载并缓存到 data/models/；
  缓存命中后完全离线（HF_HUB_OFFLINE=1）。
- 模型不可用/下载失败/推理异常时，自动降级为纯 Python 的字符 n-gram hash
  embedding 兜底，保证知识库上传、RAG 检索在离线环境仍可运行（效果弱于深度学习模型）。
"""

import os
import sys
import threading
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

# Xenova 仓库：含 sentence-transformers 模型的 ONNX 导出（tokenizer.json + 量化权重）
ONNX_REPO_ID = "Xenova/all-MiniLM-L6-v2"
_ONNX_FILE = "onnx/model_quantized.onnx"  # int8 量化 ~23MB
_TOKENIZER_FILE = "tokenizer.json"
_MAX_SEQ_LEN = 256

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2 输出维度（与 fallback 向量维度一致）

_session = None          # onnxruntime InferenceSession
_tokenizer = None        # tokenizers.Tokenizer
_use_fallback = False    # 模型不可用时启用兜底 embedding
_init_lock = threading.Lock()


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


def _ensure_model_files() -> bool:
    """确保 ONNX 权重与 tokenizer.json 在本地缓存，返回是否就绪。

    策略：先以 local_files_only=True 探测缓存；未命中再联网下载
    （HF_ENDPOINT 镜像或默认 huggingface.co），下载后缓存。
    """
    from huggingface_hub import snapshot_download

    if HF_ENDPOINT:
        os.environ.setdefault("HF_ENDPOINT", HF_ENDPOINT)

    try:
        # 离线探测：缓存命中直接返回
        snapshot = snapshot_download(
            repo_id=ONNX_REPO_ID,
            cache_dir=str(MODEL_CACHE_DIR),
            allow_patterns=[_ONNX_FILE, _TOKENIZER_FILE],
            local_files_only=True,
        )
        _cached = True
    except Exception:
        snapshot, _cached = None, False

    if snapshot is None:
        print(
            f"[embedding] 本地未找到 ONNX 模型 {ONNX_REPO_ID}，"
            f"尝试从 {os.environ.get('HF_ENDPOINT', 'https://huggingface.co')} 下载"
            f"（{_ONNX_FILE} ~23MB，仅首次需要）..."
        )
        try:
            snapshot = snapshot_download(
                repo_id=ONNX_REPO_ID,
                cache_dir=str(MODEL_CACHE_DIR),
                allow_patterns=[_ONNX_FILE, _TOKENIZER_FILE],
                local_files_only=False,
            )
        except Exception as exc:
            print(f"[embedding] 警告：ONNX 模型下载失败（{exc}），将使用兜底 embedding。")
            return False

    if snapshot is not None:
        # 成功后切换离线模式，避免 transformers/hub 对网络文件的 HEAD 检查导致卡顿
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    return snapshot is not None


def _load_local_model():
    """懒加载 ONNX 推理会话与 tokenizer（进程内只加载一次，线程安全）。

    返回 True 表示模型可用；False/None 表示启用兜底 hash embedding。
    """
    global _session, _tokenizer, _use_fallback
    if _session is not None:
        return True
    if _use_fallback:
        return None

    with _init_lock:
        if _session is not None:
            return True
        if _use_fallback:
            return None
        try:
            if not _ensure_model_files():
                _use_fallback = True
                return None
            from onnxruntime import InferenceSession
            from tokenizers import Tokenizer

            snapshot = None
            # 缓存就绪后再次本地探测拿路径（避免重复联网）
            from huggingface_hub import snapshot_download

            try:
                snapshot = snapshot_download(
                    repo_id=ONNX_REPO_ID,
                    cache_dir=str(MODEL_CACHE_DIR),
                    allow_patterns=[_ONNX_FILE, _TOKENIZER_FILE],
                    local_files_only=True,
                )
            except Exception:
                _use_fallback = True
                return None

            onnx_path = Path(snapshot) / _ONNX_FILE
            tokenizer_path = Path(snapshot) / _TOKENIZER_FILE
            _tokenizer = Tokenizer.from_file(str(tokenizer_path))
            _tokenizer.enable_truncation(max_length=_MAX_SEQ_LEN)
            _session = InferenceSession(
                str(onnx_path), providers=["CPUExecutionProvider"]
            )
            return True
        except Exception as exc:  # noqa: BLE001
            _use_fallback = True
            print(
                f"[embedding] 警告：无法加载 ONNX embedding 模型（{exc}）。"
                f"已启用离线兜底 embedding，知识库上传/检索仍可继续运行，"
                f"但语义召回效果会下降。"
            )
            return None


def is_available() -> bool:
    """embedding 是否可用（本地模型或 fallback 任一就绪）。"""
    if _session is not None or _use_fallback:
        return True
    # 首次尚未加载：只要不是永久损坏状态就认为可尝试（首次调用会触发加载/下载）
    return True


# 兼容旧调用名
is_loaded = is_available


def _embed_onnx(text: str) -> np.ndarray:
    """单条文本 ONNX 推理：mean pooling（mask）→ L2 归一化 → 384 维向量。"""
    enc = _tokenizer.encode(text)
    feeds = {
        "input_ids": np.array([enc.ids], dtype=np.int64),
        "attention_mask": np.array([enc.attention_mask], dtype=np.int64),
        "token_type_ids": np.array([enc.type_ids], dtype=np.int64),
    }
    res = _session.run(None, feeds)[0]  # last_hidden_state
    if res.ndim == 3 and res.shape[1] > 1:
        # [1, seq, 384]：按 attention_mask 做 mean pooling
        m = np.asarray(feeds["attention_mask"], dtype=np.float32)[..., None]
        pooled = (res * m).sum(axis=1) / m.sum(axis=1).clip(min=1e-9)
        vec = pooled[0]
    else:
        # 个别导出已含池化：[1, 384]
        vec = res[0]
    vec = vec[:EMBEDDING_DIM] if vec.shape[0] > EMBEDDING_DIM else vec
    vec = np.asarray(vec, dtype=np.float32)
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec = vec / norm
    return vec


def get_embedding(text: str) -> list[float]:
    """获取文本向量（L2 归一化后的 list[float]）。

    空文本返回全零向量，保证检索时不会因空输入崩溃。
    模型加载失败/推理异常时自动使用 fallback hash embedding。
    """
    if not text:
        return [0.0] * EMBEDDING_DIM
    if _use_fallback:
        return _fallback_embedding(text)
    if not _load_local_model():
        return _fallback_embedding(text)
    try:
        return _embed_onnx(text).tolist()
    except Exception as exc:  # noqa: BLE001
        print(f"[embedding] 警告：ONNX 推理失败（{exc}），本次降级兜底 embedding。")
        return _fallback_embedding(text)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度；任一向量为零向量时返回 0。"""
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    if norm == 0:
        return 0.0
    return float(np.dot(a, b) / norm)
