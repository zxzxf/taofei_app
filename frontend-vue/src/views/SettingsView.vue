<template>
  <div class="settings-layout">
    <div class="settings-tabs">
      <button class="settings-tab" :class="{ active: tab === 'model' }" @click="tab = 'model'"><span>🔧</span> 模型与 API</button>
      <button class="settings-tab" :class="{ active: tab === 'appearance' }" @click="tab = 'appearance'"><span>🎨</span> 外观</button>
      <button class="settings-tab" :class="{ active: tab === 'notifications' }" @click="tab = 'notifications'"><span>🔔</span> 通知</button>
      <button class="settings-tab" :class="{ active: tab === 'data' }" @click="tab = 'data'"><span>📦</span> 数据管理</button>
      <button class="settings-tab" :class="{ active: tab === 'about' }" @click="tab = 'about'"><span>ℹ️</span> 关于</button>
    </div>
    <div class="settings-content">
      <div v-show="tab === 'model'" class="settings-panel active">
        <div class="settings-form">
          <div class="field">
            <label>配置名称</label>
            <input v-model="config.name" type="text" placeholder="例如：DeepSeek 主账号、OpenAI 备用、Anthropic 实验">
            <div class="hint">给这套配置起个名字，保存后会出现在下方列表中</div>
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
          <div class="field">
            <label>模型名称</label>
            <input v-model="config.model" type="text" placeholder="deepseek/deepseek-chat">
            <div class="hint">例如 deepseek/deepseek-chat、gpt-4o-mini、qwen/qwen-plus</div>
          </div>
          <div class="field">
            <label>API Key</label>
            <div class="key-row">
              <input v-model="config.apiKey" :type="showKey ? 'text' : 'password'" placeholder="输入 API Key">
              <button class="btn-ghost" @click="showKey = !showKey">{{ showKey ? '隐藏' : '显示' }}</button>
            </div>
          </div>
          <div class="field">
            <label>Base URL（可选）</label>
            <input v-model="config.baseUrl" type="text" placeholder="https://api.deepseek.com">
          </div>
          <div style="display:flex;justify-content:flex-end;gap:10px;align-items:center;flex-wrap:wrap;">
            <span v-if="testResult" class="test-result" :class="testResult.ok ? 'ok' : 'fail'">
              <template v-if="testResult.ok">✓ 连接成功（{{ testResult.latency_ms }} ms）</template>
              <template v-else>✗ {{ testResult.error }}<span v-if="testResult.latency_ms > 0">（{{ testResult.latency_ms }} ms）</span></template>
            </span>
            <button class="btn-ghost" :disabled="testing" @click="testConnection">
              {{ testing ? '测试中...' : '测试连接' }}
            </button>
            <button class="btn-save" :disabled="saving" @click="saveModel" style="background:linear-gradient(135deg,var(--primary),var(--purple));border:none;color:#fff;border-radius:8px;padding:9px 24px;font-size:14px;font-weight:600;cursor:pointer;">
              {{ saving ? '保存中...' : '保存模型配置' }}
            </button>
          </div>
          <div v-if="saveMessage" class="save-tip" :class="saveMessage.type">{{ saveMessage.text }}</div>
        </div>

        <!-- 已保存的配置列表 -->
        <div class="settings-form" style="margin-top:18px;">
          <div class="field-title">
            <span>已保存的配置</span>
            <span class="hint-inline">点击「使用」即可切换当前模型</span>
          </div>
          <div v-if="presets.length === 0" class="empty-tip">
            还没有保存的配置。填好上方表单后点击「保存模型配置」即可出现在这里。
          </div>
          <div v-else class="preset-list">
            <div
              v-for="p in presets"
              :key="p.id"
              class="preset-item"
              :class="{ active: p.id === activePresetId }"
            >
              <div class="preset-main">
                <div class="preset-name">
                  <span>{{ p.name }}</span>
                  <span v-if="p.id === activePresetId" class="badge-current">✓ 当前</span>
                </div>
                <div class="preset-meta">
                  <span class="chip">{{ p.provider }}</span>
                  <span class="preset-model">{{ p.model || '(未填)' }}</span>
                  <span v-if="p.base_url" class="preset-url">{{ p.base_url }}</span>
                </div>
                <div class="preset-key">
                  <span>API Key: {{ p.has_api_key ? p.api_key_masked : '未设置' }}</span>
                </div>
              </div>
              <div class="preset-actions">
                <button class="btn-ghost" :disabled="loadingId === p.id" @click="usePreset(p)">
                  {{ p.id === activePresetId ? '重新加载' : '使用' }}
                </button>
                <button class="btn-danger-text" :disabled="loadingId === p.id" @click="deletePreset(p)">
                  删除
                </button>
              </div>
            </div>
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
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'

const tab = ref('model')
const showKey = ref(false)
const config = ref({
  name: '',
  provider: 'deepseek',
  model: 'deepseek/deepseek-chat',
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
const saveMessage = ref(null)    // {type: 'ok'|'err', text: '...'}

function applyTheme() {
  document.body.classList.toggle('light-theme', themeMode.value === 'light')
  localStorage.setItem('theme', themeMode.value)
}

function applyBodyClass() {
  document.body.classList.toggle('no-glow', !glow.value)
  document.body.classList.toggle('compact', compact.value)
}

async function loadPresets() {
  try {
    const res = await fetch('/api/model-presets')
    const data = await res.json()
    presets.value = data.presets || []
    activePresetId.value = data.active_id || ''
  } catch (e) {
    console.error('加载预设列表失败', e)
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
  if (saving.value) return
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
    // 重新拉取列表，确保 server-side 排序/字段一致
    await loadPresets()
  } catch (e) {
    showSaveTip('err', '保存失败：' + e.message)
  } finally {
    saving.value = false
  }
}

async function usePreset(p) {
  if (loadingId.value) return
  loadingId.value = p.id
  try {
    // 如果是当前激活预设，仅做"重新加载"到表单
    if (p.id === activePresetId.value) {
      const detail = await fetch(`/api/model-presets/${p.id}`).catch(() => null)
      // 简化：直接从列表项加载（API Key 脱敏版，提示用户重新填）
      config.value = {
        name: p.name,
        provider: p.provider,
        model: p.model,
        apiKey: p.has_api_key ? '' : '',  // 不回填已脱敏的 key，避免误以为真值
        baseUrl: p.base_url,
      }
      showSaveTip('ok', `已重新加载「${p.name}」（API Key 请重新填写以查看完整值）`)
      return
    }
    const res = await fetch(`/api/model-presets/${p.id}/activate`, { method: 'POST' })
    const data = await res.json()
    if (!res.ok || data.ok === false) {
      showSaveTip('err', '切换失败：' + (data.error || res.statusText))
      return
    }
    activePresetId.value = data.active_id || p.id
    // 加载到表单（API Key 不回填脱敏值）
    config.value = {
      name: p.name,
      provider: p.provider,
      model: p.model,
      apiKey: '',
      baseUrl: p.base_url,
    }
    showSaveTip('ok', `已切换到「${p.name}」，后续调用将使用此配置`)
    await loadPresets()
  } catch (e) {
    showSaveTip('err', '切换失败：' + e.message)
  } finally {
    loadingId.value = ''
  }
}

async function deletePreset(p) {
  if (loadingId.value) return
  if (!confirm(`确定删除配置「${p.name}」？`)) return
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

function clearChat() {
  if (!confirm('确定清空所有对话记录？')) return
  localStorage.removeItem('chatSessions')
  alert('已清空')
}

function clearTask() {
  if (!confirm('确定清空所有任务记录？')) return
  alert('已清空')
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
  // 如果有当前激活预设，且表单 model 为空/默认值，自动填入（API Key 除外）
  const active = presets.value.find(p => p.id === activePresetId.value)
  if (active && !config.value.model) {
    config.value.provider = active.provider
    config.value.model = active.model
    config.value.baseUrl = active.base_url
  }
})
</script>
