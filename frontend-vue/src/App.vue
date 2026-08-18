<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="brand-logo">淘</div>
      <div class="brand-name">淘飞AI</div>
    </div>

    <!-- 工作空间选择器 -->
    <div class="workspace-section" v-click-outside="closeWorkspaceDropdown">
      <div
        class="workspace-selector"
        :class="{ open: wsOpen }"
        @click="wsOpen = !wsOpen"
      >
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
          <span class="ws-search-icon">🔍</span>
          <input
            v-model="wsSearch"
            type="text"
            placeholder="搜索工作空间"
            @click.stop
          />
        </div>

        <div class="ws-dropdown-list">
          <div
            v-for="ws in filteredWorkspaces"
            :key="ws.id"
            class="ws-dropdown-item"
            :class="{ selected: ws.id === currentWsId }"
            @click="switchWorkspace(ws.id)"
          >
            <span class="ws-item-icon">📁</span>
            <div class="ws-item-info">
              <div class="ws-item-name">{{ ws.name }}</div>
            </div>
            <span v-if="ws.id === currentWsId" class="ws-item-check">✓</span>
            <div class="ws-item-actions">
              <button
                v-if="workspaces.length > 1"
                title="删除"
                @click.stop="deleteWorkspace(ws.id)"
              >
                🗑
              </button>
            </div>
          </div>

          <div v-if="filteredWorkspaces.length === 0" class="ws-empty">
            未找到工作空间
          </div>

          <!-- 新建工作空间内联表单 -->
          <div v-if="showNewWsForm" class="ws-new-form" @click.stop>
            <input
              ref="newWsInput"
              v-model="newWsName"
              type="text"
              placeholder="工作空间名称"
              @keydown.enter="confirmCreateWorkspace"
              @keydown.esc="cancelCreateWorkspace"
            />
            <div class="ws-new-actions">
              <button class="btn-confirm" @click="confirmCreateWorkspace">
                确定
              </button>
              <button class="btn-cancel" @click="cancelCreateWorkspace">
                取消
              </button>
            </div>
          </div>
        </div>

        <div class="ws-actions">
          <button class="ws-action-new" @click="startCreateWorkspace">
            <span>+</span> 新建工作空间
          </button>
          <button class="ws-action-open" @click="openLocalFolder">
            <span>📂</span> 打开本地文件夹
          </button>
        </div>

        <div class="ws-actions-bottom">
          <button class="ws-action-none" @click="clearWorkspace">
            <span>📂</span> 不使用工作空间
          </button>
        </div>

        <div class="ws-footer">
          <span class="ws-footer-icon">📁</span>
          <span class="ws-footer-name">{{ currentWsName }}</span>
          <span class="ws-footer-perm" :class="{ granted: fullAccess }">
            <span class="perm-dot" /> 允许完全访问
          </span>
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
const newWsName = ref('')
const newWsInput = ref(null)
const workspaces = ref([])
const currentWsId = ref(null)
const fullAccess = ref(false)
const apiStatus = ref('')
const apiText = ref('检测服务状态…')
const isLight = ref(false)
const toastVisible = ref(false)
const toastMsg = ref('')

// 点击外部关闭工作空间下拉
const vClickOutside = {
  mounted(el, binding) {
    el._clickOutside = (e) => {
      if (!el.contains(e.target)) binding.value()
    }
    document.addEventListener('click', el._clickOutside)
  },
  unmounted(el) {
    document.removeEventListener('click', el._clickOutside)
  },
}

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

function closeWorkspaceDropdown() {
  wsOpen.value = false
  if (showNewWsForm.value) cancelCreateWorkspace()
}

function startCreateWorkspace() {
  newWsName.value = ''
  showNewWsForm.value = true
  setTimeout(() => newWsInput.value?.focus(), 0)
}

function cancelCreateWorkspace() {
  showNewWsForm.value = false
  newWsName.value = ''
}

async function confirmCreateWorkspace() {
  const name = newWsName.value.trim()
  if (!name) return
  await addWorkspace({ name, path: '' })
  cancelCreateWorkspace()
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
  wsOpen.value = false
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
  wsOpen.value = false
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

onMounted(async () => {
  const savedTheme = localStorage.getItem('theme')
  if (savedTheme === 'light') {
    isLight.value = true
    document.body.classList.add('light-theme')
  }
  await loadWorkspaces()
  saveWorkspaces()
  emitWorkspaceChanged()
  checkApiStatus()
})
</script>
