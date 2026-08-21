<template>
  <div class="settings-layout">
    <div class="settings-tabs">
      <button class="settings-tab" :class="{ active: tab === 'model' }" @click="tab = 'model'"><span>🔧</span> 模型</button>
      <button class="settings-tab" :class="{ active: tab === 'appearance' }" @click="tab = 'appearance'"><span>🎨</span> 外观</button>
      <button class="settings-tab" :class="{ active: tab === 'notifications' }" @click="tab = 'notifications'"><span>🔔</span> 通知</button>
      <button class="settings-tab" :class="{ active: tab === 'data' }" @click="tab = 'data'"><span>📦</span> 备份</button>
      <button class="settings-tab" :class="{ active: tab === 'about' }" @click="tab = 'about'"><span>ℹ️</span> 关于</button>
      <button class="settings-tab" :class="{ active: tab === 'log' }" @click="switchLogTab"><span>📋</span> 日志</button>
    </div>
    <div class="settings-content">
      <div v-show="tab === 'model'" class="settings-panel active">
        <div class="model-config-page">
          <!-- 页面标题栏 -->
          <div class="model-page-header">
            <div class="model-page-title-group">
              <span class="model-page-icon">⚙</span>
              <div>
                <div class="model-page-title">模型配置</div>
                <div class="model-page-subtitle">管理AI模型服务商和API密钥</div>
              </div>
            </div>
            <button class="btn-primary-sm" @click="showForm = !showForm">
              {{ showForm ? '收起' : '+ 新建配置' }}
            </button>
          </div>

          <!-- 快速添加模板 -->
          <div class="quick-add-section">
            <div class="quick-add-title">模型模板 · 快速添加</div>
            <div class="quick-add-chips">
              <div
                v-for="p in providerList"
                :key="p.key"
                class="quick-chip"
                :class="{ added: isProviderAdded(p.key) }"
                @click="quickAdd(p)"
              >
                <span class="quick-chip-icon">{{ p.icon }}</span>
                <span class="quick-chip-name">{{ p.name }}</span>
                <span class="quick-chip-action">{{ isProviderAdded(p.key) ? '✓' : '+' }}</span>
              </div>
            </div>
          </div>

          <!-- 新建/编辑表单（可折叠） -->
          <div v-show="showForm" class="model-form-card">
            <div class="form-row-2col">
              <div class="field">
                <label>配置名称</label>
                <input v-model="config.name" type="text" placeholder="例如：DeepSeek 主账号">
              </div>
              <div class="field">
                <label>模型服务商</label>
                <select v-model="config.provider">
                  <option value="deepseek">DeepSeek</option>
                  <option value="openai">OpenAI</option>
                  <option value="qwen">通义千问</option>
                  <option value="glm">智谱 GLM</option>
                  <option value="moonshot">Moonshot</option>
                  <option value="ollama">Ollama</option>
                  <option value="custom">自定义</option>
                </select>
              </div>
            </div>
            <div class="form-row-2col">
              <div class="field">
                <label>模型名称</label>
                <input v-model="config.model" type="text" placeholder="deepseek-chat">
              </div>
              <div class="field">
                <label>Base URL</label>
                <input v-model="config.baseUrl" type="text" placeholder="https://api.deepseek.com">
              </div>
            </div>
            <div class="field">
              <label>API Key</label>
              <div class="key-row">
                <input v-model="config.apiKey" :type="showKey ? 'text' : 'password'" placeholder="输入 API Key">
                <button class="btn-ghost" @click="showKey = !showKey">{{ showKey ? '隐藏' : '显示' }}</button>
              </div>
            </div>
            <div class="form-actions">
              <span v-if="testResult" class="test-result" :class="testResult.ok ? 'ok' : 'fail'">
                <template v-if="testResult.ok">✓ {{ testResult.latency_ms }}ms</template>
                <template v-else>✗ {{ testResult.error }}</template>
              </span>
              <button class="btn-ghost" :disabled="testing" @click="testConnection">
                {{ testing ? '测试中...' : '测试连接' }}
              </button>
              <button class="btn-primary" :disabled="saving" @click="saveModel">
                {{ saving ? '保存中...' : '保存模型配置' }}
              </button>
            </div>
            <div v-if="saveMessage" class="save-tip" :class="saveMessage.type">{{ saveMessage.text }}</div>
          </div>

          <!-- 筛选栏 -->
          <div class="model-filter-bar">
            <div class="filter-counter">
              已保存配置 <strong>{{ filteredPresets.length }}</strong> / {{ presets.length }} 个
            </div>
            <div class="filter-search">
              <input v-model="searchQuery" type="text" placeholder="搜索配置名称或模型…">
            </div>
            <div class="filter-tabs">
              <button :class="{ active: filterTab === 'all' }" @click="filterTab = 'all'">全部</button>
              <button :class="{ active: filterTab === 'active' }" @click="filterTab = 'active'">当前</button>
              <button :class="{ active: filterTab === 'other' }" @click="filterTab = 'other'">其他</button>
            </div>
          </div>

          <!-- 配置列表 -->
          <div v-if="listLoading && presets.length === 0" class="empty-tip">加载中…</div>
          <div v-else-if="filteredPresets.length === 0" class="empty-tip">
            {{ presets.length === 0 ? '还没有保存的配置，点击「新建配置」开始' : '没有匹配的配置' }}
          </div>
          <div v-else class="preset-list" :class="{ 'preset-list-loading': listLoading }">
            <div
              v-for="p in paginatedPresets"
              :key="p.id"
              class="preset-card"
              :class="{ active: p.id === activePresetId }"
            >
              <div class="preset-card-icon">{{ getProviderIcon(p.provider) }}</div>
              <div class="preset-card-body">
                <div class="preset-card-top">
                  <span class="preset-card-name">{{ p.name }}</span>
                  <span v-if="p.id === activePresetId" class="badge-current">当前</span>
                  <span v-else class="badge-inactive">未启用</span>
                </div>
                <div class="preset-card-meta">
                  <span class="chip">{{ p.provider }}</span>
                  <span class="preset-model">{{ p.model || '(未填)' }}</span>
                  <span v-if="p.base_url" class="preset-url">{{ p.base_url }}</span>
                  <span v-if="visibleKeys[p.id]" class="preset-key">{{ getVisibleKey(p) }}</span>
                </div>
              </div>
              <div class="preset-card-actions">
                <button v-if="p.has_api_key" class="btn-icon btn-sm" :title="visibleKeys[p.id] ? '隐藏密钥' : '显示密钥'" @click="toggleKeyVisible(p)">
                  <svg v-if="!visibleKeys[p.id]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="16" height="16"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                  <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="16" height="16"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
                </button>
                <button class="btn-ghost btn-sm" :disabled="saving || loadingId === p.id" @click="usePreset(p)">
                  {{ p.id === activePresetId ? '✓' : '使用' }}
                </button>
                <button class="btn-danger-text btn-sm" :disabled="saving || loadingId === p.id || presets.length <= 1 || p.id === activePresetId" @click="deletePreset(p)">
                  删除
                </button>
              </div>
            </div>
          </div>

          <!-- 分页 -->
          <div v-if="totalPages > 1" class="preset-pagination">
            <button class="page-btn" :disabled="currentPage === 1" @click="goToPage(currentPage - 1)">‹</button>
            <button
              v-for="pg in pageNumbers"
              :key="pg"
              class="page-num"
              :class="{ active: pg === currentPage }"
              @click="goToPage(pg)"
            >{{ pg }}</button>
            <button class="page-btn" :disabled="currentPage === totalPages" @click="goToPage(currentPage + 1)">›</button>
            <span class="page-info">{{ currentPage }}/{{ totalPages }}页 · {{ filteredPresets.length }}条</span>
          </div>
        </div>
      </div>
      <div v-show="tab === 'appearance'" class="settings-panel active">
        <div class="settings-form">
          <div class="field">
            <label>界面主题</label>
            <select v-model="themeMode" @change="applyTheme">
              <option value="dark">深色模式</option>
              <option value="light">浅色模式</option>
              <option value="system">跟随系统</option>
            </select>
          </div>
          <div class="toggle-row">
            <div>
              <div class="toggle-title">霓虹光效</div>
              <div class="toggle-desc">为卡片和按钮添加科技蓝光晕</div>
            </div>
            <div class="switch" :class="{ on: glow }" @click="glow = !glow; applyBodyClass()"></div>
          </div>
          <div class="toggle-row">
            <div>
              <div class="toggle-title">紧凑模式</div>
              <div class="toggle-desc">减小卡片间距与字体大小</div>
            </div>
            <div class="switch" :class="{ on: compact }" @click="compact = !compact; applyBodyClass()"></div>
          </div>
        </div>
      </div>
      <div v-show="tab === 'notifications'" class="settings-panel active">
        <div class="settings-form">
          <div class="toggle-row">
            <div>
              <div class="toggle-title">任务完成提醒</div>
              <div class="toggle-desc">智能体任务执行完成后显示弹窗通知</div>
            </div>
            <div class="switch on"></div>
          </div>
          <div class="toggle-row">
            <div>
              <div class="toggle-title">错误告警</div>
              <div class="toggle-desc">执行失败或 API 异常时主动提醒</div>
            </div>
            <div class="switch on"></div>
          </div>
          <div class="toggle-row">
            <div>
              <div class="toggle-title">自动刷新日志</div>
              <div class="toggle-desc">在日志页面每 2 秒自动拉取新日志</div>
            </div>
            <div class="switch"></div>
          </div>
        </div>
      </div>
      <div v-show="tab === 'data'" class="settings-panel active">
        <div class="settings-form">
          <div class="field">
            <label>数据保留策略</label>
            <select v-model="retention">
              <option value="30">保留 30 天</option>
              <option value="90">保留 90 天</option>
              <option value="365">保留 1 年</option>
              <option value="0">永久保留</option>
            </select>
          </div>
          <div class="danger-zone">
            <div style="font-weight:700;margin-bottom:8px;color:var(--danger);">危险操作</div>
            <p style="font-size:13px;color:var(--text-secondary);margin-bottom:12px;">以下操作会清除本地数据，不可恢复。</p>
            <div style="display:flex;gap:10px;">
              <button class="btn-danger" style="background:rgba(239,68,68,.12);color:var(--danger);border:1px solid rgba(239,68,68,.25);border-radius:8px;padding:8px 18px;font-size:13px;cursor:pointer;" @click="clearChat">清空对话记录</button>
              <button class="btn-danger" style="background:rgba(239,68,68,.12);color:var(--danger);border:1px solid rgba(239,68,68,.25);border-radius:8px;padding:8px 18px;font-size:13px;cursor:pointer;" @click="clearTask">清空任务记录</button>
            </div>
          </div>
        </div>
      </div>
      <div v-show="tab === 'about'" class="settings-panel active">
        <div class="settings-form">
          <div class="field"><label>平台名称</label><input type="text" value="淘飞AI · 企业级AI智能体平台" disabled></div>
          <div class="field"><label>版本</label><input type="text" value="v2.0.0 (Vue)" disabled></div>
          <div class="field"><label>技术栈</label><input type="text" value="Vue 3 + Vite + FastAPI + CrewAI" disabled></div>
          <p style="font-size:13px;color:var(--text-secondary);line-height:1.7;">
            淘飞AI致力于打造零门槛、高效率、可私有化部署的企业级智能体平台。通过研究员、分析师等多 Agent 协作，帮助企业完成调研、分析、写作、决策等复杂任务。
          </p>
        </div>
      </div>

      <div v-show="tab === 'log'" class="settings-panel active">
        <div class="log-viewer">
          <div class="log-page-header">
            <div>
              <div class="log-page-title">系统日志</div>
              <div class="log-page-subtitle">实时查看平台运行日志</div>
            </div>
            <div class="log-header-actions">
              <span v-if="logLive" class="log-live-badge">● 实时</span>
              <button class="btn-ghost-sm" @click="loadLogs(1)">刷新</button>
            </div>
          </div>

          <div class="log-filter-bar">
            <select v-model="logFilter.level" @change="loadLogs(1)">
              <option value="">全部级别</option>
              <option value="INFO">INFO</option>
              <option value="WARNING">WARNING</option>
              <option value="ERROR">ERROR</option>
            </select>
            <select v-model="logFilter.source" @change="loadLogs(1)">
              <option value="">全部来源</option>
              <option v-for="s in logSources" :key="s" :value="s">{{ s }}</option>
            </select>
            <select v-model="logFilter.taskId" @change="loadLogs(1)">
              <option value="">全部任务</option>
              <option v-for="t in logTasks" :key="t.id" :value="t.id">{{ (t.topic || t.id).slice(0, 30) }}</option>
            </select>
            <input v-model="logFilter.keyword" placeholder="搜索关键词…" @keyup.enter="loadLogs(1)">
          </div>

          <div class="log-table-wrap">
            <table class="log-table">
              <thead>
                <tr>
                  <th style="width:170px">时间</th>
                  <th style="width:80px">级别</th>
                  <th style="width:110px">来源</th>
                  <th>消息</th>
                  <th style="width:180px">任务</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in logList" :key="r.time + r.message" :class="'log-row-' + r.level.toLowerCase()">
                  <td class="log-time">{{ formatTime(r.time) }}</td>
                  <td><span class="log-level" :class="r.level.toLowerCase()">{{ r.level }}</span></td>
                  <td class="log-source">{{ r.source }}</td>
                  <td class="log-msg">{{ r.message }}</td>
                  <td class="log-task">{{ r.task_id || '-' }}</td>
                </tr>
                <tr v-if="!logList.length && !logLoading">
                  <td colspan="5" class="log-empty">暂无日志</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="log-pagination">
            <span class="log-total">共 {{ logTotal }} 条</span>
            <button class="btn-ghost-sm" :disabled="logPage <= 1" @click="loadLogs(logPage - 1)">上一页</button>
            <span class="log-page-info">第 {{ logPage }} / {{ logTotalPages }} 页</span>
            <button class="btn-ghost-sm" :disabled="logPage >= logTotalPages" @click="loadLogs(logPage + 1)">下一页</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, reactive } from 'vue'
import wsManager from '../utils/wsManager.js'
import { appConfirm, appAlert } from '../utils/appDialog.js'

const tab = ref('model')
const showKey = ref(false)
const visibleKeys = reactive({})
const config = ref({
  name: '',
  provider: 'deepseek',
  model: 'deepseek-chat',
  apiKey: '',
  baseUrl: 'https://api.deepseek.com',
})
const themeMode = ref('dark')
const glow = ref(true)
const compact = ref(false)
const retention = ref('90')

// 模型预设列表状态
const presets = ref([])          // [{id, name, provider, model, base_url, has_api_key, api_key_masked, ...}]
const activePresetId = ref('')   // 后端当前激活预设 id
const loadingId = ref('')        // 正在操作（使用/删除）的预设 id，用于按钮 loading
const saving = ref(false)        // 保存按钮 loading
const listLoading = ref(false)   // 预设列表加载中
const saveMessage = ref(null)    // {type: 'ok'|'err', text: '...'}
const showForm = ref(false)      // 表单折叠
const searchQuery = ref('')      // 搜索关键词
const filterTab = ref('all')     // 筛选标签: all / active / other

// 服务商模板
const providerList = [
  { key: 'deepseek', name: 'DeepSeek', icon: '🧠', model: 'deepseek-chat', baseUrl: 'https://api.deepseek.com' },
  { key: 'openai', name: 'OpenAI', icon: '🌐', model: 'gpt-4o-mini', baseUrl: 'https://api.openai.com/v1' },
  { key: 'qwen', name: '通义千问', icon: '🌟', model: 'qwen-plus', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { key: 'glm', name: '智谱GLM', icon: '⚡', model: 'glm-4-flash', baseUrl: 'https://open.bigmodel.cn/api/paas/v4' },
  { key: 'moonshot', name: 'Moonshot', icon: '🌙', model: 'moonshot-v1-8k', baseUrl: 'https://api.moonshot.cn/v1' },
  { key: 'ollama', name: 'Ollama', icon: '🦙', model: 'llama3.2', baseUrl: 'http://localhost:11434' },
]

function isProviderAdded(key) {
  return presets.value.some(p => p.provider === key)
}

function quickAdd(p) {
  config.value = { name: p.name, provider: p.key, model: p.model, apiKey: '', baseUrl: p.baseUrl }
  showForm.value = true
}

function getProviderIcon(provider) {
  const p = providerList.find(x => x.key === provider)
  return p ? p.icon : '🔌'
}

// 筛选后的预设列表
const filteredPresets = computed(() => {
  let list = presets.value
  if (filterTab.value === 'active') list = list.filter(p => p.id === activePresetId.value)
  else if (filterTab.value === 'other') list = list.filter(p => p.id !== activePresetId.value)
  const q = searchQuery.value.trim().toLowerCase()
  if (q) list = list.filter(p =>
    (p.name || '').toLowerCase().includes(q) ||
    (p.model || '').toLowerCase().includes(q) ||
    (p.provider || '').toLowerCase().includes(q)
  )
  return list
})

// 分页
const currentPage = ref(1)
const pageSize = 4
const totalPages = computed(() => Math.max(1, Math.ceil(filteredPresets.value.length / pageSize)))
const paginatedPresets = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filteredPresets.value.slice(start, start + pageSize)
})
const pageNumbers = computed(() => {
  const pages = []
  for (let i = 1; i <= totalPages.value; i++) pages.push(i)
  return pages
})
function goToPage(pg) {
  currentPage.value = Math.max(1, Math.min(totalPages.value, pg))
}
watch(totalPages, (tp) => {
  if (currentPage.value > tp) currentPage.value = tp
})
watch([searchQuery, filterTab], () => { currentPage.value = 1 })

function applyTheme() {
  document.body.classList.toggle('light-theme', themeMode.value === 'light')
  localStorage.setItem('theme', themeMode.value)
}

function applyBodyClass() {
  document.body.classList.toggle('no-glow', !glow.value)
  document.body.classList.toggle('compact', compact.value)
}

async function loadPresets() {
  listLoading.value = true
  try {
    const res = await fetch('/api/model-presets')
    const data = await res.json()
    presets.value = data.presets || []
    activePresetId.value = data.active_id || ''
    // 跳转到包含当前激活预设的页
    if (activePresetId.value) {
      const idx = presets.value.findIndex(p => p.id === activePresetId.value)
      if (idx >= 0) currentPage.value = Math.floor(idx / pageSize) + 1
    }
  } catch (e) {
    console.error('加载预设列表失败', e)
  } finally {
    listLoading.value = false
    const tp = Math.max(1, Math.ceil(filteredPresets.value.length / pageSize))
    if (currentPage.value > tp) currentPage.value = tp
  }
}

function notifyModelChanged() {
  window.dispatchEvent(new Event('taofei-model-changed'))
}

const plainKeys = reactive({})

function getVisibleKey(p) {
  if (!p.has_api_key) return '未设置Key'
  return plainKeys[p.id] || p.api_key_masked
}

async function toggleKeyVisible(p) {
  const isVisible = visibleKeys[p.id]
  if (isVisible) {
    visibleKeys[p.id] = false
    return
  }
  try {
    const res = await fetch(`/api/model-presets/${p.id}/api-key`)
    const data = await res.json()
    if (res.ok && data.ok) {
      plainKeys[p.id] = data.api_key || ''
      visibleKeys[p.id] = true
    } else {
      showSaveTip('err', '获取密钥失败：' + (data.error || res.statusText))
    }
  } catch (e) {
    showSaveTip('err', '获取密钥失败：' + e.message)
  }
}

function showSaveTip(type, text, timeout = 2400) {
  saveMessage.value = { type, text }
  if (timeout > 0) {
    setTimeout(() => {
      if (saveMessage.value && saveMessage.value.text === text) {
        saveMessage.value = null
      }
    }, timeout)
  }
}

async function saveModel() {
  if (saving.value || loadingId.value) return
  if (!config.value.model.trim()) {
    showSaveTip('err', '请先填写模型名称')
    return
  }
  saving.value = true
  try {
    const res = await fetch('/api/model-presets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: config.value.name.trim(),
        provider: config.value.provider,
        model: config.value.model.trim(),
        api_key: config.value.apiKey,
        base_url: config.value.baseUrl,
      }),
    })
    const data = await res.json()
    if (!res.ok || data.ok === false) {
      showSaveTip('err', '保存失败：' + (data.error || res.statusText))
      return
    }
    const saved = data.preset || {}
    activePresetId.value = data.active_id || saved.id || ''
    showSaveTip('ok', `已保存为「${saved.name || '新配置'}」，已切换为当前模型`)
    showForm.value = false
    // 丢弃过期的 localStorage 缓存（保存成功后以后端配置为唯一真相源）
    try { localStorage.removeItem('model_config') } catch (e) { /* ignore */ }
    // 通知其他组件（如 ChatView）模型已变更
    notifyModelChanged()
    // 重新拉取列表，确保 server-side 排序/字段一致
    await loadPresets()
  } catch (e) {
    showSaveTip('err', '保存失败：' + e.message)
  } finally {
    saving.value = false
  }
}

async function usePreset(p) {
  if (saving.value || loadingId.value) return
  loadingId.value = p.id
  try {
    const res = await fetch(`/api/model-presets/${p.id}/activate`, { method: 'POST' })
    const data = await res.json()
    if (!res.ok || data.ok === false) {
      showSaveTip('err', '切换失败：' + (data.error || res.statusText))
      return
    }
    activePresetId.value = data.active_id || p.id
    // 把激活后的配置回填到表单（API Key 保留为空，由用户填回完整值或保持当前激活态）
    config.value = {
      name: p.name,
      provider: p.provider,
      model: p.model,
      apiKey: '',
      baseUrl: p.base_url,
    }
    showForm.value = true
    // 丢弃过期的 localStorage 缓存（以后端激活预设为准）
    try { localStorage.removeItem('model_config') } catch (e) { /* ignore */ }
    if (p.id === activePresetId.value) {
      showSaveTip('ok', `已使用「${p.name}」作为当前模型，后续对话将基于此配置`)
    }
    notifyModelChanged()
    await loadPresets()
  } catch (e) {
    showSaveTip('err', '切换失败：' + e.message)
  } finally {
    loadingId.value = ''
  }
}

async function deletePreset(p) {
  if (saving.value || loadingId.value) return
  if (presets.value.length <= 1) {
    showSaveTip('err', '至少保留一个模型配置，无法删除')
    return
  }
  if (p.id === activePresetId.value) {
    showSaveTip('err', '正在使用的配置不能删除，请先切换到其他配置')
    return
  }
  if (!(await appConfirm(`确定删除配置「${p.name}」？`))) return
  loadingId.value = p.id
  try {
    const res = await fetch(`/api/model-presets/${p.id}`, { method: 'DELETE' })
    const data = await res.json()
    if (!res.ok || data.ok === false) {
      showSaveTip('err', '删除失败：' + (data.error || res.statusText))
      return
    }
    activePresetId.value = data.active_id || ''
    showSaveTip('ok', `已删除「${p.name}」`)
    notifyModelChanged()
    await loadPresets()
  } catch (e) {
    showSaveTip('err', '删除失败：' + e.message)
  } finally {
    loadingId.value = ''
  }
}

const testing = ref(false)
const testResult = ref(null) // { ok, latency_ms, error, ... }

async function testConnection() {
  if (testing.value) return
  testing.value = true
  testResult.value = null
  try {
    const res = await fetch('/api/test-connection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: config.value.provider,
        model: config.value.model,
        api_key: config.value.apiKey,
        base_url: config.value.baseUrl,
      }),
    })
    testResult.value = await res.json()
  } catch (e) {
    testResult.value = { ok: false, error: '请求失败：' + e.message, latency_ms: 0 }
  } finally {
    testing.value = false
  }
}

async function clearChat() {
  if (!(await appConfirm('确定清空所有对话记录？'))) return
  localStorage.removeItem('chatSessions')
  await appAlert('已清空')
}

async function clearTask() {
  if (!(await appConfirm('确定清空所有任务记录？'))) return
  await appAlert('已清空')
}

onMounted(async () => {
  const savedTheme = localStorage.getItem('theme')
  if (savedTheme === 'light') themeMode.value = 'light'
  const savedConfig = localStorage.getItem('model_config')
  if (savedConfig) {
    try {
      Object.assign(config.value, JSON.parse(savedConfig))
    } catch (e) { /* ignore */ }
  }
  applyBodyClass()
  // 拉取后端预设列表
  await loadPresets()
  // 只要后端存在激活预设，就优先以后端激活配置覆盖表单（不管 localStorage 旧值与默认值），
  // 避免 localStorage 中缓存的错误配置（如旧 model/base_url）覆盖了正确的后端激活预设。
  const active = presets.value.find(p => p.id === activePresetId.value)
  if (active) {
    config.value.name = active.name
    config.value.provider = active.provider
    config.value.model = active.model
    config.value.baseUrl = active.base_url
    config.value.apiKey = ''  // API Key 不回填，由用户按需重新输入（保存时留空保留原 Key）
    // 丢弃 localStorage 中过期的旧缓存，避免下次打开再回填错误值
    try { localStorage.removeItem('model_config') } catch (e) { /* ignore */ }
  }
})

const logPage = ref(1)
const logPageSize = 50
const logTotal = ref(0)
const logList = ref([])
const logLoading = ref(false)
const logLive = ref(true)
const logFilter = reactive({ level: '', source: '', taskId: '', keyword: '' })
const logTasks = ref([])
const logSources = ['system', 'agent', 'workflow', 'model', 'integration']
let _logWsUnsub = null

const logTotalPages = computed(() => Math.max(1, Math.ceil(logTotal.value / logPageSize)))

function formatTime(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    const pad = (n) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  } catch { return iso }
}

async function loadLogs(page) {
  if (page) logPage.value = page
  logLoading.value = true
  try {
    const params = new URLSearchParams()
    params.set('limit', String(logPageSize))
    params.set('offset', String((logPage.value - 1) * logPageSize))
    if (logFilter.level) params.set('level', logFilter.level)
    if (logFilter.source) params.set('source', logFilter.source)
    if (logFilter.taskId) params.set('task_id', logFilter.taskId)
    if (logFilter.keyword) params.set('keyword', logFilter.keyword)
    const res = await fetch(`/api/logs?${params.toString()}`)
    const data = await res.json()
    logList.value = data.logs || []
    logTotal.value = data.total || 0
  } catch (e) {
    console.error('加载日志失败', e)
  } finally {
    logLoading.value = false
  }
}

async function loadLogTasks() {
  try {
    const res = await fetch('/api/log-tasks')
    const data = await res.json()
    logTasks.value = data.tasks || []
  } catch {}
}

function handleWsLog(record) {
  if (!logLive.value) return
  if (logPage.value > 1) return
  if (logFilter.level && record.level !== logFilter.level) return
  if (logFilter.source && record.source !== logFilter.source) return
  if (logFilter.taskId && record.task_id !== logFilter.taskId) return
  if (logFilter.keyword && !record.message.toLowerCase().includes(logFilter.keyword.toLowerCase())) return
  logList.value.unshift(record)
  if (logList.value.length > logPageSize) logList.value.pop()
  logTotal.value += 1
}

function toggleLogLive() {
  logLive.value = !logLive.value
  if (logLive.value) {
    _startWsLog()
    loadLogs(1)
  } else {
    _stopWsLog()
  }
}

function _startWsLog() {
  _stopWsLog()
  _logWsUnsub = wsManager.subscribeLogs(handleWsLog, logFilter.taskId || undefined)
}

function _stopWsLog() {
  if (_logWsUnsub) {
    _logWsUnsub()
    _logWsUnsub = null
  }
}

function switchLogTab() {
  tab.value = 'log'
  loadLogs(1)
  loadLogTasks()
  if (logLive.value) _startWsLog()
}

onUnmounted(() => {
  _stopWsLog()
})
</script>

<style scoped>
.log-viewer { display: flex; flex-direction: column; gap: 14px; height: calc(100vh - 120px); }
.log-page-header { display: flex; justify-content: space-between; align-items: flex-start; }
.log-page-title { font-size: 20px; font-weight: 600; color: var(--text); }
.log-page-subtitle { font-size: 12.5px; color: var(--text-secondary); margin-top: 2px; }
.log-header-actions { display: flex; align-items: center; gap: 8px; }
.log-live-badge { font-size: 11.5px; color: var(--success); font-weight: 600; animation: logPulse 1.5s ease-in-out infinite; }
@keyframes logPulse { 0%,100% { opacity:1 } 50% { opacity:.4 } }
.btn-ghost-sm { padding: 5px 10px; font-size: 12px; border: 1px solid var(--border); border-radius: 6px; background: transparent; color: var(--text-secondary); cursor: pointer; transition: all .2s; }
.btn-ghost-sm:hover { border-color: var(--primary); color: var(--primary); }
.btn-ghost-sm:disabled { opacity: .4; cursor: not-allowed; }

.log-filter-bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.log-filter-bar select, .log-filter-bar input {
  padding: 5px 10px; font-size: 12.5px; background: var(--bg-card);
  border: 1px solid var(--border); border-radius: 6px; color: var(--text);
  outline: none; transition: border-color .2s;
}
.log-filter-bar select:focus, .log-filter-bar input:focus { border-color: var(--primary); }
.log-filter-bar input { min-width: 180px; }

.log-table-wrap { flex: 1; overflow: auto; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-card); }
.log-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.log-table th {
  position: sticky; top: 0; background: var(--bg-soft); color: var(--text-secondary);
  font-weight: 500; text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border);
  font-size: 12px;
}
.log-table td { padding: 6px 12px; border-bottom: 1px solid var(--border-subtle); vertical-align: top; }
.log-table tr:last-child td { border-bottom: none; }
.log-row-warning { background: rgba(245, 158, 11, 0.04); }
.log-row-error { background: rgba(239, 68, 68, 0.05); }
.log-time { color: var(--text-secondary); font-family: 'Monaco', 'Menlo', monospace; font-size: 11.5px; white-space: nowrap; }
.log-level { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 10.5px; font-weight: 600; }
.log-level.info { background: rgba(59, 130, 246, 0.12); color: #60a5fa; }
.log-level.warning { background: rgba(245, 158, 11, 0.15); color: #f59e0b; }
.log-level.error { background: rgba(239, 68, 68, 0.15); color: #ef4444; }
.log-source { color: var(--text-secondary); font-size: 12px; }
.log-msg { color: var(--text); line-height: 1.5; word-break: break-all; }
.log-task { color: var(--text-muted); font-family: 'Monaco', 'Menlo', monospace; font-size: 11px; }
.log-empty { text-align: center; padding: 40px 0; color: var(--text-muted); font-size: 13px; }

.log-pagination { display: flex; justify-content: space-between; align-items: center; padding: 4px 0; }
.log-total { font-size: 12.5px; color: var(--text-secondary); }
.log-page-info { font-size: 12.5px; color: var(--text-muted); }
</style>
