<template>
  <div class="knowledge-page">
    <div class="page-header">
      <h2>📚 知识库</h2>
      <p class="model-page-subtitle">上传本地文档后，Agent 可基于私有知识作答（RAG 检索增强）。</p>
    </div>

    <!-- 新建知识库 -->
    <div class="glass-card kb-create-card">
      <div class="kb-create-title">新建知识库</div>
      <div class="kb-form">
        <input v-model="newName" class="kb-input" placeholder="知识库名称（必填）" @keyup.enter="createKb" />
        <input v-model="newDesc" class="kb-input" placeholder="描述（可选）" @keyup.enter="createKb" />
        <button class="btn-primary" :disabled="!newName.trim() || creating" @click="createKb">
          {{ creating ? '创建中…' : '创建' }}
        </button>
      </div>
    </div>

    <!-- 知识库列表 -->
    <div v-if="kbs.length" class="kb-list">
      <div v-for="kb in kbs" :key="kb.id" class="glass-card kb-card">
        <div class="kb-info">
          <div class="kb-name-row">
            <strong class="kb-name">{{ kb.name }}</strong>
            <span class="kb-status" :class="kb.status">{{ kb.status === 'ready' ? '已就绪' : kb.status }}</span>
          </div>
          <div v-if="kb.description" class="kb-desc">{{ kb.description }}</div>
          <div class="kb-meta">
            分块：{{ kb.chunk_count }} · 创建于 {{ formatTime(kb.created_at) }}
          </div>
        </div>
        <div class="kb-actions">
          <label class="upload-btn">
            上传文件
            <input type="file" :disabled="uploadingId === kb.id" hidden @change="e => uploadFile(kb.id, e.target.files[0], e)" />
          </label>
          <button class="btn-icon" title="删除知识库" @click="deleteKb(kb.id)">🗑</button>
        </div>
      </div>
    </div>
    <div v-else class="empty-tip">还没有知识库，先在上方创建一个吧。</div>

    <!-- 操作反馈 -->
    <div v-if="message" class="kb-message" :class="{ error: messageError }">{{ message }}</div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { appConfirm } from '../utils/appDialog.js'

const kbs = ref([])
const newName = ref('')
const newDesc = ref('')
const creating = ref(false)
const uploadingId = ref('')
const message = ref('')
const messageError = ref(false)

function formatTime(ts) {
  if (!ts) return '--'
  const d = new Date(ts * 1000)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function flash(msg, isError = false) {
  message.value = msg
  messageError.value = isError
  setTimeout(() => { message.value = '' }, 4000)
}

async function loadKbs() {
  try {
    const res = await fetch('/api/knowledge')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    kbs.value = data.knowledge_bases || []
  } catch (e) {
    flash(`加载知识库失败：${e.message}`, true)
  }
}

async function createKb() {
  if (!newName.value.trim() || creating.value) return
  creating.value = true
  try {
    const res = await fetch('/api/knowledge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newName.value.trim(), description: newDesc.value.trim() }),
    })
    if (!res.ok) {
      const d = await res.json().catch(() => ({}))
      throw new Error(d.error || `HTTP ${res.status}`)
    }
    newName.value = ''
    newDesc.value = ''
    flash('知识库创建成功')
    await loadKbs()
  } catch (e) {
    flash(`创建失败：${e.message}`, true)
  } finally {
    creating.value = false
  }
}

async function deleteKb(id) {
  const ok = await appConfirm('确定删除该知识库及其全部分块？此操作不可恢复。')
  if (!ok) return
  try {
    const res = await fetch(`/api/knowledge/${id}`, { method: 'DELETE' })
    if (!res.ok) {
      const d = await res.json().catch(() => ({}))
      throw new Error(d.error || `HTTP ${res.status}`)
    }
    flash('知识库已删除')
    await loadKbs()
  } catch (e) {
    flash(`删除失败：${e.message}`, true)
  }
}

async function uploadFile(id, file, event) {
  if (!file) return
  uploadingId.value = id
  flash(`正在解析并向量化「${file.name}」…`)
  try {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`/api/knowledge/${id}/upload`, { method: 'POST', body: form })
    const data = await res.json().catch(() => ({}))
    if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`)
    flash(`「${file.name}」入库成功，共 ${data.chunks} 个分块`)
  } catch (e) {
    flash(`上传失败：${e.message}`, true)
  } finally {
    uploadingId.value = ''
    if (event) event.target.value = ''
    await loadKbs()
  }
}

onMounted(loadKbs)
</script>

<style scoped>
.knowledge-page {
  padding: 22px 26px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.page-header h2 {
  margin: 0 0 4px;
  font-size: 20px;
}
.kb-create-card {
  padding: 16px 18px;
}
.kb-create-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 10px;
}
.kb-form {
  display: flex;
  gap: 10px;
}
.kb-input {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid var(--border);
  background: var(--panel-2);
  border-radius: 8px;
  font-size: 13px;
  color: var(--text);
}
.kb-input:focus {
  outline: none;
  border-color: var(--primary);
}
.kb-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.kb-card {
  padding: 14px 18px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}
.kb-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.kb-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.kb-name {
  font-size: 15px;
}
.kb-status {
  font-size: 10.5px;
  font-weight: 600;
  padding: 1px 8px;
  border-radius: 10px;
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
}
.kb-desc {
  font-size: 12.5px;
  color: var(--text-secondary);
}
.kb-meta {
  font-size: 11.5px;
  color: var(--text-muted);
}
.kb-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.upload-btn {
  padding: 8px 16px;
  background: linear-gradient(135deg, var(--primary), var(--purple));
  color: #fff;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: opacity .15s;
}
.upload-btn:hover { opacity: .9; }
.kb-message {
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
  border: 1px solid rgba(16, 185, 129, 0.25);
}
.kb-message.error {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
  border-color: rgba(239, 68, 68, 0.25);
}
</style>
