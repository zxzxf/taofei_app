<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="brand-logo">淘</div>
      <div class="brand-name">淘飞AI</div>
    </div>

    <nav class="nav-section">
      <button class="nav-item" :class="{ active: route.name === 'chat' }" @click="router.push('/chat')">
        <span class="icon">💬</span> 会话中心 <span class="nav-badge">新</span>
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

const workspaces = ref([])
const currentWsId = ref(null)
const fullAccess = ref(false)
const apiStatus = ref('')
const apiText = ref('检测服务状态…')
const isLight = ref(false)
const toastVisible = ref(false)
const toastMsg = ref('')

const currentWsName = computed(() => {
  const ws = workspaces.value.find(w => w.id === currentWsId.value)
  return ws ? ws.name : '选择工作空间'
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
  // 优先尝试本地备份，避免首次打开空白
  try {
    const saved = JSON.parse(localStorage.getItem('workspaces') || '{}')
    if (saved.workspaces && saved.workspaces.length) {
      workspaces.value = saved.workspaces
      currentWsId.value = saved.current_id || null
      fullAccess.value = saved.full_access || false
    }
  } catch (e) { /* ignore */ }

  try {
    const res = await fetch('/api/workspaces')
    if (res.ok) {
      const data = await res.json()
      workspaces.value = data.workspaces || []
      currentWsId.value = data.current_id
    }
    if (!workspaces.value.length) {
      // 后端无工作空间 → 用默认路径创建一个
      try {
        const defaultPath = 'E:\\20260814\\taofei_app'
        const res2 = await fetch('/api/workspaces', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: 'taofei_app', path: defaultPath }),
        })
        if (res2.ok) {
          const d2 = await res2.json()
          workspaces.value = [d2.workspace]
          currentWsId.value = d2.current_id || d2.workspace?.id
        }
      } catch (e) { /* ignore */ }
    }
  } catch (e) {
    console.error('加载工作空间失败', e)
  }
}

function saveWorkspaces() {
  // 保留 localStorage 作为前端离线备份，但以后端 API 为真相源
  // handle 等不可序列化对象需要剔除
  try {
    localStorage.setItem('workspaces', JSON.stringify({
      workspaces: workspaces.value.map(w => ({ id: w.id, name: w.name, path: w.path })),
      current_id: currentWsId.value,
      full_access: fullAccess.value,
    }))
  } catch (e) { /* ignore */ }
}

function emitWorkspaceChanged() {
  try {
    window.dispatchEvent(new CustomEvent('taofei-workspace-changed', {
      detail: { current_id: currentWsId.value, workspaces: workspaces.value },
    }))
  } catch (e) { /* ignore */ }
}

async function addWorkspace(ws) {
  try {
    const res = await fetch('/api/workspaces', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(ws),
    })
    if (res.ok) {
      const data = await res.json()
      workspaces.value = data.workspaces || workspaces.value
      currentWsId.value = data.current_id
    } else {
      // 后端不可用：本地追加
      const id = 'ws_' + Date.now()
      workspaces.value.push({ id, ...ws })
      currentWsId.value = id
    }
  } catch (e) {
    const id = 'ws_' + Date.now()
    workspaces.value.push({ id, ...ws })
    currentWsId.value = id
  }
  fullAccess.value = true
  saveWorkspaces()
  emitWorkspaceChanged()
  showToast('工作空间已添加')
}

async function openLocalFolder() {
  let picked = { canceled: true }

  // 1. 桌面端：调用 Electron 原生目录选择
  if (window.desktop && window.desktop.openDirectoryPicker) {
    try {
      picked = await window.desktop.openDirectoryPicker({
        title: '打开本地目录 · 选择本地文件夹',
        buttonLabel: '选择文件夹',
      })
    } catch (e) {
      console.error('桌面端目录选择失败', e)
    }
    if (picked.canceled) return
    const name = picked.path.split(/[\\/]/).pop() || '本地目录'
    await addWorkspace({ name, path: picked.path })
    return
  }

  // 2. 浏览器端：File System Access API
  if (window.showDirectoryPicker) {
    try {
      const handle = await window.showDirectoryPicker()
      const name = handle.name || '本地目录'
      await addWorkspace({ name, path: '', handle })
      // 尝试请求完全访问权限
      try {
        if (handle.requestPermission) {
          await handle.requestPermission({ mode: 'readwrite' })
        }
      } catch (_) { /* ignore */ }
    } catch (e) {
      if (e.name !== 'AbortError') {
        console.error('浏览器目录选择失败', e)
      }
    }
    return
  }

  // 3. 兜底：input directory 选择（只能拿到相对文件列表，无绝对路径）
  const input = document.createElement('input')
  input.type = 'file'
  input.webkitdirectory = true
  input.directory = true
  input.style.display = 'none'
  document.body.appendChild(input)
  input.addEventListener('change', () => {
    if (input.files && input.files.length > 0) {
      const first = input.files[0].webkitRelativePath || input.files[0].name
      const name = first.split('/')[0] || '本地目录'
      addWorkspace({ name, path: '' })
    }
    document.body.removeChild(input)
  })
  input.addEventListener('cancel', () => {
    document.body.removeChild(input)
  })
  input.click()
}

function clearWorkspace() {
  currentWsId.value = null
  fullAccess.value = false
  saveWorkspaces()
  emitWorkspaceChanged()
  showToast('已取消工作空间')
}

async function switchWorkspace(id) {
  try {
    const res = await fetch(`/api/workspaces/${id}/switch`, { method: 'POST' })
    if (res.ok) {
      const data = await res.json()
      currentWsId.value = data.current_id || id
    } else {
      // 回退：本地切换
      currentWsId.value = id
    }
  } catch (e) {
    currentWsId.value = id
  }
  saveWorkspaces()
  showToast('工作空间已切换')
  emitWorkspaceChanged()
}

async function deleteWorkspace(id) {
  if (!confirm('确定删除该工作空间？')) return
  try {
    const res = await fetch(`/api/workspaces/${id}`, { method: 'DELETE' })
    if (res.ok) {
      const data = await res.json()
      workspaces.value = workspaces.value.filter(w => w.id !== id)
      currentWsId.value = data.current_id || workspaces.value[0]?.id || null
    } else {
      workspaces.value = workspaces.value.filter(w => w.id !== id)
      if (currentWsId.value === id) currentWsId.value = workspaces.value[0]?.id || null
    }
  } catch (e) {
    workspaces.value = workspaces.value.filter(w => w.id !== id)
    if (currentWsId.value === id) currentWsId.value = workspaces.value[0]?.id || null
  }
  saveWorkspaces()
  showToast('已删除')
  emitWorkspaceChanged()
}

function checkApiStatus() {
  apiStatus.value = 'ok'
  apiText.value = '服务正常'
}

function onOpenLocalFolderRequest() {
  openLocalFolder()
}

function onDeleteWorkspaceRequest(evt) {
  const id = evt?.detail?.id
  if (id) deleteWorkspace(id)
}

onMounted(async () => {
  const savedTheme = localStorage.getItem('theme')
  if (savedTheme === 'light') {
    isLight.value = true
    document.body.classList.add('light-theme')
  }
  window.addEventListener('taofei-open-local-folder', onOpenLocalFolderRequest)
  window.addEventListener('taofei-delete-workspace', onDeleteWorkspaceRequest)
  await loadWorkspaces()
  saveWorkspaces()
  emitWorkspaceChanged()
  checkApiStatus()
})
</script>
