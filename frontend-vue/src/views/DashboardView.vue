<template>
  <div class="dashboard-layout">
    <div class="dashboard-nav">
      <button class="dash-nav-item" :class="{ active: section === 'overview' }" @click="section = 'overview'"><span>📊</span> 数据概览</button>
      <button class="dash-nav-item" :class="{ active: section === 'orchestration' }" @click="section = 'orchestration'"><span>🔄</span> 智能体编排</button>
      <button class="dash-nav-item" :class="{ active: section === 'trend' }" @click="section = 'trend'"><span>📈</span> 任务趋势</button>
      <button class="dash-nav-item" :class="{ active: section === 'agents' }" @click="section = 'agents'"><span>🔥</span> 热门智能体</button>
      <button class="dash-nav-item" :class="{ active: section === 'activity' }" @click="section = 'activity'"><span>🔔</span> 最近动态</button>
      <button class="dash-nav-item" :class="{ active: section === 'quickstart' }" @click="section = 'quickstart'"><span>🚀</span> 快速开始</button>
    </div>
    <div class="dashboard-content">
      <div v-show="section === 'overview'" class="dash-panel active">
        <div class="stats-grid">
          <div class="stat-card" v-for="s in stats" :key="s.label" :class="s.color">
            <div class="stat-label">{{ s.label }}</div>
            <div class="stat-row">
              <div class="stat-value">{{ s.value }}</div>
            </div>
            <div class="stat-trend" :class="{ down: s.trend < 0 }">{{ s.trend >= 0 ? '↑' : '↓' }} {{ Math.abs(s.trend) }}% 较上周</div>
          </div>
        </div>
      </div>
      <div v-show="section === 'orchestration'" class="dash-panel active">
        <div class="glass-card">
          <div class="card-head">
            <div class="card-title">🔄 智能体编排</div>
          </div>
          <div class="dash-flow-diagram">
            <div class="dash-flow-node primary"><div class="dash-node-title">用户触发</div><div class="dash-node-desc">自然语言输入</div></div>
            <span class="dash-flow-arrow">→</span>
            <div class="dash-flow-node"><div class="dash-node-title">需求理解</div><div class="dash-node-desc">意图识别分析</div></div>
            <span class="dash-flow-arrow">→</span>
            <div class="dash-flow-node"><div class="dash-node-title">知识检索</div><div class="dash-node-desc">企业知识库</div></div>
            <span class="dash-flow-arrow">→</span>
            <div class="dash-flow-node"><div class="dash-node-title">规划分析</div><div class="dash-node-desc">多智能体协同</div></div>
            <span class="dash-flow-arrow">→</span>
            <div class="dash-flow-node"><div class="dash-node-title">任务执行</div><div class="dash-node-desc">调用工具/流程</div></div>
            <span class="dash-flow-arrow">→</span>
            <div class="dash-flow-node primary"><div class="dash-node-title">输出结果</div><div class="dash-node-desc">结构化交付</div></div>
          </div>
        </div>
      </div>
      <div v-show="section === 'trend'" class="dash-panel active">
        <div class="glass-card">
          <div class="card-head">
            <div class="card-title">📈 任务执行趋势</div>
            <div class="card-sub">近 7 天</div>
          </div>
          <div class="chart-wrap" style="height:220px;">
            <canvas ref="chartRef"></canvas>
          </div>
        </div>
      </div>
      <div v-show="section === 'agents'" class="dash-panel active">
        <div class="glass-card">
          <div class="card-head">
            <div class="card-title">🔥 热门智能体</div>
          </div>
          <div class="agent-grid">
            <div class="agent-card" v-for="a in agents" :key="a.name">
              <div class="agent-icon">{{ a.icon }}</div>
              <div class="agent-name">{{ a.name }}</div>
              <div class="agent-desc">{{ a.desc }}</div>
              <div class="agent-meta">
                <span>{{ a.uses }} 次使用</span>
                <button class="agent-btn">使用</button>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div v-show="section === 'activity'" class="dash-panel active">
        <div class="glass-card">
          <div class="card-head"><div class="card-title">🔔 最近动态</div></div>
          <div class="activity-list">
            <div class="activity-item" v-for="(a, i) in activities" :key="i">
              <span class="activity-dot" :style="{ background: a.color }"></span>
              <span>{{ a.text }}</span>
              <span class="activity-tag">{{ a.tag }}</span>
            </div>
          </div>
        </div>
      </div>
      <div v-show="section === 'quickstart'" class="dash-panel active">
        <div class="glass-card">
          <div class="card-head"><div class="card-title">🚀 快速开始</div></div>
          <p style="color:var(--text-secondary);font-size:13px;line-height:1.7;margin-bottom:14px;">
            在「任务编排」中输入任意主题，研究员 + 分析师双 Agent 将自动调研并生成结构化报告。
          </p>
          <button class="btn-primary" @click="$router.push('/task')">立即创建任务</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch, nextTick } from 'vue'

const section = ref('overview')
const chartRef = ref(null)

const stats = ref([
  { label: '任务总数', value: 0, trend: 0, color: '' },
  { label: '智能体数量', value: 0, trend: 0, color: 'cyan' },
  { label: '知识文档', value: 0, trend: 0, color: 'green' },
  { label: '节省人效', value: '0h', trend: 0, color: 'purple' },
])

const agents = ref([])
const trendData = ref({ labels: [], data: [] })
const activities = ref([])

async function loadStats() {
  try {
    const res = await fetch('/api/dashboard/stats')
    if (!res.ok) return
    const d = await res.json()
    stats.value = [
      { label: '任务总数', value: d.total ?? 0, trend: d.success_rate ?? 0, color: '' },
      { label: '智能体数量', value: d.agents ?? 0, trend: d.success_rate ?? 0, color: 'cyan' },
      { label: '知识文档', value: d.completed ?? 0, trend: d.success_rate ?? 0, color: 'green' },
      { label: '节省人效', value: (d.saved_hours ?? 0) + 'h', trend: d.success_rate ?? 0, color: 'purple' },
    ]
  } catch (e) { console.warn('dashboard stats failed', e) }
}

async function loadTrend() {
  try {
    const res = await fetch('/api/dashboard/trend')
    if (!res.ok) return
    const d = await res.json()
    trendData.value = d
    if (section.value === 'trend') {
      nextTick(() => drawTrendChart())
    }
  } catch (e) { console.warn('dashboard trend failed', e) }
}

async function loadAgents() {
  try {
    const res = await fetch('/api/dashboard/agents')
    if (!res.ok) return
    const d = await res.json()
    agents.value = (d.agents || []).map(a => ({
      icon: a.icon, name: a.name, desc: a.desc, uses: a.runs,
    }))
  } catch (e) { console.warn('dashboard agents failed', e) }
}

async function loadActivities() {
  try {
    const res = await fetch('/api/dashboard/activities?limit=10')
    if (!res.ok) return
    const d = await res.json()
    activities.value = (d.activities || []).map(a => ({
      text: a.text, tag: a.tag, color: a.color,
    }))
  } catch (e) { console.warn('dashboard activities failed', e) }
}

function drawTrendChart() {
  const canvas = chartRef.value
  if (!canvas) return
  const w = canvas.offsetWidth
  const h = canvas.offsetHeight
  if (!w || !h) return
  canvas.width = w; canvas.height = h
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, w, h)
  const data = trendData.value.data || []
  if (!data.length) return
  const max = Math.max(...data, 1)
  const padTop = 15, padBottom = 25, padLeft = 5, padRight = 5
  const chartH = h - padTop - padBottom
  const chartW = w - padLeft - padRight
  const step = chartW / data.length

  // grid lines
  ctx.strokeStyle = 'rgba(255,255,255,0.06)'
  ctx.lineWidth = 1
  for (let i = 0; i <= 4; i++) {
    const y = padTop + (chartH / 4) * i
    ctx.beginPath()
    ctx.moveTo(padLeft, y)
    ctx.lineTo(w - padRight, y)
    ctx.stroke()
  }

  // area fill
  ctx.fillStyle = 'rgba(59, 130, 246, 0.15)'
  ctx.beginPath()
  data.forEach((v, i) => {
    const x = padLeft + step * (i + 0.5)
    const y = padTop + chartH - (v / max) * chartH
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y)
  })
  ctx.lineTo(padLeft + chartW, padTop + chartH)
  ctx.lineTo(padLeft, padTop + chartH)
  ctx.closePath()
  ctx.fill()

  // line
  ctx.strokeStyle = '#3b82f6'
  ctx.lineWidth = 2
  ctx.beginPath()
  data.forEach((v, i) => {
    const x = padLeft + step * (i + 0.5)
    const y = padTop + chartH - (v / max) * chartH
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y)
  })
  ctx.stroke()

  // dots
  ctx.fillStyle = '#3b82f6'
  data.forEach((v, i) => {
    const x = padLeft + step * (i + 0.5)
    const y = padTop + chartH - (v / max) * chartH
    ctx.beginPath()
    ctx.arc(x, y, 3.5, 0, Math.PI * 2)
    ctx.fill()
  })

  // value labels
  ctx.fillStyle = '#94a3b8'
  ctx.font = '11px sans-serif'
  ctx.textAlign = 'center'
  data.forEach((v, i) => {
    const x = padLeft + step * (i + 0.5)
    const y = padTop + chartH - (v / max) * chartH
    ctx.fillText(String(v), x, y - 8)
  })
}

onMounted(async () => {
  await Promise.all([loadStats(), loadTrend(), loadAgents(), loadActivities()])
  nextTick(() => { if (section.value === 'trend') drawTrendChart() })
})

watch(section, (v) => { if (v === 'trend') nextTick(() => drawTrendChart()) })
</script>
