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
          <div style="display:flex;justify-content:flex-end;gap:10px;">
            <button class="btn-ghost" @click="testConnection">测试连接</button>
            <button class="settings-form btn-save" style="background:linear-gradient(135deg,var(--primary),var(--purple));border:none;color:#fff;border-radius:8px;padding:9px 24px;font-size:14px;font-weight:600;cursor:pointer;" @click="saveModel">保存模型配置</button>
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
const config = ref({ provider: 'deepseek', model: 'deepseek/deepseek-chat', apiKey: '', baseUrl: 'https://api.deepseek.com' })
const themeMode = ref('dark')
const glow = ref(true)
const compact = ref(false)
const retention = ref('90')

function applyTheme() {
  document.body.classList.toggle('light-theme', themeMode.value === 'light')
  localStorage.setItem('theme', themeMode.value)
}

function applyBodyClass() {
  document.body.classList.toggle('no-glow', !glow.value)
  document.body.classList.toggle('compact', compact.value)
}

async function saveModel() {
  try {
    await fetch('/api/model_config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config.value)
    })
    alert('模型配置已保存')
  } catch (e) {
    alert('保存失败：' + e.message)
  }
}

async function testConnection() {
  alert('测试连接功能开发中')
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

onMounted(() => {
  const savedTheme = localStorage.getItem('theme')
  if (savedTheme === 'light') themeMode.value = 'light'
  applyBodyClass()
})
</script>
