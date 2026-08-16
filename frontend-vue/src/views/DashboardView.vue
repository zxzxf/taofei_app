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
          <div class="flow-diagram">
            <div class="flow-node primary"><div class="node-title">用户触发</div><div class="node-desc">自然语言输入</div></div>
            <span class="flow-arrow">→</span>
            <div class="flow-node"><div class="node-title">需求理解</div><div class="node-desc">意图识别分析</div></div>
            <span class="flow-arrow">→</span>
            <div class="flow-node"><div class="node-title">知识检索</div><div class="node-desc">企业知识库</div></div>
            <span class="flow-arrow">→</span>
            <div class="flow-node"><div class="node-title">规划分析</div><div class="node-desc">多智能体协同</div></div>
            <span class="flow-arrow">→</span>
            <div class="flow-node"><div class="node-title">任务执行</div><div class="node-desc">调用工具/流程</div></div>
            <span class="flow-arrow">→</span>
            <div class="flow-node primary"><div class="node-title">输出结果</div><div class="node-desc">结构化交付</div></div>
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

const agents = ref([
  { icon: '🔬', name: '研究员', desc: '深度调研指定主题，整理行业信息', uses: 128 },
  { icon: '📊', name: '分析师', desc: '数据驱动的分析与决策支持', uses: 96 },
  { icon: '✍️', name: '文案师', desc: '品牌营销内容与创意文案生成', uses: 72 },
  { icon: '🔍', name: '检索员', desc: '知识库语义检索与精准问答', uses: 54 },
])

const activities = ref([
  { text: '研究员完成「AI智能体框架」调研', tag: '任务', color: '#3b82f6' },
  { text: '新增技能「天气查询」已接入', tag: '集成', color: '#10b981' },
  { text: 'DeepSeek 模型连接正常', tag: '系统', color: '#64748b' },
])

function drawTrendChart() {
  const canvas = chartRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  const w = canvas.offsetWidth, h = canvas.offsetHeight
  canvas.width = w; canvas.height = h
  ctx.clearRect(0, 0, w, h)
  const data = [3, 5, 4, 7, 6, 9, 8]
  const max = Math.max(...data, 1)
  const pw = w / data.length
  ctx.strokeStyle = '#3b82f6'
  ctx.lineWidth = 2
  ctx.beginPath()
  data.forEach((v, i) => {
    const x = pw * (i + 0.5)
    const y = h - (v / max) * (h - 20) - 10
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y)
  })
  ctx.stroke()
  ctx.fillStyle = 'rgba(59, 130, 246, 0.1)'
  ctx.beginPath()
  data.forEach((v, i) => {
    const x = pw * (i + 0.5)
    const y = h - (v / max) * (h - 20) - 10
    if (i === 0) ctx.moveTo(x, h); else ctx.lineTo(x, y)
  })
  ctx.lineTo(w - pw * 0.5, h)
  ctx.closePath()
  ctx.fill()
}

onMounted(() => {
  nextTick(() => { if (section.value === 'trend') drawTrendChart() })
})

watch(section, (v) => { if (v === 'trend') nextTick(() => drawTrendChart()) })
</script>
