<template>
  <div class="task-layout">
    <div class="task-nav">
      <button class="task-nav-item" :class="{ active: section === 'input' }" @click="section = 'input'"><span>📝</span> 新建任务</button>
      <button class="task-nav-item" :class="{ active: section === 'result' }" @click="section = 'result'"><span>📄</span> 运行结果</button>
      <button class="task-nav-item" :class="{ active: section === 'flow' }" @click="section = 'flow'"><span>🧩</span> 可视化编排</button>
    </div>
    <div class="task-content">
      <div v-show="section === 'input'" class="task-panel active">
        <div class="hero-input">
          <h1>今天想让 AI 帮你做什么？</h1>
          <p>输入一个主题，研究员 Agent 负责调研，分析师 Agent 负责成稿</p>
          <div class="input-box">
            <input v-model="topic" type="text" placeholder="例如：网络安全态势感知技术，或 AI 智能体框架…" @keydown.enter="runTask">
            <button class="btn-run" @click="runTask">▶ 开始运行</button>
          </div>
        </div>
        <div class="card-title" style="margin-bottom:12px;">📌 推荐模板</div>
        <div class="template-grid">
          <div class="template-card" v-for="t in templates" :key="t.title" @click="topic = t.topic">
            <div class="t-icon">{{ t.icon }}</div>
            <div class="t-title">{{ t.title }}</div>
            <div class="t-desc">{{ t.desc }}</div>
          </div>
        </div>
      </div>
      <div v-show="section === 'result'" class="task-panel active">
        <div v-if="running" class="status-bar">
          <div class="spinner"></div>
          <span>任务执行中…</span>
        </div>
        <div v-if="error" class="error-box">{{ error }}</div>
        <div v-if="result" class="result-card" style="margin-top:18px;">
          <div class="result-head">
            <span style="font-weight:700;font-size:15px;">📄 生成报告</span>
            <button class="btn-copy" @click="copyResult">复制全文</button>
          </div>
          <div class="md" v-html="renderMd(result)"></div>
        </div>
      </div>
      <div v-show="section === 'flow'" class="task-panel active">
        <div class="flow-toolbar">
          <input v-model="flowName" type="text" placeholder="工作流名称" style="min-width:160px">
          <button class="btn-mini">💾 保存</button>
          <button class="btn-mini run">▶ 运行</button>
          <span style="font-size:12px;color:var(--text-muted);margin-left:auto">可视化编排功能开发中</span>
        </div>
        <div class="flow-wrap">
          <div class="flow-palette">
            <div class="flow-palette-title">节点类型</div>
            <div class="flow-palette-item">🔄 LLM 节点</div>
            <div class="flow-palette-item">🔗 HTTP 节点</div>
            <div class="flow-palette-item">🔀 条件分支</div>
            <div class="flow-palette-item">📝 文本处理</div>
          </div>
          <div class="flow-canvas-box">
            <div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted);font-size:14px;">
              点击节点类型添加到画布
            </div>
          </div>
          <div class="flow-config glass-card" style="padding:16px">
            <div style="font-size:13px;color:var(--text-muted)">点击节点或连线进行配置</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const section = ref('input')
const topic = ref('')
const running = ref(false)
const result = ref('')
const error = ref('')
const flowName = ref('')

const templates = [
  { icon: '📊', title: '行业调研报告', desc: '针对特定行业进行深度调研，生成结构化分析报告', topic: 'AI智能体行业调研报告' },
  { icon: '🔬', title: '技术深度分析', desc: '分析技术原理、应用场景与发展趋势', topic: '大语言模型技术分析' },
  { icon: '📝', title: '营销文案', desc: '生成品牌营销内容与推广文案', topic: '智能体产品营销文案' },
  { icon: '🚀', title: '商业计划书', desc: '撰写完整的商业计划与可行性分析', topic: 'AI创业项目商业计划书' },
]

async function runTask() {
  if (!topic.value.trim()) return
  running.value = true
  error.value = ''
  result.value = ''
  section.value = 'result'
  try {
    const res = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic: topic.value })
    })
    const data = await res.json()
    if (data.error) { error.value = data.error; return }
    result.value = data.report || data.result || '（无结果）'
  } catch (e) {
    error.value = '请求失败：' + e.message
  } finally {
    running.value = false
  }
}

function copyResult() {
  navigator.clipboard.writeText(result.value)
}

function renderMd(text) {
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
</script>
