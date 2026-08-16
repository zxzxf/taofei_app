<template>
  <div class="chat-view">
    <div class="chat-sessions">
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
            <div v-if="s.skills && s.skills.length" class="chat-session-skills">
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
import { ref, computed, onMounted, nextTick, watch } from 'vue'

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
      skills: [...tempSelectedSkills.value]
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

function generateReply(text, skills) {
  const t = text.toLowerCase().trim()

  if (/^(你好|您好|hi|hello|嗨|hey|哈喽)/i.test(t)) {
    return '你好！我是淘飞AI助手，有什么可以帮你的吗？\n\n你可以问我问题，或者使用 `@技能名` 来调用已安装的技能。'
  }

  if (/^(你是谁|介绍.*自己|你叫什么)/i.test(t)) {
    return '我是**淘飞AI助手**，一个集成式的AI工作平台助手。\n\n我可以帮助你：\n- 回答问题和进行对话\n- 调用已安装的技能（如代码审查、天气查询等）\n- 管理和编排任务\n\n有什么需要帮忙的？'
  }

  if (/天气|weather/i.test(t)) {
    const cityMatch = t.match(/([\u4e00-\u9fa5]{2,})\s*天气/) || t.match(/天气.*?([\u4e00-\u9fa5]{2,})/)
    const city = cityMatch ? cityMatch[1] : '北京'
    return `如需查询天气，请前往「集成管理 → 天气查询」页面，输入城市名即可获取实时天气数据。\n\n当前查询城市：${city}\n（天气数据由 Open-Meteo API 提供）`
  }

  if (/时间|几点|现在/i.test(t)) {
    const now = new Date()
    return `现在是 **${now.toLocaleString('zh-CN', { dateStyle: 'full', timeStyle: 'short' })}**`
  }

  if (/谢谢|感谢|thx|thanks/i.test(t)) {
    return '不客气！有问题随时问我 😊'
  }

  if (/再见|拜拜|bye/i.test(t)) {
    return '再见！期待下次与你交流 👋'
  }

  if (/代码|code|bug|错误|报错/i.test(t)) {
    const hasCodeSkill = skills && skills.some(s => s.name.includes('code') || s.name.includes('Code'))
    if (hasCodeSkill) {
      return '检测到你已启用 **code-reviewer** 技能。\n\n请将需要审查的代码粘贴到对话框中，我会帮你分析代码质量、潜在问题和改进建议。'
    }
    return '我可以帮你分析代码问题。请将代码粘贴到对话框中，包括错误信息（如果有）。\n\n你也可以在「集成管理 → 技能管理」中添加 **Claude Code** 或 **code-reviewer** 技能来获得更专业的代码审查能力。'
  }

  if (/技能|skill|功能/i.test(t)) {
    const skillCount = skills ? skills.length : 0
    if (skillCount > 0) {
      const names = skills.map(s => `- ${s.icon || '🛠️'} ${s.name}`).join('\n')
      return `当前会话已携带 **${skillCount}** 个技能：\n${names}\n\n你可以通过对话让我调用这些技能，或在「集成管理」中管理更多技能。`
    }
    return '当前会话未携带技能。\n\n你可以在新建会话时选择技能，或前往「集成管理 → 技能管理」添加和管理技能。\n\n可用的技能模板包括：Claude Code、Cursor AI、GitHub Copilot、网页搜索、图片生成、PDF 解析等。'
  }

  if (/帮助|help|怎么用|使用/i.test(t)) {
    return '## 使用指南\n\n**1. 对话交流** — 直接输入问题，我会尽力回答\n\n**2. 技能调用** — 新建会话时选择技能，AI 会自动调用\n\n**3. 天气查询** — 在「集成管理 → 天气查询」中查天气\n\n**4. 技能管理** — 在「集成管理 → 技能管理」中添加/管理技能\n\n**5. 任务编排** — 在「任务编排」中创建自动化工作流'
  }

  if (t.includes('?') || t.includes('？') || t.includes('什么') || t.includes('怎么') || t.includes('如何')) {
    return `关于「${text}」这个问题，我的理解是：\n\n这是一个很好的问题。目前我作为一个本地AI助手，能够处理常见的对话和任务。\n\n如果你需要更专业的能力，建议：\n- 添加相关技能（如 Claude Code 用于编程、网页搜索用于信息检索）\n- 在任务编排中创建自动化流程\n\n有什么其他问题我可以帮忙解答吗？`
  }

  const responses = [
    `收到你的消息：「${text}」\n\n我理解你想了解更多关于这方面的信息。请告诉我更具体的需求，我会尽力帮助你。\n\n💡 提示：你可以使用「帮助」查看完整的使用指南。`,
    `关于「${text}」，我的想法是：\n\n这取决于具体的使用场景。如果你能提供更多上下文，我可以给出更有针对性的建议。\n\n你可以尝试：\n- 输入「帮助」查看功能列表\n- 输入「技能」查看可用技能\n- 输入「天气 + 城市名」获取天气信息`,
    `这是一个有意思的话题。目前我作为本地AI助手，主要支持：\n\n- 日常对话与问答\n- 技能管理与调用\n- 天气查询\n- 使用指南\n\n请告诉我你具体需要什么帮助，我会尽力协助你。`,
  ]

  return responses[Math.floor(Math.random() * responses.length)]
}

async function send() {
  const text = inputText.value.trim()
  if (!text) return
  const s = currentSession.value
  if (!s) { openNewSessionDialog(); return }
  s.messages.push({ role: 'user', text, time: Date.now() })
  s.title = text.slice(0, 20)
  inputText.value = ''
  await scrollToBottom()

  try {
    await new Promise(r => setTimeout(r, 600 + Math.random() * 400))
    const reply = generateReply(text, s.skills)
    s.messages.push({ role: 'ai', text: reply, time: Date.now() })
    s.time = Date.now()
  } catch (e) {
    s.messages.push({ role: 'ai', text: '请求失败：' + e.message, time: Date.now() })
  }
  saveSessions()
  await scrollToBottom()
}

async function scrollToBottom() {
  await nextTick()
  if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
}

function saveSessions() {
  localStorage.setItem('chatSessions', JSON.stringify(sessions.value))
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

onMounted(() => {
  loadSessions()
  loadAvailableSkills()
  if (!sessions.value.length) {
    openNewSessionDialog()
  }
})

watch(currentId, () => scrollToBottom())
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
</style>
