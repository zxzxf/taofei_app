<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="brand-logo">淘</div>
      <div class="brand-name">淘飞AI</div>
    </div>

    <div class="workspace-section">
      <div class="workspace-selector" :class="{ open: wsOpen }" @click="wsOpen = !wsOpen">
        <div class="workspace-selector-main">
          <div class="workspace-icon">📁</div>
          <div class="workspace-info">
            <div class="workspace-name">{{ currentWsName }}</div>
          </div>
        </div>
        <span class="workspace-arrow">▼</span>
      </div>
      <div class="workspace-dropdown" :class="{ open: wsOpen }">
        <div class="ws-search">
          <span>🔍</span>
          <input v-model="wsSearch" type="text" placeholder="搜索工作空间">
        </div>
        <div class="ws-dropdown-list">
          <div
            v-for="ws in filteredWorkspaces"
            :key="ws.id"
            class="ws-dropdown-item"
            :class="{ selected: ws.id === currentWsId }"
            @click="switchWorkspace(ws.id)"
          >
            <div class="workspace-icon">📁</div>
            <div class="ws-item-info">
              <div class="ws-item-name">{{ ws.name }}</div>
            </div>
            <div class="ws-item-actions">
              <button @click.stop="deleteWorkspace(ws.id)">删除</button>
            </div>
          </div>
          <div v-if="!workspaces.length" class="ws-empty">暂无工作空间</div>
        </div>
        <div class="ws-actions">
          <button @click="showNewWsForm = true">+ 新建</button>
          <button @click="openLocalFolder">打开本地</button>
        </div>
      </div>
    </div>

    <nav class="nav-section">
      <button class="nav-item" :class="{ active: route.name === 'chat' }" @click="router.push('/chat')">
        <span class="icon">💬</span> 对话中心 <span class="nav-badge">新</span>
      </button>
      <button class="nav-item" :class="{ active: route.name === 'dashboard' }" @click="router.push('/dashboard')">
        <span class="icon">🏠</span> 工作台
      </button>
      <button class="nav-item" :class="{ active: route.name === 'agents' }" @click="router.push('/agents')">
        <span class="icon">🤖</span> 智能体中心
      </button>
      <button class="nav-item" :class="{ active: route.name === 'task' }" @click="router.push('/task')">
        <span class="icon">⚡</span> 任务编排
      </button>
      <button class="nav-item" :class="{ active: route.name === 'knowledge' }" @click="router.push('/knowledge')">
        <span class="icon">📚</span> 知识库
      </button>
      <button class="nav-item" :class="{ active: route.name === 'analysis' }" @click="router.push('/analysis')">
        <span class="icon">📊</span> 数据分析
      </button>
      <button class="nav-item" :class="{ active: route.name === 'integration' }" @click="router.push('/integration')">
        <span class="icon">🔌</span> 集成管理
      </button>
      <button class="nav-item" :class="{ active: route.name === 'settings' }" @click="router.push('/settings')">
        <span class="icon">⚙️</span> 系统设置
      </button>
    </nav>

    <div class="nav-bottom">
      <div class="api-status">
        <span class="dot" :class="apiStatus"></span>
        <span>{{ apiText }}</span>
      </div>
    </div>
  </aside>

  <main class="main">
    <div class="main-header">
      <div class="header-left">
        <span class="page-title">{{ pageTitle }}</span>
        <div class="header-tags">
          <span v-for="tag in pageTags" :key="tag" class="header-tag">{{ tag }}</span>
        </div>
      </div>
      <div class="header-right">
        <div class="model-chip" @click="router.push('/settings')">
          <div class="avatar">D</div>
          <div class="avatar-meta">
            <span class="avatar-name">DeepSeek</span>
            <span class="avatar-sub">deepseek-chat</span>
          </div>
        </div>
        <button class="theme-toggle" @click="toggleTheme">{{ isLight ? '☀️' : '🌙' }}</button>
        <button class="header-btn" @click="router.push('/task')">+ 新建任务</button>
      </div>
    </div>

    <div class="content">
      <router-view />
    </div>
  </main>

  <div class="toast" :class="{ show: toastVisible }">{{ toastMsg }}</div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useRouter as useAppRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const wsOpen = ref(false)
const wsSearch = ref('')
const showNewWsForm = ref(false)
const workspaces = ref([])
const currentWsId = ref(null)
const apiStatus = ref('')
const apiText = ref('检测服务状态…')
const isLight = ref(false)
const toastVisible = ref(false)
const toastMsg = ref('')

const currentWsName = computed(() => {
  const ws = workspaces.value.find(w => w.id === currentWsId.value)
  return ws ? ws.name : '选择工作空间'
})

const filteredWorkspaces = computed(() => {
  const term = wsSearch.value.trim().toLowerCase()
  if (!term) return workspaces.value
  return workspaces.value.filter(w =>
    w.name.toLowerCase().includes(term) || (w.path || '').toLowerCase().includes(term)
  )
})

const pageTitle = computed(() => route.meta.title || '淘飞AI')
const pageTags = computed(() => route.meta.tags || [])

function toggleTheme() {
  isLight.value = !isLight.value
  document.body.classList.toggle('light-theme', isLight.value)
  localStorage.setItem('theme', isLight.value ? 'light' : 'dark')
}

function showToast(msg) {
  toastMsg.value = msg
  toastVisible.value = true
  setTimeout(() => toastVisible.value = false, 2500)
}

async function loadWorkspaces() {
  try {
    const saved = localStorage.getItem('workspaces')
    if (saved) {
      const data = JSON.parse(saved)
      workspaces.value = data.workspaces || []
      currentWsId.value = data.current_id
    } else {
      workspaces.value = [{ id: 'default', name: 'taofei_app', path: 'd:/workspaces/taofei_plateform/taofei_app' }]
      currentWsId.value = 'default'
      saveWorkspaces()
    }
  } catch (e) {
    console.error('加载工作空间失败', e)
  }
}

function saveWorkspaces() {
  localStorage.setItem('workspaces', JSON.stringify({
    workspaces: workspaces.value,
    current_id: currentWsId.value
  }))
}

async function switchWorkspace(id) {
  currentWsId.value = id
  saveWorkspaces()
  wsOpen.value = false
  showToast('工作空间已切换')
}

async function deleteWorkspace(id) {
  if (!confirm('确定删除该工作空间？')) return
  workspaces.value = workspaces.value.filter(w => w.id !== id)
  if (currentWsId.value === id) currentWsId.value = workspaces.value[0]?.id || null
  saveWorkspaces()
  showToast('已删除')
}

async function openLocalFolder() {
  const path = prompt('请输入本地文件夹路径：')
  if (!path) return
  const name = path.split(/[\\/]/).pop()
  const id = 'ws-' + Date.now()
  workspaces.value.push({ id, name, path })
  currentWsId.value = id
  saveWorkspaces()
  showToast('已添加工作空间')
}

function checkApiStatus() {
  apiStatus.value = 'ok'
  apiText.value = '服务正常'
}

onMounted(() => {
  const savedTheme = localStorage.getItem('theme')
  if (savedTheme === 'light') {
    isLight.value = true
    document.body.classList.add('light-theme')
  }
  loadWorkspaces()
  checkApiStatus()
})
</script>
