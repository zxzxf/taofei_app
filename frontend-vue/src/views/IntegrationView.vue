<template>
  <div class="integration-layout">
    <div class="integration-nav">
      <button class="integration-nav-item" :class="{ active: section === 'weather' }" @click="section = 'weather'"><span>🌤️</span> 天气查询</button>
      <button class="integration-nav-item" :class="{ active: section === 'skills' }" @click="section = 'skills'"><span>🛠️</span> 技能管理</button>
      <button class="integration-nav-item" :class="{ active: section === 'list' }" @click="section = 'list'"><span>🔌</span> 集成列表</button>
    </div>
    <div class="integration-content">
      <div v-show="section === 'weather'" class="integration-panel active">
        <div class="glass-card" style="margin-top:20px;">
          <div class="card-head">
            <div class="card-title">🌤️ 天气查询（Open-Meteo · 已接入）</div>
            <div class="card-sub">免费 · 无需 API Key · 支持全球城市</div>
          </div>
          <div class="weather-query">
            <input v-model="city" type="text" placeholder="输入城市名，如：北京、上海、深圳" @keydown.enter="queryWeather">
            <button class="btn-primary" @click="queryWeather">查询天气</button>
          </div>
          <div v-if="weather" class="weather-result">
            <div class="weather-now">
              <div class="weather-now-icon">{{ weather.icon }}</div>
              <div>
                <div class="weather-now-temp">{{ weather.temp }}<small>°C</small></div>
                <div class="weather-now-cond" style="font-size:14px;color:var(--text-secondary);margin-top:2px;">{{ weather.condition }}</div>
              </div>
            </div>
            <div class="weather-details">
              <div class="weather-detail"><div class="k">湿度</div><div class="v">{{ weather.humidity }}%</div></div>
              <div class="weather-detail"><div class="k">风速</div><div class="v">{{ weather.wind }} km/h</div></div>
            </div>
          </div>
        </div>
      </div>
      <div v-show="section === 'skills'" class="integration-panel active">
        <div class="glass-card">
          <div class="card-head">
            <div>
              <div class="card-title">🛠️ 技能管理</div>
              <div class="card-sub" style="margin-top:4px">会话中心可用「@技能名」调用</div>
            </div>
            <div style="display:flex;gap:8px;">
              <button class="btn-ghost" @click="showUploadModal = true">📤 上传技能</button>
              <button class="btn-ghost" @click="showInstallForm = !showInstallForm">🔗 自定义安装</button>
              <button class="btn-primary" @click="showSkillForm = !showSkillForm">+ 新建技能</button>
            </div>
          </div>

          <div v-if="showUploadModal" class="skill-upload-overlay" @click.self="showUploadModal = false">
            <div class="skill-upload-modal">
              <div class="skill-upload-header">
                <span class="skill-upload-title">上传技能</span>
                <button class="skill-upload-close" @click="showUploadModal = false">✕</button>
              </div>
              <div
                class="skill-upload-zone"
                :class="{ active: uploadDragOver, hasFile: uploadedFile }"
                @click="$refs.fileInput.click()"
                @dragover.prevent="uploadDragOver = true"
                @dragleave.prevent="uploadDragOver = false"
                @drop.prevent="handleFileDrop"
              >
                <div v-if="!uploadedFile" class="skill-upload-placeholder">
                  <div class="skill-upload-icon">📄</div>
                  <div class="skill-upload-hint">SKILL.md</div>
                  <div class="skill-upload-sub">点击或拖拽文件到此处上传</div>
                </div>
                <div v-else class="skill-upload-file">
                  <div class="skill-upload-file-icon">📦</div>
                  <div class="skill-upload-file-info">
                    <div class="skill-upload-file-name">{{ uploadedFile.name }}</div>
                    <div class="skill-upload-file-size">{{ formatFileSize(uploadedFile.size) }}</div>
                  </div>
                </div>
              </div>
              <input ref="fileInput" type="file" accept=".skill,.zip,.md" style="display:none" @change="handleFileSelect">
              <div class="skill-upload-tips">
                <div class="skill-upload-tip">• 包含根级 SKILL.md 文件的 zip 或 .skill 文件</div>
                <div class="skill-upload-tip">• SKILL.md 包含以 YAML 格式编写的技能名称和描述</div>
              </div>
              <div v-if="uploadError" class="skill-upload-error">{{ uploadError }}</div>
              <div class="skill-upload-footer">
                <button class="btn-ghost" @click="closeUploadModal">取消</button>
                <button class="btn-primary" @click="confirmUpload" :disabled="!uploadedFile || uploading">
                  {{ uploading ? '上传中…' : '确认' }}
                </button>
              </div>
            </div>
          </div>

          <div v-if="showInstallForm" class="skill-install-form">
            <div class="install-form-title">🔗 自定义安装技能</div>
            <div class="install-form-sub">从 GitHub 仓库、npm 包或 URL 安装技能</div>
            <div class="field" style="margin-bottom:12px;">
              <label style="font-size:12.5px;font-weight:600;margin-bottom:6px;display:block;">安装来源</label>
              <input v-model="installForm.source" type="text" placeholder="如：github.com/anthropics/claude-code 或 npm:@anthropic/skill-code" style="width:100%;padding:9px 12px;border:1px solid var(--border-strong);border-radius:8px;background:var(--bg-soft);color:var(--text);">
            </div>
            <div class="field" style="margin-bottom:12px;">
              <label style="font-size:12.5px;font-weight:600;margin-bottom:6px;display:block;">技能名称（可选）</label>
              <input v-model="installForm.name" type="text" placeholder="留空则自动从来源获取" style="width:100%;padding:9px 12px;border:1px solid var(--border-strong);border-radius:8px;background:var(--bg-soft);color:var(--text);">
            </div>
            <div style="display:flex;gap:8px;">
              <button class="btn-ghost" @click="showInstallForm = false">取消</button>
              <button class="btn-primary" @click="installSkill" :disabled="installing">
                {{ installing ? '安装中…' : '安装技能' }}
              </button>
            </div>
            <div v-if="installResult" class="install-result" :class="installResult.type">
              {{ installResult.msg }}
            </div>
          </div>

          <div class="skill-templates">
            <div class="skill-templates-title" @click="templatesCollapsed = !templatesCollapsed">
              📦 技能模板 · 快速添加
              <span class="skill-templates-toggle">{{ templatesCollapsed ? '▸ 展开' : '▾ 收起' }}</span>
            </div>
            <div v-show="!templatesCollapsed" class="skill-template-grid">
              <div v-for="tpl in skillTemplates" :key="tpl.id" class="skill-template-card" :class="{ added: tpl.added }" :title="tpl.desc" @click="addTemplateSkill(tpl)">
                <span class="skill-template-icon" :style="{ background: tpl.color }">{{ tpl.icon }}</span>
                <span class="skill-template-name">{{ tpl.name }}</span>
                <span class="skill-template-add">{{ tpl.added ? '✓' : '+' }}</span>
              </div>
            </div>
          </div>

          <div v-if="showSkillForm" style="background:var(--bg-soft);border:1px solid var(--border);border-radius:var(--radius-sm);padding:16px;margin-bottom:16px;">
            <div class="field" style="margin-bottom:12px;">
              <label style="font-size:12.5px;font-weight:600;margin-bottom:6px;display:block;">技能名称</label>
              <input v-model="skillForm.name" type="text" placeholder="如：天气查询" style="width:100%;padding:9px 12px;border:1px solid var(--border-strong);border-radius:8px;background:var(--bg-soft);color:var(--text);">
            </div>
            <div class="field" style="margin-bottom:12px;">
              <label style="font-size:12.5px;font-weight:600;margin-bottom:6px;display:block;">API URL</label>
              <input v-model="skillForm.url" type="text" placeholder="https://api.example.com/data" style="width:100%;padding:9px 12px;border:1px solid var(--border-strong);border-radius:8px;background:var(--bg-soft);color:var(--text);">
            </div>
            <div class="field" style="margin-bottom:12px;">
              <label style="font-size:12.5px;font-weight:600;margin-bottom:6px;display:block;">技能描述</label>
              <input v-model="skillForm.desc" type="text" placeholder="简要描述技能功能" style="width:100%;padding:9px 12px;border:1px solid var(--border-strong);border-radius:8px;background:var(--bg-soft);color:var(--text);">
            </div>
            <button class="btn-primary" @click="addSkill">保存技能</button>
          </div>

          <div class="skill-list-header">
            已安装技能 <span class="skill-count">{{ filteredSkills.length }}</span>
            <span class="skill-total-hint">/ 共 {{ skills.length }} 个</span>
          </div>

          <div class="skill-toolbar">
            <input v-model="skillSearch" type="text" class="skill-search-input" placeholder="搜索技能名称或描述…">
            <div class="skill-filter-group">
              <button class="skill-filter-btn" :class="{ active: skillFilter === 'all' }" @click="skillFilter = 'all'">全部</button>
              <button class="skill-filter-btn" :class="{ active: skillFilter === 'enabled' }" @click="skillFilter = 'enabled'">已启用</button>
              <button class="skill-filter-btn" :class="{ active: skillFilter === 'disabled' }" @click="skillFilter = 'disabled'">已停用</button>
            </div>
          </div>

          <div v-if="skillLoading" class="skill-loading">
            <span class="skill-loading-spinner"></span> 加载中…
          </div>

          <div v-else-if="paginatedSkills.length">
            <div class="skill-row" v-for="s in paginatedSkills" :key="s.id">
              <div class="skill-icon" :style="{ background: s.color || 'rgba(139, 92, 246, 0.12)' }">{{ s.icon || '🛠️' }}</div>
              <div class="skill-info">
                <div class="skill-name">
                  {{ s.name }}
                  <span class="skill-tag" :class="s.enabled ? 'on' : 'off'">{{ s.enabled ? '已启用' : '已停用' }}</span>
                  <span v-if="s.type && s.type !== 'api'" class="skill-type-badge" :class="s.type">{{ skillTypeLabel(s.type) }}</span>
                </div>
                <div class="skill-desc">{{ s.desc }}</div>
                <div class="skill-url">{{ s.url }}</div>
              </div>
              <div class="skill-ops">
                <button class="skill-op" @click="s.enabled = !s.enabled">{{ s.enabled ? '停用' : '启用' }}</button>
                <button class="skill-op danger" @click="deleteSkill(s.id)">删除</button>
              </div>
            </div>
          </div>
          <div v-else class="skill-empty">
            {{ skillSearch || skillFilter !== 'all' ? '没有匹配的技能' : '暂无技能，点击「新建技能」或从下方模板添加' }}
          </div>

          <div v-if="filteredSkills.length > 0" class="skill-pagination">
            <button class="page-btn" :disabled="currentPage === 1" @click="goToPage(currentPage - 1)">‹</button>
            <button
              v-for="p in pageNumbers"
              :key="p"
              class="page-num"
              :class="{ active: p === currentPage, ellipsis: p === '...' }"
              @click="goToPage(p)"
            >{{ p }}</button>
            <button class="page-btn" :disabled="currentPage === totalPages" @click="goToPage(currentPage + 1)">›</button>
            <span class="page-info">{{ currentPage }}/{{ totalPages }} 页 · {{ filteredSkills.length }} 条</span>
          </div>
        </div>
      </div>
      <div v-show="section === 'list'" class="integration-panel active">
        <div class="glass-card" style="margin-bottom:20px">
          <div class="card-head" style="margin-bottom:6px">
            <div>
              <div class="card-title">🔌 集成列表</div>
              <div class="card-sub" style="margin-top:4px">统一接入外部系统与 API</div>
            </div>
          </div>
        </div>
        <div class="integration-grid">
          <div class="integration-card" v-for="item in integrations" :key="item.name" :class="{ planned: item.status === 'planned', clickable: item.type === 'github' }" @click="item.type === 'github' && openGitHubModal()">
            <div class="integration-card-head">
              <div class="integration-icon">{{ item.icon }}</div>
              <div>
                <div class="integration-name">{{ item.name }}</div>
                <div class="integration-cat">{{ item.category }}</div>
              </div>
              <div class="integration-status" :class="item.status">{{ item.status === 'connected' ? '已接入' : '规划中' }}</div>
            </div>
            <div class="integration-desc">{{ item.desc }}</div>
            <div v-if="item.type === 'github'" class="integration-action">点击提交代码 →</div>
          </div>
        </div>

        <!-- GitHub 提交弹窗 -->
        <div v-if="showGitHubModal" class="skill-upload-overlay" @click.self="showGitHubModal = false">
          <div class="skill-upload-modal" style="max-width:520px">
            <div class="skill-upload-header">
              <span class="skill-upload-title">🐙 GitHub 代码提交</span>
              <button class="skill-upload-close" @click="showGitHubModal = false">✕</button>
            </div>
            <div class="skill-install-form" style="padding:16px 0 0;margin:0;border:none">
              <div class="field" style="margin-bottom:12px;">
                <label style="font-size:12.5px;font-weight:600;margin-bottom:6px;display:block;">仓库地址</label>
                <input v-model="githubConfig.repo" type="text" placeholder="https://github.com/owner/repo.git" style="width:100%;padding:9px 12px;border:1px solid var(--border-strong);border-radius:8px;background:var(--bg-soft);color:var(--text);">
              </div>
              <div class="field" style="margin-bottom:12px;">
                <label style="font-size:12.5px;font-weight:600;margin-bottom:6px;display:block;">目标分支</label>
                <input v-model="githubConfig.branch" type="text" placeholder="main" style="width:100%;padding:9px 12px;border:1px solid var(--border-strong);border-radius:8px;background:var(--bg-soft);color:var(--text);">
              </div>
              <div class="field" style="margin-bottom:12px;">
                <label style="font-size:12.5px;font-weight:600;margin-bottom:6px;display:block;">提交信息</label>
                <textarea v-model="githubConfig.message" rows="3" placeholder="描述本次提交内容" style="width:100%;padding:9px 12px;border:1px solid var(--border-strong);border-radius:8px;background:var(--bg-soft);color:var(--text);resize:vertical;"></textarea>
              </div>
              <div style="display:flex;gap:8px;">
                <button class="btn-ghost" @click="showGitHubModal = false">取消</button>
                <button class="btn-primary" @click="commitToGitHub" :disabled="githubLoading || !githubConfig.message.trim()">
                  {{ githubLoading ? '提交中…' : '提交并推送' }}
                </button>
              </div>
              <div v-if="githubResult" class="install-result" :class="githubResult.type" style="margin-top:12px">
                {{ githubResult.msg }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'

const section = ref('weather')
const city = ref('')
const weather = ref(null)
const showSkillForm = ref(false)
const showInstallForm = ref(false)
const skills = ref([])
const skillForm = ref({ name: '', url: '', desc: '' })
const installForm = ref({ source: '', name: '' })
const installing = ref(false)
const installResult = ref(null)
const skillSearch = ref('')
const skillFilter = ref('all')
const currentPage = ref(1)
const pageSize = ref(3)
const skillLoading = ref(false)
const templatesCollapsed = ref(false)
const showUploadModal = ref(false)
const uploadDragOver = ref(false)
const uploadedFile = ref(null)
const uploadError = ref('')
const uploading = ref(false)

const skillTemplates = ref([
  {
    id: 'tpl-claude-code',
    icon: '🤖',
    name: 'Claude Code',
    desc: 'Anthropic 编程助手，支持代码生成、重构、调试、审查',
    url: 'claude-code://cli',
    type: 'cli',
    color: 'rgba(217, 119, 87, 0.15)',
    added: false
  },
  {
    id: 'tpl-cursor',
    icon: '📝',
    name: 'Cursor AI',
    desc: 'AI 代码编辑器，智能补全与多文件编辑',
    url: 'cursor://ai',
    type: 'cli',
    color: 'rgba(59, 130, 246, 0.15)',
    added: false
  },
  {
    id: 'tpl-github-copilot',
    icon: '🐙',
    name: 'GitHub Copilot',
    desc: 'GitHub AI 编程助手，支持多种语言代码补全',
    url: 'copilot://github',
    type: 'cli',
    color: 'rgba(168, 85, 247, 0.15)',
    added: false
  },
  {
    id: 'tpl-web-search',
    icon: '🔍',
    name: '网页搜索',
    desc: '互联网信息搜索，返回相关网页摘要与链接',
    url: 'https://api.search.example.com/v1/search',
    type: 'api',
    color: 'rgba(16, 185, 129, 0.15)',
    added: false
  },
  {
    id: 'tpl-image-gen',
    icon: '🎨',
    name: '图片生成',
    desc: '根据文字描述生成高质量图片，支持多种风格',
    url: 'https://api.example.com/v1/image/generate',
    type: 'api',
    color: 'rgba(236, 72, 153, 0.15)',
    added: false
  },
  {
    id: 'tpl-pdf-reader',
    icon: '📄',
    name: 'PDF 解析',
    desc: '解析 PDF 文档，提取文本、表格与图片内容',
    url: 'https://api.example.com/v1/pdf/parse',
    type: 'api',
    color: 'rgba(245, 158, 11, 0.15)',
    added: false
  },
])

const defaultSkills = [
  { id: 'skill-1', name: '天气查询', url: 'https://api.open-meteo.com/v1/forecast', desc: '查询全球城市天气信息，支持实时温度、湿度、风速等', enabled: true, type: 'api', icon: '🌤️', color: 'rgba(59, 130, 246, 0.12)' },
  { id: 'skill-2', name: '网页搜索', url: 'https://api.search.example.com/v1/search', desc: '互联网信息搜索，返回相关网页摘要与链接', enabled: true, type: 'api', icon: '🔍', color: 'rgba(16, 185, 129, 0.12)' },
  { id: 'skill-3', name: '文档摘要', url: 'https://api.example.com/v1/summarize', desc: '自动提取长文档关键信息，生成结构化摘要', enabled: true, type: 'api', icon: '📝', color: 'rgba(139, 92, 246, 0.12)' },
  { id: 'skill-4', name: '代码执行', url: 'https://api.example.com/v1/execute', desc: '安全沙箱中执行 Python/JS 代码并返回结果', enabled: false, type: 'api', icon: '⚡', color: 'rgba(245, 158, 11, 0.12)' },
  { id: 'skill-5', name: '图片生成', url: 'https://api.example.com/v1/image/generate', desc: '根据文字描述生成高质量图片，支持多种风格', enabled: true, type: 'api', icon: '🎨', color: 'rgba(236, 72, 153, 0.12)' },
  { id: 'skill-6', name: '翻译服务', url: 'https://api.example.com/v1/translate', desc: '多语言翻译，支持中英日韩法德等 30+ 语言', enabled: true, type: 'api', icon: '🌐', color: 'rgba(59, 130, 246, 0.12)' },
  { id: 'skill-7', name: 'OCR 识别', url: 'https://api.example.com/v1/ocr', desc: '图片文字识别，支持中文、英文、数字及混排', enabled: true, type: 'api', icon: '📷', color: 'rgba(139, 92, 246, 0.12)' },
  { id: 'skill-8', name: '语音合成', url: 'https://api.example.com/v1/tts', desc: '文本转语音，支持多音色与情感表达', enabled: false, type: 'api', icon: '🔊', color: 'rgba(236, 72, 153, 0.12)' },
  { id: 'skill-9', name: '数据分析', url: 'https://api.example.com/v1/analyze', desc: '结构化数据分析与可视化图表生成', enabled: true, type: 'api', icon: '📊', color: 'rgba(16, 185, 129, 0.12)' },
  { id: 'skill-10', name: '邮件发送', url: 'https://api.example.com/v1/mail', desc: 'SMTP 邮件发送，支持模板与附件', enabled: true, type: 'api', icon: '📧', color: 'rgba(245, 158, 11, 0.12)' },
  { id: 'skill-11', name: '日程管理', url: 'https://api.example.com/v1/calendar', desc: '创建和管理日程，支持提醒与重复规则', enabled: true, type: 'api', icon: '📅', color: 'rgba(59, 130, 246, 0.12)' },
  { id: 'skill-12', name: '数据库查询', url: 'https://api.example.com/v1/query', desc: '自然语言转 SQL，安全查询数据库', enabled: false, type: 'api', icon: '🗄️', color: 'rgba(139, 92, 246, 0.12)' },
]

const integrations = ref([
  { icon: '🌤️', name: 'Open-Meteo', category: '天气服务', status: 'connected', desc: '免费天气数据 API，支持全球城市查询' },
  { icon: '🐙', name: 'GitHub', category: '代码托管', status: 'connected', desc: '代码提交、推送与仓库管理集成', type: 'github' },
  { icon: '💬', name: '企业微信', category: '即时通讯', status: 'planned', desc: '企业微信消息推送与群聊管理' },
  { icon: '钉钉', name: '钉钉开放平台', category: '即时通讯', status: 'planned', desc: '钉钉机器人消息与审批集成' },
  { icon: '📧', name: '邮件服务', category: '通知服务', status: 'planned', desc: 'SMTP 邮件发送与通知' },
  { icon: '🔗', name: 'API 网关', category: '开发工具', status: 'planned', desc: '统一 API 管理与流量控制' },
  { icon: '🗄️', name: '向量数据库', category: '数据存储', status: 'planned', desc: '知识库向量存储与相似度检索' },
])

const showGitHubModal = ref(false)
const githubConfig = ref({ repo: 'https://github.com/zxzxf/taofei_app.git', branch: 'main', message: '' })
const githubLoading = ref(false)
const githubResult = ref(null)

const filteredSkills = computed(() => {
  let result = skills.value
  if (skillFilter.value === 'enabled') result = result.filter(s => s.enabled)
  else if (skillFilter.value === 'disabled') result = result.filter(s => !s.enabled)
  const term = skillSearch.value.trim().toLowerCase()
  if (term) result = result.filter(s => s.name.toLowerCase().includes(term) || s.desc.toLowerCase().includes(term))
  return result
})

const totalPages = computed(() => Math.max(1, Math.ceil(filteredSkills.value.length / pageSize.value)))

const paginatedSkills = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredSkills.value.slice(start, start + pageSize.value)
})

const pageNumbers = computed(() => {
  const pages = []
  const total = totalPages.value
  const cur = currentPage.value
  if (total <= 7) {
    for (let i = 1; i <= total; i++) pages.push(i)
  } else {
    pages.push(1)
    if (cur > 3) pages.push('...')
    const start = Math.max(2, cur - 1)
    const end = Math.min(total - 1, cur + 1)
    for (let i = start; i <= end; i++) pages.push(i)
    if (cur < total - 2) pages.push('...')
    pages.push(total)
  }
  return pages
})

watch([skillSearch, skillFilter], () => { currentPage.value = 1 })

function goToPage(page) {
  if (page === '...' || page < 1 || page > totalPages.value) return
  currentPage.value = page
}

function skillTypeLabel(type) {
  const labels = { cli: 'CLI', api: 'API', installed: '已安装' }
  return labels[type] || type
}

async function queryWeather() {
  if (!city.value.trim()) return
  try {
    const cityName = city.value.trim()
    const geoRes = await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(cityName)}&count=1&language=zh`)
    const geoData = await geoRes.json()
    if (!geoData.results || !geoData.results.length) {
      alert('未找到城市：' + cityName)
      return
    }
    const loc = geoData.results[0]
    const weatherRes = await fetch(`https://api.open-meteo.com/v1/forecast?latitude=${loc.latitude}&longitude=${loc.longitude}&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m`)
    const w = await weatherRes.json()
    const cw = w.current
    const codeMap = { 0: '晴', 1: '晴', 2: '多云', 3: '阴', 45: '雾', 48: '雾', 51: '小雨', 53: '小雨', 55: '中雨', 61: '雨', 63: '雨', 65: '大雨', 71: '雪', 73: '雪', 75: '大雪', 77: '雪', 80: '阵雨', 81: '阵雨', 82: '暴雨', 95: '雷雨', 96: '雷雨', 99: '雷雨' }
    const cond = codeMap[cw.weather_code] || '未知'
    weather.value = {
      temp: Math.round(cw.temperature_2m),
      condition: cond,
      icon: { '晴': '☀️', '多云': '⛅', '阴': '☁️', '雾': '🌫️', '小雨': '🌦️', '中雨': '🌧️', '大雨': '🌧️', '雨': '🌧️', '雪': '🌨️', '大雪': '❄️', '阵雨': '🌦️', '暴雨': '⛈️', '雷雨': '⛈️' }[cond] || '🌡️',
      humidity: cw.relative_humidity_2m,
      wind: Math.round(cw.wind_speed_10m),
      city: loc.name + (loc.admin1 ? ' · ' + loc.admin1 : '')
    }
  } catch (e) {
    alert('查询失败：' + e.message)
  }
}

async function loadSkills() {
  skillLoading.value = true
  await new Promise(r => setTimeout(r, 300))
  try {
    const saved = localStorage.getItem('skills')
    if (saved) {
      skills.value = JSON.parse(saved)
    } else {
      skills.value = [...defaultSkills]
      saveSkills()
    }
  } catch {
    skills.value = [...defaultSkills]
  }
  checkTemplateStatus()
  skillLoading.value = false
}

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function handleFileDrop(e) {
  uploadDragOver.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file) setUploadedFile(file)
}

function handleFileSelect(e) {
  const file = e.target?.files?.[0]
  if (file) setUploadedFile(file)
}

function setUploadedFile(file) {
  uploadError.value = ''
  const validExts = ['.skill', '.zip', '.md']
  const ext = '.' + file.name.split('.').pop().toLowerCase()
  if (!validExts.includes(ext)) {
    uploadError.value = '仅支持 .skill、.zip 或 .md 文件'
    return
  }
  uploadedFile.value = file
}

function closeUploadModal() {
  showUploadModal.value = false
  uploadedFile.value = null
  uploadError.value = ''
  uploadDragOver.value = false
}

async function confirmUpload() {
  if (!uploadedFile.value) return
  uploading.value = true
  uploadError.value = ''

  try {
    const file = uploadedFile.value
    const ext = '.' + file.name.split('.').pop().toLowerCase()
    let parsedName = file.name.replace(/\.[^.]+$/, '')
    let parsedDesc = `从文件 ${file.name} 上传的技能`
    let parsedIcon = '📦'

    if (ext === '.md') {
      const text = await file.text()
      const yamlMatch = text.match(/^---\n([\s\S]*?)\n---/)
      if (yamlMatch) {
        const yaml = yamlMatch[1]
        const nameMatch = yaml.match(/^name:\s*(.+)/m)
        const descMatch = yaml.match(/^description:\s*(.+)/m)
        if (nameMatch) parsedName = nameMatch[1].trim().replace(/^["']|["']$/g, '')
        if (descMatch) parsedDesc = descMatch[1].trim().replace(/^["']|["']$/g, '')
      } else {
        const nameMatch = text.match(/^#\s+(.+)/m)
        if (nameMatch) parsedName = nameMatch[1].trim()
      }
    } else {
      await new Promise(r => setTimeout(r, 800))
    }

    const exists = skills.value.some(s => s.name === parsedName)
    if (exists) {
      uploadError.value = `技能「${parsedName}」已存在`
      uploading.value = false
      return
    }

    skills.value.push({
      id: 'upload-' + Date.now().toString(),
      name: parsedName,
      url: `file://${file.name}`,
      desc: parsedDesc,
      enabled: true,
      type: 'installed',
      icon: parsedIcon,
      color: 'rgba(34, 197, 94, 0.12)'
    })
    saveSkills()
    currentPage.value = totalPages.value
    closeUploadModal()
  } catch (e) {
    uploadError.value = `上传失败：${e.message}`
  } finally {
    uploading.value = false
  }
}

function addSkill() {
  if (!skillForm.value.name || !skillForm.value.url) return
  skills.value.push({
    id: Date.now().toString(),
    name: skillForm.value.name,
    url: skillForm.value.url,
    desc: skillForm.value.desc || '用户自定义技能',
    enabled: true,
    type: 'api',
    icon: '🛠️',
    color: 'rgba(139, 92, 246, 0.12)'
  })
  skillForm.value = { name: '', url: '', desc: '' }
  showSkillForm.value = false
  saveSkills()
  currentPage.value = totalPages.value
}

function addTemplateSkill(tpl) {
  if (tpl.added) return
  const exists = skills.value.some(s => s.name === tpl.name)
  if (exists) {
    tpl.added = true
    return
  }
  skills.value.push({
    id: 'tpl-' + Date.now().toString(),
    name: tpl.name,
    url: tpl.url,
    desc: tpl.desc,
    enabled: true,
    type: tpl.type,
    icon: tpl.icon,
    color: tpl.color
  })
  tpl.added = true
  saveSkills()
  currentPage.value = totalPages.value
}

async function installSkill() {
  if (!installForm.value.source.trim()) return
  installing.value = true
  installResult.value = null

  const source = installForm.value.source.trim()
  let parsedName = installForm.value.name.trim()
  let parsedUrl = source
  let parsedType = 'installed'
  let parsedIcon = '📦'

  if (source.startsWith('github.com/') || source.startsWith('https://github.com/')) {
    const cleanPath = source.replace(/^https?:\/\/github\.com\//, '').replace(/^github\.com\//, '')
    const parts = cleanPath.split('/')
    parsedName = parsedName || parts[1] || parts[0]
    parsedUrl = `https://github.com/${cleanPath}`
    parsedIcon = '🐙'
  } else if (source.startsWith('npm:')) {
    parsedName = parsedName || source.slice(4).split('/').pop()
    parsedUrl = `https://www.npmjs.com/package/${source.slice(4)}`
    parsedIcon = '📦'
  } else if (source.startsWith('http')) {
    parsedName = parsedName || source.split('/').pop() || '自定义技能'
    parsedIcon = '🔗'
  } else {
    parsedName = parsedName || source
    parsedUrl = source
    parsedIcon = '📦'
  }

  try {
    await new Promise(r => setTimeout(r, 800))

    const exists = skills.value.some(s => s.name === parsedName)
    if (exists) {
      installResult.value = { type: 'error', msg: `技能「${parsedName}」已存在` }
    } else {
      skills.value.push({
        id: 'inst-' + Date.now().toString(),
        name: parsedName,
        url: parsedUrl,
        desc: `从 ${source} 安装的技能`,
        enabled: true,
        type: parsedType,
        icon: parsedIcon,
        color: 'rgba(34, 197, 94, 0.12)'
      })
      saveSkills()
      currentPage.value = totalPages.value
      installResult.value = { type: 'success', msg: `技能「${parsedName}」安装成功！` }
      installForm.value = { source: '', name: '' }
      setTimeout(() => { installResult.value = null }, 3000)
    }
  } catch (e) {
    installResult.value = { type: 'error', msg: `安装失败：${e.message}` }
  } finally {
    installing.value = false
  }
}

function deleteSkill(id) {
  skills.value = skills.value.filter(s => s.id !== id)
  const deleted = skills.value
  skillTemplates.value.forEach(tpl => {
    if (!deleted.some(s => s.name === tpl.name)) {
      tpl.added = false
    }
  })
  saveSkills()
  if (currentPage.value > totalPages.value) currentPage.value = totalPages.value
}

function saveSkills() {
  localStorage.setItem('skills', JSON.stringify(skills.value))
}

function checkTemplateStatus() {
  skillTemplates.value.forEach(tpl => {
    tpl.added = skills.value.some(s => s.name === tpl.name)
  })
}

function openGitHubModal() {
  githubConfig.value = { repo: 'https://github.com/zxzxf/taofei_app.git', branch: 'main', message: '' }
  githubResult.value = null
  showGitHubModal.value = true
}

async function commitToGitHub() {
  if (!githubConfig.value.message.trim()) return
  githubLoading.value = true
  githubResult.value = null
  try {
    const res = await fetch('/api/git/commit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        repo: githubConfig.value.repo,
        branch: githubConfig.value.branch || 'main',
        message: githubConfig.value.message.trim()
      })
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`)
    githubResult.value = { type: 'success', msg: `提交成功：${data.commit || data.output || '已推送至 GitHub'}` }
    setTimeout(() => { showGitHubModal.value = false }, 1200)
  } catch (e) {
    githubResult.value = { type: 'error', msg: `提交失败：${e.message}` }
  } finally {
    githubLoading.value = false
  }
}

onMounted(() => {
  loadSkills()
})
</script>
