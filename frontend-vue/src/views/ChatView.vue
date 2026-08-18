<template>
  <div class="chat-view">
    <div class="chat-sessions" :style="{ width: sessionsWidth + 'px', flexShrink: 0 }">
      <div class="chat-sessions-head">
        <h3>会话列表</h3>
        <button class="chat-new-btn" @click="openNewSessionDialog">+ 新对话</button>
      </div>
      <div class="chat-search">
        <input v-model="searchTerm" type="text" placeholder="搜索会话">
      </div>
      <div class="chat-session-list">
        <div
          v-for="s in filteredSessions"
          :key="s.id"
          class="chat-session"
          :class="{ active: s.id === currentId }"
          @click="currentId = s.id"
        >
          <div class="chat-session-info">
            <div class="chat-session-title">{{ s.title }}</div>
            <div class="chat-session-meta">{{ formatTime(s.time) }} · {{ s.messages.length }} 条消息</div>
            <div v-if="s.skills && s.skills.length || s.modelPresetId" class="chat-session-tags">
              <span v-if="s.modelPresetId && presetNameById(s.modelPresetId)" class="chat-session-model-chip" :title="`本对话使用：${presetNameById(s.modelPresetId)}`">
                🤖 {{ presetNameById(s.modelPresetId) }}
              </span>
              <span v-for="sk in s.skills" :key="sk.id" class="session-skill-chip">{{ sk.icon || '🛠️' }} {{ sk.name }}</span>
            </div>
          </div>
          <button class="chat-session-delete" @click.stop="deleteSession(s.id)">🗑</button>
        </div>
        <div v-if="!filteredSessions.length" style="padding: 20px; text-align: center; color: var(--text-muted); font-size: 12px;">
          暂无会话
        </div>
      </div>
    </div>
    <div class="chat-resizer" :class="{ active: resizing }" @mousedown="startResize"></div>
    <div class="chat-area">
      <div class="chat-area-head">
        <div class="chat-area-head-left">
          <span class="chat-area-title">{{ currentSession?.title || '新对话' }}</span>
          <div v-if="currentSession?.skills?.length" class="chat-area-skills">
            <span v-for="sk in currentSession.skills" :key="sk.id" class="chat-skill-tag">
              {{ sk.icon || '🛠️' }} {{ sk.name }}
            </span>
            <button class="chat-skill-edit" @click="editSkills" title="管理技能">⚙️</button>
          </div>
        </div>
        <div class="chat-area-head-right">
          <div class="chat-current-model-wrap" :class="{ open: modelMenuOpen }" @click.stop="toggleModelMenu">
            <div class="chat-current-model" :title="currentModelFull">
              <span class="chat-current-model-dot">{{ currentModelInitial }}</span>
              <span class="chat-current-model-text">
                <span class="chat-current-model-name">{{ currentModelName }}</span>
                <span class="chat-current-model-sub">{{ currentModelSub }}</span>
              </span>
              <span class="chat-current-model-arrow">▾</span>
            </div>
            <div class="chat-model-menu" @click.stop>
              <div class="chat-model-menu-header">
                <span>为本对话选择模型</span>
                <button class="chat-model-menu-link" @click.stop="goPresetAdmin">管理预设 →</button>
              </div>
              <div v-if="modelLoading" class="chat-model-menu-empty">加载中…</div>
              <div v-else-if="!presets.length" class="chat-model-menu-empty">
                还没有保存的预设，请到「系统设置」中配置。
              </div>
              <div v-else class="chat-model-menu-list">
                <div
                  v-for="p in presets"
                  :key="p.id"
                  class="chat-model-menu-item"
                  :class="{ active: p.id === currentSessionModelId }"
                  @click="pickModelForSession(p)"
                >
                  <div class="chat-model-menu-dot">{{ (p.name || p.provider || '?').charAt(0).toUpperCase() }}</div>
                  <div class="chat-model-menu-info">
                    <div class="chat-model-menu-name">
                      {{ p.name || p.provider }}
                      <span v-if="p.id === currentSessionModelId" class="chat-model-menu-tag">本对话</span>
                    </div>
                    <div class="chat-model-menu-sub">{{ p.model || '(未填)' }}</div>
                  </div>
                  <span v-if="p.id === currentSessionModelId" class="chat-model-menu-check">✓</span>
                </div>
              </div>
            </div>
          </div>
          <button class="btn-ghost" @click="editSkills" v-if="currentSession">管理技能</button>
          <button class="btn-ghost" @click="clearCurrent">清空当前</button>
        </div>
      </div>
      <div class="chat-messages" ref="messagesEl">
        <div v-for="(msg, i) in currentMessages" :key="i" class="chat-msg" :class="msg.role">
          <div class="chat-avatar" :class="msg.role">{{ msg.role === 'user' ? '我' : 'AI' }}</div>
          <div class="chat-bubble-wrap">
            <div class="chat-bubble" v-html="renderMarkdown(msg.text)"></div>
            <div class="chat-time">{{ formatTime(msg.time) }}</div>
          </div>
        </div>
        <div v-if="!currentMessages.length" style="display: flex; flex: 1; align-items: center; justify-content: center; color: var(--text-muted); gap: 10px;">
          <span style="font-size: 42px; opacity: .4;">💬</span>
          <span>开始新对话</span>
        </div>
      </div>
      <div class="chat-input-area">
        <textarea
          v-model="inputText"
          rows="1"
          placeholder="输入问题，例如：帮我生成一份行业调研报告…"
          @keydown.enter.exact.prevent="send"
        ></textarea>
        <button class="chat-send" @click="send">➤</button>
      </div>
    </div>

    <div class="chat-resizer chat-resizer-right" :class="{ active: filesResizing }" @mousedown="startFilesResize"></div>

    <div class="chat-files" :class="{ collapsed: filesCollapsed }" :style="filesCollapsed ? {} : { width: filesWidth + 'px', flexShrink: 0 }">
      <div class="chat-files-head">
        <div class="chat-files-title-row">
          <div class="chat-files-title">
            <span class="chat-files-icon" @click="filesCollapsed = !filesCollapsed" style="cursor:pointer">📁</span>
            <div class="ws-picker" :class="{ open: wsPickerOpen }">
                  <div class="ws-picker-trigger" @click.stop="onWsPickerToggle">
                    <svg class="ws-picker-trigger-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"
                        :fill="wsPickerOpen ? 'var(--accent)' : 'rgba(139,92,246,.8)'"/>
                    </svg>
                    <span class="ws-picker-name">{{ wsName || '选择工作空间' }}</span>
                    <svg class="ws-picker-arrow" width="10" height="10" viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
                    </svg>
                  </div>
                  <div class="ws-picker-dropdown" v-if="wsPickerOpen">
                    <div class="ws-picker-header">
                      <span class="ws-picker-header-icon">📁</span>
                      <div class="ws-picker-header-text">
                        <div class="ws-picker-header-title">工作空间</div>
                        <div class="ws-picker-header-sub">共 {{ workspaceList.length }} 个</div>
                      </div>
                    </div>
                    <div class="ws-picker-list">
                      <div
                        v-for="ws in workspaceList"
                        :key="ws.id"
                        class="ws-picker-item"
                        :class="{ selected: ws.id === currentWorkspaceId }"
                        @click.stop="pickWorkspace(ws)"
                      >
                        <div class="ws-picker-item-left">
                          <svg v-if="ws.id === currentWorkspaceId" class="ws-picker-item-check" width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
                            <path d="M5 12l4 4L19 7" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
                          </svg>
                          <span class="ws-picker-item-icon">📂</span>
                          <span class="ws-picker-item-name">{{ ws.name }}</span>
                        </div>
                        <button class="ws-picker-item-del" @click.stop="removeWorkspace(ws.id)" title="删除工作空间">
                          <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true">
                            <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m2 0v14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V6"
                              stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
                          </svg>
                        </button>
                      </div>
                      <div v-if="!workspaceList.length" class="ws-picker-empty">
                        <span style="font-size:20px;">🗂️</span>
                        <div style="margin-top:6px;">暂无工作空间</div>
                        <div style="font-size:11px;opacity:.8;">点击下方「打开」添加一个本地目录</div>
                      </div>
                    </div>
                    <div class="ws-picker-actions">
                      <button class="ws-picker-btn-create" @click.stop="createWorkspace">
                        <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true" style="flex-shrink:0;">
                          <path d="M5 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"
                            stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
                          <path d="M9 11h6M12 8v6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                        <span>打开工作空间</span>
                      </button>
                    </div>
                  </div>
                </div>
            <span class="chat-files-arrow" @click="filesCollapsed = !filesCollapsed" style="cursor:pointer; display:none;">{{ filesCollapsed ? '▸' : '▾' }}</span>
          </div>
          <div class="chat-files-actions" v-if="!filesCollapsed">
            <button class="chat-files-refresh" @click="loadWorkspaceFiles" :title="`刷新（${wsName || '加载中…'}）`">↻</button>
          </div>
        </div>
      </div>
      <div v-if="!filesCollapsed" class="chat-files-body">
        <div v-if="filesLoading" class="chat-files-empty">加载中…</div>
        <div v-else-if="filesError" class="chat-files-empty chat-files-error">{{ filesError }}</div>
        <div v-else-if="!currentWorkspaceId" class="chat-files-empty">
          还没有工作空间。<br>
          请到顶部「📁」切换器添加一个目录。
        </div>
        <div v-else-if="!fileTree.length" class="chat-files-empty">空目录</div>
        <div v-else class="chat-files-tree">
          <div
            v-for="row in fileTreeRows"
            :key="row.node.rel + ':' + row.depth"
            class="chat-files-row"
            :class="{ dir: row.node.is_dir, file: !row.node.is_dir, expanded: expandedDirs[row.node.rel] }"
            :style="{ paddingLeft: (8 + row.depth * 14) + 'px' }"
            :title="row.node.rel"
            @click="onFileRowClick(row.node)"
          >
            <span class="chat-files-toggle">{{ row.node.is_dir ? (expandedDirs[row.node.rel] ? '▾' : '▸') : '' }}</span>
            <span class="chat-files-glyph">{{ fileGlyph(row.node) }}</span>
            <span class="chat-files-label">{{ row.node.name }}</span>
            <span class="chat-files-size" v-if="!row.node.is_dir">{{ formatSize(row.node.size) }}</span>
          </div>
        </div>
      </div>
    </div>

    <div v-if="showSkillPicker" class="skill-picker-overlay" @click.self="showSkillPicker = false">
      <div class="skill-picker-modal">
        <div class="skill-picker-header">
          <div class="skill-picker-title">{{ editingSessionId ? '管理会话技能' : '选择会话技能' }}</div>
          <button class="skill-picker-close" @click="showSkillPicker = false">✕</button>
        </div>
        <div class="skill-picker-sub">选择要在本次对话中携带的技能，AI 将自动调用它们</div>
        <div class="skill-picker-body">
          <div v-if="!availableSkills.length" class="skill-picker-empty">
            暂无可用技能，请先在「集成管理 → 技能管理」中添加
          </div>
          <div v-for="sk in availableSkills" :key="sk.id" class="skill-picker-item" :class="{ selected: isSkillSelected(sk.id), disabled: !sk.enabled }" @click="toggleSkill(sk)">
            <div class="skill-picker-check">{{ isSkillSelected(sk.id) ? '✓' : '' }}</div>
            <div class="skill-picker-icon" :style="{ background: sk.color || 'rgba(139, 92, 246, 0.12)' }">{{ sk.icon || '🛠️' }}</div>
            <div class="skill-picker-info">
              <div class="skill-picker-name">{{ sk.name }}</div>
              <div class="skill-picker-desc">{{ sk.desc }}</div>
            </div>
            <span v-if="!sk.enabled" class="skill-picker-disabled">已停用</span>
          </div>
        </div>
        <div class="skill-picker-footer">
          <span class="skill-picker-count">已选 {{ tempSelectedSkills.length }} 个技能</span>
          <div style="display:flex;gap:8px;">
            <button class="btn-ghost" @click="showSkillPicker = false">取消</button>
            <button class="btn-primary" @click="confirmSkillSelection">确认</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch, onUnmounted } from 'vue'

const sessions = ref([])
const currentId = ref(null)
const inputText = ref('')
const searchTerm = ref('')
const messagesEl = ref(null)
const showSkillPicker = ref(false)
const availableSkills = ref([])
const tempSelectedSkills = ref([])
const editingSessionId = ref(null)

const currentSession = computed(() => sessions.value.find(s => s.id === currentId.value))
const currentMessages = computed(() => currentSession.value?.messages || [])

const filteredSessions = computed(() => {
  const term = searchTerm.value.trim().toLowerCase()
  if (!term) return sessions.value
  return sessions.value.filter(s => s.title.toLowerCase().includes(term))
})

function formatTime(ts) {
  if (!ts) return ''
  return new Date(ts).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function renderMarkdown(text) {
  if (!text) return ''
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
}

function loadAvailableSkills() {
  try {
    const saved = localStorage.getItem('skills')
    if (saved) availableSkills.value = JSON.parse(saved)
  } catch {}
}

function isSkillSelected(skillId) {
  return tempSelectedSkills.value.some(s => s.id === skillId)
}

function toggleSkill(skill) {
  if (!skill.enabled) return
  const idx = tempSelectedSkills.value.findIndex(s => s.id === skill.id)
  if (idx >= 0) {
    tempSelectedSkills.value.splice(idx, 1)
  } else {
    tempSelectedSkills.value.push({ id: skill.id, name: skill.name, icon: skill.icon, type: skill.type, url: skill.url })
  }
}

function openNewSessionDialog() {
  loadAvailableSkills()
  editingSessionId.value = null
  tempSelectedSkills.value = []
  showSkillPicker.value = true
}

function editSkills() {
  const s = currentSession.value
  if (!s) return
  loadAvailableSkills()
  editingSessionId.value = s.id
  tempSelectedSkills.value = [...(s.skills || [])]
  showSkillPicker.value = true
}

function confirmSkillSelection() {
  if (editingSessionId.value) {
    const s = sessions.value.find(x => x.id === editingSessionId.value)
    if (s) {
      s.skills = [...tempSelectedSkills.value]
      saveSessions()
    }
  } else {
    const id = Date.now().toString()
    sessions.value.unshift({
      id,
      title: '新对话',
      time: Date.now(),
      messages: [],
      skills: [...tempSelectedSkills.value],
      modelPresetId: globalDefaultPresetId.value || '',  // 新建会话时绑定当前默认模型
    })
    currentId.value = id
    saveSessions()
  }
  showSkillPicker.value = false
}

function deleteSession(id) {
  if (!confirm('确定删除该会话？')) return
  sessions.value = sessions.value.filter(s => s.id !== id)
  if (currentId.value === id) currentId.value = sessions.value[0]?.id || null
  saveSessions()
}

function clearCurrent() {
  const s = currentSession.value
  if (!s) return
  if (!confirm('确定清空当前会话的消息记录吗？')) return
  s.messages = [{ role: 'ai', text: '当前会话已清空，请重新输入。', time: Date.now() }]
  saveSessions()
}

const sending = ref(false)

// ===== 当前会话模型（会话级，每个对话可独立切换） =====
const presets = ref([])
const presetsById = computed(() => {
  const m = {}
  for (const p of presets.value) m[p.id] = p
  return m
})
const modelMenuOpen = ref(false)
const modelLoading = ref(false)

// 会话绑定模型：当前会话的 modelPresetId（未设置时回退到全局激活）
const currentSessionModelId = computed(() => {
  const s = currentSession.value
  return s?.modelPresetId || globalDefaultPresetId.value || ''
})

const currentSessionPreset = computed(() => {
  const id = currentSessionModelId.value
  if (!id) return null
  return presetsById.value[id] || null
})

const currentModelName = computed(() =>
  currentSessionPreset.value?.name || currentSessionPreset.value?.provider || '未配置',
)
const currentModelSub = computed(() =>
  currentSessionPreset.value?.model || '点击右上角切换',
)
const currentModelFull = computed(() => {
  const p = currentSessionPreset.value
  if (!p) return '尚未配置模型，请到顶栏或系统设置中选择'
  return `${p.name || p.provider} · ${p.model || '(未填)'}${p.base_url ? ' · ' + p.base_url : ''}`
})
const currentModelInitial = computed(() => {
  const n = currentSessionPreset.value?.name || currentSessionPreset.value?.provider || '?'
  return (n.charAt(0) || '?').toUpperCase()
})

// 全局默认（顶栏激活预设），仅用于「新建会话时」未指定时的默认
const globalDefaultPresetId = ref('')

async function loadPresetsList() {
  modelLoading.value = true
  try {
    const res = await fetch('/api/model-presets')
    if (!res.ok) return
    const data = await res.json()
    presets.value = data.presets || []
    globalDefaultPresetId.value = data.active_id || ''
  } catch (e) { /* 静默 */ }
  finally { modelLoading.value = false }
}

function loadActiveModel() { loadPresetsList() }

function toggleModelMenu() {
  modelMenuOpen.value = !modelMenuOpen.value
  if (modelMenuOpen.value) loadPresetsList()
}

function pickModelForSession(p) {
  const s = currentSession.value
  if (!s) return
  if (s.modelPresetId === p.id) {
    modelMenuOpen.value = false
    return
  }
  s.modelPresetId = p.id
  // 立刻反映在 UI 上
  saveSessions()
  modelMenuOpen.value = false
  showMessage(`本对话已切换到「${p.name || p.provider}」`)
}

function goPresetAdmin() {
  modelMenuOpen.value = false
  window.location.hash = '#/settings'
}

function showMessage(text) {
  // 简易提示，复用 toast 也可以，这里直接用一个临时变量
  saveMessage.value = { type: 'ok', text }
  setTimeout(() => { saveMessage.value = null }, 2000)
}
const saveMessage = ref(null)

// 全局 model-changed 事件：更新全局默认（新建会话时使用）
function onModelChanged() {
  loadPresetsList()
}

// 点击其它位置关闭 dropdown
function onDocClickChat(e) {
  if (!modelMenuOpen.value) return
  const el = e.target
  if (el && el.closest && el.closest('.chat-current-model-wrap')) return
  modelMenuOpen.value = false
}

async function send() {
  const text = inputText.value.trim()
  if (!text || sending.value) return
  const s = currentSession.value
  if (!s) { openNewSessionDialog(); return }

  // 1) 推入用户消息
  s.messages.push({ role: 'user', text, time: Date.now() })
  s.title = text.slice(0, 20)
  inputText.value = ''
  await scrollToBottom()

  // 2) 预占一条 AI 消息，等待后端返回
  const aiMsg = { role: 'ai', text: '', time: Date.now(), pending: true }
  s.messages.push(aiMsg)
  await scrollToBottom()

  sending.value = true
  saveSessions()
  try {
    // 3) 构造后端 ChatRequest 格式：{role, content}，并附会话携带的 skills（用于后端 @技能名 触发）
    const payload = {
      messages: s.messages
        .filter(m => !m.pending)
        .map(m => ({ role: m.role === 'ai' ? 'assistant' : m.role, content: m.text })),
      skills: (s.skills || []).map(sk => ({ id: sk.id, name: sk.name, type: sk.type })),
      model_preset_id: s.modelPresetId || globalDefaultPresetId.value || null,
      workspace_id: currentWorkspaceId.value || null,
    }

    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })

    if (!res.ok) {
      let errMsg = `HTTP ${res.status}`
      try {
        const data = await res.json()
        errMsg = data.error || data.detail || errMsg
      } catch {}
      aiMsg.text = `❌ 调用大模型失败：${errMsg}`
      aiMsg.pending = false
      aiMsg.error = true
    } else {
      const data = await res.json()
      aiMsg.text = data.reply || '(大模型无返回内容)'
      aiMsg.pending = false
      const tags = []
      if (data.workspace_injected) tags.push('📁 已注入工作空间上下文')
      if (data.skills_injected) tags.push('✨ 已注入技能上下文')
      if (tags.length) aiMsg.text += '\n\n<sub>' + tags.join('  ') + '</sub>'
      s.time = Date.now()
    }
  } catch (e) {
    aiMsg.text = `❌ 网络错误：${e.message || e}\n\n请确认后端服务已启动（http://127.0.0.1:8000）且模型已配置。`
    aiMsg.pending = false
    aiMsg.error = true
  } finally {
    sending.value = false
    saveSessions()
    await scrollToBottom()
  }
}

async function scrollToBottom() {
  await nextTick()
  if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
}

function saveSessions() {
  localStorage.setItem('chatSessions', JSON.stringify(sessions.value))
}

function presetNameById(id) {
  const p = presetsById.value[id]
  if (!p) return ''
  return p.name || p.provider || ''
}

function loadSessions() {
  try {
    const saved = localStorage.getItem('chatSessions')
    if (saved) {
      sessions.value = JSON.parse(saved)
      currentId.value = sessions.value[0]?.id || null
    }
  } catch (e) { console.error('加载会话失败', e) }
}

function onWorkspaceChanged(evt) {
  // App.vue 切换工作空间时派发此事件
  const newId = evt?.detail?.current_id
  if (newId && newId !== currentWorkspaceId.value) {
    currentWorkspaceId.value = newId
    // 切换工作空间时重置展开状态
    expandedDirs.value = {}
  }
  // 无论 ID 是否变化都刷新一次文件列表，保证右侧内容与顶栏选择一致
  loadWorkspaceFiles()
}

onMounted(async () => {
  loadSessions()
  loadAvailableSkills()
  await loadPresetsList()
  // 回填旧会话（没有 modelPresetId 字段的）默认绑定全局激活预设
  for (const s of sessions.value) {
    if (!s.modelPresetId && globalDefaultPresetId.value) {
      s.modelPresetId = globalDefaultPresetId.value
    }
  }
  saveSessions()
  window.addEventListener('taofei-model-changed', onModelChanged)
  window.addEventListener('taofei-workspace-changed', onWorkspaceChanged)
  document.addEventListener('click', onDocClickChat)
  document.addEventListener('click', onDocClickWorkspace)
  await loadWorkspaceList()
  loadWorkspaceFiles()
  if (!sessions.value.length) {
    openNewSessionDialog()
  }
})

onUnmounted(() => {
  window.removeEventListener('taofei-model-changed', onModelChanged)
  window.removeEventListener('taofei-workspace-changed', onWorkspaceChanged)
  document.removeEventListener('click', onDocClickChat)
  document.removeEventListener('click', onDocClickWorkspace)
})

watch(currentId, () => scrollToBottom())

// ===== 工作空间文件树（右侧面板） =====
const currentWorkspaceId = ref('')
const wsName = ref('')
const wsPath = ref('')
const fileTree = ref([])
const expandedDirs = ref({})
const filesLoading = ref(false)
const filesError = ref('')
const filesCollapsed = ref(false)

// 左侧会话列表宽度拖拽
const sessionsWidth = ref(parseInt(localStorage.getItem('chatSessionsWidth') || '260'))
const resizing = ref(false)
let resizeStartX = 0
let resizeStartWidth = 0

function startResize(e) {
  resizing.value = true
  resizeStartX = e.clientX
  resizeStartWidth = sessionsWidth.value
  document.addEventListener('mousemove', onResize)
  document.addEventListener('mouseup', stopResize)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

function onResize(e) {
  if (!resizing.value) return
  const delta = e.clientX - resizeStartX
  const w = Math.min(500, Math.max(180, resizeStartWidth + delta))
  sessionsWidth.value = w
}

function stopResize() {
  resizing.value = false
  document.removeEventListener('mousemove', onResize)
  document.removeEventListener('mouseup', stopResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  localStorage.setItem('chatSessionsWidth', sessionsWidth.value)
}

// 右侧工作空间文件面板宽度拖拽
const filesWidth = ref(parseInt(localStorage.getItem('chatFilesWidth') || '300'))
const filesResizing = ref(false)
let filesResizeStartX = 0
let filesResizeStartWidth = 0

function startFilesResize(e) {
  if (filesCollapsed.value) return
  filesResizing.value = true
  filesResizeStartX = e.clientX
  filesResizeStartWidth = filesWidth.value
  document.addEventListener('mousemove', onFilesResize)
  document.addEventListener('mouseup', stopFilesResize)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

function onFilesResize(e) {
  if (!filesResizing.value) return
  const delta = filesResizeStartX - e.clientX // 向右拖拽减小，向左增大
  const w = Math.min(500, Math.max(200, filesResizeStartWidth + delta))
  filesWidth.value = w
}

function stopFilesResize() {
  filesResizing.value = false
  document.removeEventListener('mousemove', onFilesResize)
  document.removeEventListener('mouseup', stopFilesResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  localStorage.setItem('chatFilesWidth', filesWidth.value)
}

// 工作空间选择器
const wsPickerOpen = ref(false)
const workspaceList = ref([])

async function loadWorkspaceList() {
  try {
    const res = await fetch('/api/workspaces')
    if (res.ok) {
      const data = await res.json()
      workspaceList.value = data.workspaces || []
      if (!currentWorkspaceId.value && data.current_id) {
        currentWorkspaceId.value = data.current_id
      }
    }
  } catch (e) { /* ignore */ }
}

function pickWorkspace(ws) {
  if (!ws || !ws.id) return
  if (ws.id === currentWorkspaceId.value) {
    wsPickerOpen.value = false
    return
  }
  currentWorkspaceId.value = ws.id
  wsName.value = ws.name
  wsPath.value = ws.path
  expandedDirs.value = {}
  wsPickerOpen.value = false
  loadWorkspaceFiles()
}

async function removeWorkspace(id) {
  if (!confirm('确定删除该工作空间？')) return
  try {
    const res = await fetch(`/api/workspaces/${id}`, { method: 'DELETE' })
    if (res.ok) {
      const data = await res.json()
      workspaceList.value = workspaceList.value.filter(w => w.id !== id)
      if (currentWorkspaceId.value === id) {
        currentWorkspaceId.value = data.current_id || workspaceList.value[0]?.id || ''
        if (!currentWorkspaceId.value) {
          wsName.value = ''
          wsPath.value = ''
          fileTree.value = []
        }
      }
      loadWorkspaceFiles()
    }
  } catch (e) { /* ignore */ }
}

async function createWorkspace() {
  // 「打开工作空间」优先调用后端原生目录选择对话框；不支持/取消/超时则退回粘贴路径，
  // 名称直接按目录名自动生成，不再需要用户单独输入名字。
  let path = ''
  try {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 30_000)
    const res = await fetch('/api/browse-directory', { signal: controller.signal })
    clearTimeout(timer)
    if (res.ok) {
      const data = await res.json().catch(() => ({}))
      if (data?.canceled) return
      if (data?.path) path = String(data.path)
    }
  } catch (_e) {
    // 网络错误 / 后端沙箱无法弹对话框 / 用户超时：静默走 fallback
  }

  if (!path) {
    const input = prompt(
      '请粘贴要打开的本地文件夹路径（例如 E:\\projects\\my-app）：',
      'E:\\20260814\\taofei_app'
    )
    if (!input) return
    path = input
  }

  const trimmed = String(path).trim()
  if (!trimmed) return
  const name = trimmed.split(/[\\/]/).filter(Boolean).pop() || '新工作空间'

  try {
    const res = await fetch('/api/workspaces', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, path: trimmed }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      alert('打开失败：' + (err.error || '路径无效'))
      return
    }
    const data = await res.json()
    workspaceList.value.push(data.workspace)
    pickWorkspace(data.workspace)
  } catch (e) {
    alert('打开失败：' + (e.message || String(e)))
  }
}

// 切换工作空间选择器下拉
function onWsPickerToggle() {
  wsPickerOpen.value = !wsPickerOpen.value
}

// 点击外部关闭工作空间选择器
function onDocClickWorkspace(e) {
  if (!wsPickerOpen.value) return
  const picker = document.querySelector('.ws-picker')
  if (picker && !picker.contains(e.target)) {
    wsPickerOpen.value = false
  }
}

// 把后端返回的扁平列表构造为嵌套树（按 '/' 拆 rel）
function buildTreeFromFlat(items) {
  if (!Array.isArray(items)) return []
  const rootChildren = new Map()
  for (const it of items) {
    if (!it) continue
    const parts = (it.rel || it.name || '').split('/').filter(Boolean)
    if (!parts.length) continue
    let cursor = rootChildren
    // 遍历中间层，创建/复用目录节点
    for (let i = 0; i < parts.length - 1; i++) {
      const part = parts[i]
      const key = parts.slice(0, i + 1).join('/')
      const existing = cursor.get(part)
      if (!existing) {
        cursor.set(part, { name: part, rel: key, is_dir: true, size: 0, children: new Map() })
      } else if (!existing.children || !(existing.children instanceof Map)) {
        // 路径上存在同名 leaf（非目录），把它升级为目录
        existing.is_dir = true
        existing.children = new Map()
      }
      cursor = cursor.get(part).children
    }
    const leafName = parts[parts.length - 1] || it.name
    const leafKey = it.rel || it.name || leafName
    if (!cursor) continue
    const prev = cursor.get(leafName)
    if (prev && prev.children instanceof Map) {
      // 已存在同名目录节点 → 保留目录的 children，其他字段用新 leaf 覆盖
      cursor.set(leafName, { ...prev, ...it, name: leafName, rel: leafKey, children: prev.children })
    } else {
      cursor.set(leafName, { name: leafName, ...it, rel: leafKey, children: null })
    }
  }
  // Map → Array，目录优先、再按字母排序
  function sortMap(m) {
    const arr = [...m.values()]
    arr.sort((a, b) => (a.is_dir === b.is_dir ? a.name.localeCompare(b.name) : a.is_dir ? -1 : 1))
    return arr
  }
  function materialize(m) {
    const arr = sortMap(m)
    for (const n of arr) {
      if (n.children instanceof Map) n.children = materialize(n.children)
      else if (n.is_dir) n.children = []
    }
    return arr
  }
  return materialize(rootChildren)
}

const fileTreeRows = computed(() => {
  // 把 fileTree 扁平化（按展开状态）成带 depth 的行
  const rows = []
  function walk(nodes, depth) {
    if (!Array.isArray(nodes)) return
    for (const n of nodes) {
      rows.push({ node: n, depth })
      const exp = expandedDirs.value && typeof expandedDirs.value === 'object' ? expandedDirs.value[n.rel] : false
      if (n.is_dir && exp && Array.isArray(n.children) && n.children.length) {
        walk(n.children, depth + 1)
      }
    }
  }
  walk(Array.isArray(fileTree.value) ? fileTree.value : [], 0)
  return rows
})

function formatSize(bytes) {
  if (!bytes || bytes < 0) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB'
  return (bytes / 1024 / 1024 / 1024).toFixed(1) + ' GB'
}

function fileGlyph(node) {
  if (node.is_dir) return '📂'
  const n = node.name.toLowerCase()
  if (/\.(png|jpe?g|gif|svg|webp|bmp|ico)$/.test(n)) return '🖼'
  if (/\.(mp4|mov|avi|mkv|webm)$/.test(n)) return '🎬'
  if (/\.(mp3|wav|flac|ogg|m4a)$/.test(n)) return '🎵'
  if (/\.(zip|tar|gz|7z|rar)$/.test(n)) return '📦'
  if (/\.(pdf)$/.test(n)) return '📕'
  if (/\.(md|markdown|txt)$/.test(n)) return '📝'
  if (/\.(json|ya?ml|toml|ini|cfg|conf)$/.test(n)) return '⚙'
  if (/\.(css|scss|less)$/.test(n)) return '🎨'
  if (/\.(vue|jsx|tsx|svelte)$/.test(n)) return '🧩'
  if (/\.(html?)$/.test(n)) return '🔖'
  if (/\.(py|js|ts|java|c|cpp|go|rs|rb|php|sh|ps1|bat)$/.test(n)) return '📜'
  return '📄'
}

async function loadWorkspaceFiles() {
  filesLoading.value = true
  filesError.value = ''
  try {
    if (!currentWorkspaceId.value) {
      const resW = await fetch('/api/workspaces')
      if (!resW.ok) throw new Error('无法获取工作空间列表')
      const dataW = await resW.json()
      currentWorkspaceId.value = dataW.current_id || ''
    }
    if (!currentWorkspaceId.value) {
      fileTree.value = []
      wsName.value = ''
      wsPath.value = ''
      return
    }
    const res = await fetch(`/api/workspaces/${currentWorkspaceId.value}/files?max_depth=6&max_files=5000`)
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.error || `HTTP ${res.status}`)
    }
    const data = await res.json()
    fileTree.value = buildTreeFromFlat(data.files || [])
    // 同时拉详情拿 workspace 名字
    const wsRes = await fetch('/api/workspaces')
    if (wsRes.ok) {
      const wd = await wsRes.json()
      const ws = (wd.workspaces || []).find(w => w.id === currentWorkspaceId.value)
      if (ws) {
        wsName.value = ws.name
        wsPath.value = ws.path
      }
    }
  } catch (e) {
    filesError.value = e.message || String(e)
  } finally {
    filesLoading.value = false
  }
}

function onFileRowClick(node) {
  if (node.is_dir) {
    const next = { ...expandedDirs.value }
    if (next[node.rel]) delete next[node.rel]
    else next[node.rel] = true
    expandedDirs.value = next
  } else {
    onFilePick(node)
  }
}

function onFilePick(node) {
  // 把文件相对路径附到输入框，作为给 AI 的上下文
  const ref = '@' + node.rel
  const cur = inputText.value.trim()
  if (cur.includes(ref)) {
    inputText.value = cur + '\n' + ref
  } else {
    inputText.value = cur ? cur + '  ' + ref : ref
  }
  // 简单提示
  showMessage(`已引用：${node.rel}`)
}
</script>

<style scoped>
.skill-picker-overlay {
  position: fixed; top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(4px);
  z-index: 1000;
  display: flex; align-items: center; justify-content: center;
  padding: 16px;
}
.skill-picker-modal {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  width: 100%; max-width: 480px;
  max-height: 85vh;
  display: flex; flex-direction: column;
  box-shadow: var(--shadow);
}
.skill-picker-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 20px 12px;
  border-bottom: 1px solid var(--border);
}
.skill-picker-title { font-size: 16px; font-weight: 700; }
.skill-picker-close {
  background: none; border: none; color: var(--text-muted);
  font-size: 18px; cursor: pointer; padding: 4px 8px; border-radius: 6px;
}
.skill-picker-close:hover { background: var(--bg-soft); color: var(--text); }
.skill-picker-sub { font-size: 12.5px; color: var(--text-muted); padding: 8px 20px 12px; }
.skill-picker-body { flex: 1; overflow-y: auto; padding: 8px 20px; }
.skill-picker-empty { text-align: center; padding: 30px; color: var(--text-muted); font-size: 13px; }
.skill-picker-item {
  display: flex; align-items: center; gap: 12px;
  padding: 12px; border-radius: var(--radius-sm);
  cursor: pointer; transition: all .15s;
  border: 1px solid transparent;
  margin-bottom: 6px;
}
.skill-picker-item:hover { background: var(--bg-soft); }
.skill-picker-item.selected {
  background: rgba(59, 130, 246, 0.08);
  border-color: rgba(59, 130, 246, 0.3);
}
.skill-picker-item.disabled { opacity: .45; cursor: not-allowed; }
.skill-picker-check {
  width: 20px; height: 20px; border-radius: 6px; flex-shrink: 0;
  border: 2px solid var(--border-strong);
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 700; color: var(--primary);
}
.skill-picker-item.selected .skill-picker-check {
  background: var(--primary); border-color: var(--primary); color: #fff;
}
.skill-picker-icon {
  width: 36px; height: 36px; border-radius: 9px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center; font-size: 18px;
}
.skill-picker-info { flex: 1; min-width: 0; }
.skill-picker-name { font-size: 13.5px; font-weight: 600; margin-bottom: 2px; }
.skill-picker-desc { font-size: 11.5px; color: var(--text-muted); line-height: 1.4; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.skill-picker-disabled { font-size: 10px; color: var(--text-muted); background: var(--bg-soft); padding: 2px 8px; border-radius: 4px; flex-shrink: 0; }
.skill-picker-footer {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 20px; border-top: 1px solid var(--border);
}
.skill-picker-count { font-size: 12.5px; color: var(--text-muted); }

.chat-area-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
.chat-area-head-left { flex: 1; min-width: 0; }
.chat-area-head-right { display: flex; gap: 6px; flex-shrink: 0; }
.chat-area-skills { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; align-items: center; }
.chat-skill-tag {
  font-size: 11px; padding: 2px 8px; border-radius: 6px;
  background: rgba(59, 130, 246, 0.1); color: var(--primary);
  border: 1px solid rgba(59, 130, 246, 0.2);
}
.chat-skill-edit { background: none; border: none; cursor: pointer; font-size: 12px; padding: 2px 4px; opacity: .6; }
.chat-skill-edit:hover { opacity: 1; }
.chat-session-skills { display: flex; flex-wrap: wrap; gap: 3px; margin-top: 4px; }
.session-skill-chip { font-size: 10px; padding: 1px 6px; border-radius: 4px; background: rgba(139, 92, 246, 0.1); color: var(--text-secondary); }

/* ===== 对话中心 · 当前模型指示器（可点击切换） ===== */
.chat-current-model-wrap { position: relative; }
.chat-current-model {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 4px 12px 4px 4px; border-radius: 24px;
  background: rgba(59, 130, 246, 0.08);
  border: 1px solid rgba(59, 130, 246, 0.18);
  cursor: pointer; user-select: none;
  transition: border-color .15s, box-shadow .15s;
}
.chat-current-model:hover { border-color: var(--primary); box-shadow: 0 0 10px rgba(59, 130, 246, 0.18); }
.chat-current-model-wrap.open .chat-current-model {
  border-color: var(--primary); box-shadow: 0 0 12px rgba(59, 130, 246, 0.22);
}
.chat-current-model-dot {
  width: 26px; height: 26px; border-radius: 50%;
  background: linear-gradient(135deg, #2563eb, #7c3aed);
  color: #fff; display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 12px; flex-shrink: 0;
}
.chat-current-model-text { display: flex; flex-direction: column; line-height: 1.2; }
.chat-current-model-name { font-size: 12px; font-weight: 600; color: var(--text); }
.chat-current-model-sub { font-size: 10.5px; color: var(--text-muted); }
.chat-current-model-arrow { font-size: 10px; color: var(--text-muted); margin-left: 2px; transition: transform .15s; }
.chat-current-model-wrap.open .chat-current-model-arrow { transform: rotate(180deg); }

.chat-model-menu {
  position: absolute; top: calc(100% + 8px); right: 0;
  min-width: 320px; max-width: 380px;
  background: var(--card); border: 1px solid var(--border);
  border-radius: 12px; box-shadow: 0 12px 36px rgba(0, 0, 0, 0.32);
  padding: 8px; z-index: 200; display: none;
  backdrop-filter: blur(8px);
}
.chat-current-model-wrap.open .chat-model-menu {
  display: block; animation: chatModelMenuFadeIn .12s ease-out;
}
@keyframes chatModelMenuFadeIn {
  from { opacity: 0; transform: translateY(-4px); }
  to   { opacity: 1; transform: translateY(0); }
}
.chat-model-menu-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 10px 8px; font-size: 12px; color: var(--text-muted);
  border-bottom: 1px solid var(--border); margin-bottom: 6px;
}
.chat-model-menu-link {
  background: none; border: none; color: var(--primary); cursor: pointer;
  font-size: 12px; padding: 0;
}
.chat-model-menu-link:hover { text-decoration: underline; }
.chat-model-menu-empty {
  padding: 18px 14px; text-align: center; font-size: 13px; color: var(--text-muted);
}
.chat-model-menu-list { display: flex; flex-direction: column; gap: 2px; max-height: 360px; overflow-y: auto; }
.chat-model-menu-item {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 10px; border-radius: 8px; cursor: pointer;
  transition: background .12s;
}
.chat-model-menu-item:hover { background: rgba(59, 130, 246, 0.08); }
.chat-model-menu-item.active { background: rgba(59, 130, 246, 0.14); }
.chat-model-menu-dot {
  width: 28px; height: 28px; border-radius: 50%; flex-shrink: 0;
  background: linear-gradient(135deg, #2563eb, #7c3aed);
  color: #fff; display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 12px;
}
.chat-model-menu-info { flex: 1; min-width: 0; }
.chat-model-menu-name {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; font-weight: 600; color: var(--text);
}
.chat-model-menu-tag {
  font-size: 10px; padding: 1px 7px; border-radius: 10px;
  background: rgba(34, 197, 94, 0.15); color: #22c55e; font-weight: 600;
}
.chat-model-menu-sub {
  font-size: 11px; color: var(--text-muted);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.chat-model-menu-check { color: #22c55e; font-weight: 700; font-size: 14px; }

.chat-session-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; align-items: center; }
.chat-session-model-chip {
  font-size: 10px; padding: 1px 7px; border-radius: 10px;
  background: rgba(59, 130, 246, 0.1); color: var(--primary);
  border: 1px solid rgba(59, 130, 246, 0.2); font-weight: 600;
  max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
/* ===== 右侧 · 工作空间文件面板 ===== */
.chat-files {
  flex-shrink: 0;
  border-left: 1px solid var(--border);
  background: var(--panel);
  display: flex; flex-direction: column;
  transition: width .18s ease;
  min-height: 0;
}
.chat-files.collapsed { width: 36px; }
.chat-files-head {
  display: flex; align-items: center;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-soft);
  flex-shrink: 0;
  overflow: visible;
}
.chat-files.collapsed .chat-files-head { padding: 10px 8px; justify-content: center; }
.chat-files-title-row {
  display: flex; align-items: center; justify-content: space-between;
  width: 100%; min-width: 0;
  gap: 8px;
  overflow: visible;
}
.chat-files-title {
  display: flex; align-items: center; gap: 6px;
  user-select: none;
  min-width: 0;
}
.chat-files-icon { font-size: 14px; flex-shrink: 0; }
.chat-files-sep { color: var(--text-muted); font-size: 14px; line-height: 1; }
.chat-files-name {
  font-size: 12.5px; font-weight: 600; color: var(--text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.chat-files.collapsed .chat-files-sep,
.chat-files.collapsed .chat-files-name,
.chat-files.collapsed .chat-files-arrow { display: none; }
.chat-files.collapsed .ws-picker { display: none; }
.chat-files-arrow { color: var(--text-muted); font-size: 10px; flex-shrink: 0; }
.chat-files-actions { display: flex; gap: 4px; flex-shrink: 0; align-items: center; }
.chat-files.collapsed .chat-files-actions { display: none; }
.chat-files-refresh {
  background: transparent; border: 1px solid var(--border);
  color: var(--text-muted); cursor: pointer;
  width: 22px; height: 22px; border-radius: 5px;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; padding: 0; line-height: 1;
}

/* ===== 工作空间选择器 ===== */
.ws-picker {
  position: relative;
  display: inline-flex;
  overflow: visible;
  font-family: inherit;
}
.ws-picker-trigger {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 10px 5px 8px;
  border: 1px solid var(--border, rgba(100, 116, 139, .25));
  border-radius: 9px;
  background: linear-gradient(180deg, rgba(255,255,255,.03), rgba(255,255,255,0)) , var(--bg);
  cursor: pointer;
  max-width: 220px;
  transition: border-color .18s ease, background .18s ease, box-shadow .18s ease, transform .12s ease;
  user-select: none;
  box-shadow: 0 1px 2px rgba(15, 23, 42, .04);
}
.ws-picker-trigger:hover {
  border-color: color-mix(in srgb, var(--accent, #8b5cf6) 55%, var(--border));
  background: var(--bg-soft);
  box-shadow: 0 2px 8px rgba(139, 92, 246, .12);
}
.ws-picker-trigger:active { transform: translateY(1px); }
.ws-picker-trigger-icon {
  flex-shrink: 0;
  width: 14px; height: 14px;
  filter: drop-shadow(0 1px 0 rgba(255,255,255,.4));
}
.ws-picker-name {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text, #0f172a);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  max-width: 150px;
  line-height: 1;
  letter-spacing: .1px;
}
.ws-picker-arrow {
  flex-shrink: 0;
  color: var(--text-muted, #64748b);
  transition: transform .2s ease, color .2s ease;
}
.ws-picker.open .ws-picker-trigger {
  border-color: var(--accent, #8b5cf6);
  background: color-mix(in srgb, var(--accent) 8%, var(--bg));
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 16%, transparent),
              0 2px 8px rgba(139, 92, 246, .18);
}
.ws-picker.open .ws-picker-arrow {
  transform: rotate(180deg);
  color: var(--accent);
}
.ws-picker-dropdown {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 999;
  min-width: 230px;
  max-width: 280px;
  background: var(--bg, #ffffff);
  border: 1px solid color-mix(in srgb, var(--border) 85%, var(--accent) 15%);
  border-radius: 14px;
  box-shadow:
    0 8px 24px rgba(15, 23, 42, .08),
    0 20px 48px rgba(15, 23, 42, .10),
    0 0 0 1px rgba(255, 255, 255, .2) inset;
  overflow: hidden;
  backdrop-filter: blur(10px);
  animation: wsPop .18s cubic-bezier(.2,.9,.3,1.1);
  transform-origin: top right;
}
@keyframes wsPop {
  from { opacity: 0; transform: translateY(-4px) scale(.98); }
  to   { opacity: 1; transform: translateY(0)    scale(1);    }
}
.ws-picker-header {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px 9px;
  background:
    linear-gradient(180deg,
      color-mix(in srgb, var(--accent, #8b5cf6) 10%, transparent),
      transparent 70%);
  border-bottom: 1px solid var(--border);
}
.ws-picker-header-icon {
  width: 28px; height: 28px; flex-shrink: 0;
  display: grid; place-items: center;
  background: color-mix(in srgb, var(--accent, #8b5cf6) 14%, transparent);
  border-radius: 8px;
  font-size: 14px;
}
.ws-picker-header-text { min-width: 0; }
.ws-picker-header-title {
  font-size: 12.5px; font-weight: 700; color: var(--text);
  line-height: 1.15;
  letter-spacing: .2px;
}
.ws-picker-header-sub {
  font-size: 10.5px; color: var(--text-muted, #64748b);
  line-height: 1.3; margin-top: 2px;
}
.ws-picker-list {
  max-height: 220px;
  overflow-y: auto;
  padding: 6px;
}
.ws-picker-list::-webkit-scrollbar { width: 6px; }
.ws-picker-list::-webkit-scrollbar-thumb {
  background: color-mix(in srgb, var(--border) 90%, var(--text-muted));
  border-radius: 3px;
}
.ws-picker-list::-webkit-scrollbar-thumb:hover {
  background: var(--text-muted);
}
.ws-picker-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 9px;
  margin: 1px 0;
  border-radius: 9px;
  cursor: pointer;
  color: var(--text, #0f172a);
  transition: background .12s ease, color .12s ease, transform .08s ease;
}
.ws-picker-item:hover {
  background: var(--bg-soft, #f1f5f9);
}
.ws-picker-item:active { transform: scale(.992); }
.ws-picker-item.selected {
  background: color-mix(in srgb, var(--accent, #8b5cf6) 14%, transparent);
  color: var(--accent, #7c3aed);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 30%, transparent);
}
.ws-picker-item-left {
  display: flex; align-items: center; gap: 7px;
  min-width: 0;
}
.ws-picker-item-check {
  flex-shrink: 0;
  color: var(--accent, #7c3aed);
}
.ws-picker-item-icon {
  font-size: 12.5px; flex-shrink: 0;
  filter: saturate(.9);
}
.ws-picker-item-name {
  font-size: 12.5px;
  font-weight: 500;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  max-width: 150px;
  line-height: 1;
}
.ws-picker-item.selected .ws-picker-item-name { font-weight: 600; }
.ws-picker-item-del {
  background: transparent;
  border: 1px solid transparent;
  color: var(--text-muted, #94a3b8);
  cursor: pointer;
  padding: 4px 5px;
  border-radius: 7px;
  display: inline-flex; align-items: center; justify-content: center;
  opacity: 0;
  transform: translateX(2px);
  transition: opacity .15s ease, color .15s ease, background .15s ease, border-color .15s ease, transform .15s ease;
}
.ws-picker-item:hover .ws-picker-item-del,
.ws-picker-item.selected .ws-picker-item-del { opacity: 1; transform: translateX(0); }
.ws-picker-item-del:hover {
  color: #ef4444;
  background: rgba(239, 68, 68, .09);
  border-color: rgba(239, 68, 68, .25);
}
.ws-picker-empty {
  padding: 18px 16px 20px;
  text-align: center;
  color: var(--text-muted, #64748b);
  font-size: 12px;
  line-height: 1.5;
}
.ws-picker-actions {
  padding: 8px;
  border-top: 1px solid var(--border);
  background: linear-gradient(0deg, var(--bg-soft, #f8fafc), transparent);
}
.ws-picker-btn-create {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  width: 100%;
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px dashed color-mix(in srgb, var(--accent, #8b5cf6) 45%, var(--border));
  background: color-mix(in srgb, var(--accent, #8b5cf6) 6%, transparent);
  color: var(--accent, #7c3aed);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: background .15s ease, border-color .15s ease, transform .1s ease;
}
.ws-picker-btn-create:hover {
  background: color-mix(in srgb, var(--accent, #8b5cf6) 12%, transparent);
  border-color: var(--accent);
  border-style: solid;
}
.ws-picker-btn-create:active { transform: scale(.99); }
.chat-files-refresh:hover { color: var(--primary); border-color: var(--primary); }

.chat-files-body { flex: 1; overflow-y: auto; padding: 4px 0; min-height: 0; }
.chat-files.collapsed .chat-files-body { display: none; }
.chat-files-empty {
  padding: 20px 16px; text-align: center; color: var(--text-muted);
  font-size: 12px; line-height: 1.5;
}
.chat-files-error { color: #ef4444; }

.chat-files-tree { display: flex; flex-direction: column; }
.chat-files-row {
  display: flex; align-items: center; gap: 4px;
  padding: 4px 8px 4px 0;
  font-size: 12.5px; color: var(--text);
  cursor: pointer; user-select: none;
  white-space: nowrap;
  transition: background .1s;
}
.chat-files-row:hover { background: var(--bg-soft); }
.chat-files-row.expanded { color: var(--primary); }
.chat-files-toggle {
  width: 12px; flex-shrink: 0; text-align: center;
  color: var(--text-muted); font-size: 9px; line-height: 1;
}
.chat-files-glyph { flex-shrink: 0; font-size: 13px; line-height: 1; }
.chat-files-label {
  flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis;
}
.chat-files-size {
  flex-shrink: 0; color: var(--text-muted); font-size: 10.5px;
  margin-left: auto; padding-left: 8px;
}

</style>
