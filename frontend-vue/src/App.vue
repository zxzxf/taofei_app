<template>
  <!-- 启动 loading：初始化完成前显示，避免页面短暂空白/卡顿无反馈 -->
  <div v-if="!bootReady" class="boot-loading">
    <div class="boot-logo">淘飞<span>AI</span></div>
    <div class="boot-sub">企业级 AI 智能体平台</div>
    <div class="boot-spinner"></div>
    <div class="boot-text">{{ bootText }}</div>
  </div>

  <template v-else>
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
        <span class="icon">🤖</span> 智能体
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

      <!-- 3.3 插件贡献项（nav section） -->
      <template v-if="pluginNavItems.length">
        <div class="nav-plugin-sep"></div>
        <button
          v-for="it in pluginNavItems"
          :key="it.id"
          class="nav-item plugin"
          :class="{ active: it.path && route.path === it.path }"
          @click="runPluginItem(it)"
        >
          <span class="icon">{{ it.icon }}</span> {{ it.label }}
          <span v-if="it.badge" class="nav-badge">{{ it.badge }}</span>
        </button>
      </template>
    </nav>

    <!-- 3.3 插件贡献项（bottom section） -->
    <div v-if="pluginBottomItems.length" class="nav-bottom-plugins">
      <button
        v-for="it in pluginBottomItems"
        :key="it.id"
        class="nav-item plugin bottom"
        @click="runPluginItem(it)"
      >
        <span class="icon">{{ it.icon }}</span> {{ it.label }}
      </button>
    </div>

    <div class="nav-bottom">
      <div class="api-status">
        <span class="dot" :class="apiStatus"></span>
        <span>{{ apiText }}</span>
      </div>
      <div class="ws-status" :title="wsStatusText">
        <span class="ws-dot" :class="wsStatus"></span>
        <span>{{ wsStatusText }}</span>
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

  <!-- 应用内自定义对话框（替代原生 confirm/alert/prompt，规避 Electron 焦点缺陷） -->
  <AppDialog />
  </template>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useRouter as useAppRouter } from 'vue-router'
import wsManager from './utils/wsManager.js'
import AppDialog from './components/AppDialog.vue'
import { appConfirm, appPrompt } from './utils/appDialog.js'
// 3.3 插件化扩展机制：注册表 + 自动发现 modules/
import { pluginRegistry, getSidebarContributions, loadPluginModules } from './plugins/registry.js'

const route = useRoute()
const router = useRouter()

// ===== 3.3 插件化扩展机制 =====
const pluginNavItems = computed(() => getSidebarContributions('nav'))
const pluginBottomItems = computed(() => getSidebarContributions('bottom'))

function runPluginItem(item) {
  if (!item) return
  if (item.path) {
    router.push(item.path)
    return
  }
  if (typeof item.action === 'function') {
    try {
      // 注入宿主能力
      item.action({
        router,
        toast: showToast,
        appConfirm,
        appPrompt,
      })
    } catch (e) {
      console.error(`[plugin] 执行动作失败（${item.pluginId}/${item.id}）`, e)
      showToast('插件动作执行失败')
    }
  }
}

const workspaces = ref([])
const currentWsId = ref(null)
const fullAccess = ref(false)
const apiStatus = ref('')
const apiText = ref('检测服务状态…')
const wsStatus = ref('disconnected')
const isLight = ref(false)
const toastVisible = ref(false)
const toastMsg = ref('')
const bootReady = ref(false)
const bootText = ref('正在加载工作台…')

const currentWsName = computed(() => {
  const ws = workspaces.value.find(w => w.id === currentWsId.value)
  return ws ? ws.name : '选择工作空间'
})

const pageTitle = computed(() => route.meta.title || '淘飞AI')
const pageTags = computed(() => route.meta.tags || [])

const wsStatusText = computed(() => {
  if (wsStatus.value === 'connected') return '实时已连接'
  if (wsStatus.value === 'connecting') return '实时连接中…'
  return '实时未连接'
})

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
    } else {
      console.warn('加载工作空间列表失败：HTTP', res.status)
    }
  } catch (e) {
    console.error('加载工作空间失败', e)
    // 后端不可用时，保留 localStorage 中的缓存数据
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
  // 浏览器端（File System Access API / input directory）拿不到绝对路径，
  // 后端必须用真实路径才能扫描目录，path 为空时直接提示，不创建假空间。
  if (!ws.path || !String(ws.path).trim()) {
    showToast('浏览器端无法获取目录绝对路径，请使用桌面客户端或输入路径')
    return
  }
  try {
    const res = await fetch('/api/workspaces', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: ws.name, path: ws.path }),
    })
    if (res.ok) {
      const data = await res.json()
      // 后端返回的是单个 workspace 对象，需要合并到列表中
      if (data.workspace) {
        // 检查是否已存在同路径的工作空间（去重）
        const exists = workspaces.value.find(w => w.path === data.workspace.path)
        if (!exists) {
          workspaces.value.push(data.workspace)
        }
      } else if (data.workspaces && Array.isArray(data.workspaces)) {
        workspaces.value = data.workspaces
      }
      currentWsId.value = data.current_id
    } else {
      const err = await res.json().catch(() => ({}))
      showToast('工作空间添加失败：' + (err.error || `HTTP ${res.status}`))
      return
    }
  } catch (e) {
    showToast('工作空间添加失败：' + (e.message || String(e)))
    return
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
      showToast('目录选择失败：' + (e.message || String(e)))
    }
    if (picked.canceled) return
    const name = picked.path.split(/[\\/]/).pop() || '本地目录'
    await addWorkspace({ name, path: picked.path })
    return
  }

  // 2. 浏览器端：File System Access API 拿不到绝对路径，改用输入路径方式
  if (window.showDirectoryPicker) {
    const typed = await appPrompt(
      '浏览器无法获取目录绝对路径，请粘贴或输入本地文件夹路径：\n（例如 D:\\projects\\my-app）',
      '',
      '打开本地目录',
    )
    if (!typed) return
    const trimmed = typed.trim()
    const name = trimmed.split(/[\\/]/).filter(Boolean).pop() || '本地目录'
    await addWorkspace({ name, path: trimmed })
    return
  }

  // 3. 兜底：input directory 选择（只能拿到相对文件列表，无绝对路径）→ 同样走输入路径
  const typed = await appPrompt(
    '请粘贴或输入要打开的本地文件夹路径：\n（例如 D:\\projects\\my-app）',
    '',
    '打开本地目录',
  )
  if (!typed) return
  const trimmed = typed.trim()
  const name = trimmed.split(/[\\/]/).filter(Boolean).pop() || '本地目录'
  await addWorkspace({ name, path: trimmed })
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
  if (!(await appConfirm('确定删除该工作空间？'))) return
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
  // 3.3 插件化：启动时扫描加载 plugins/modules/
  loadPluginModules()
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
  wsManager.connect()
  wsStatus.value = wsManager.status
  wsUnsub = wsManager.onStatus((s) => { wsStatus.value = s })

  // 启动 loading：等待健康检查 + 初始化完成后淡出
  try {
    const res = await fetch('/api/health')
    if (res.ok) {
      const data = await res.json()
      if (data && data.embedding_warmup === false) {
        bootText.value = '正在预热本地模型（首次启动可能需要 1-2 分钟）…'
      }
    }
  } catch { /* 健康检查失败不阻塞进入 */ }
  // 至少展示片刻，避免 loading 一闪而过
  await new Promise((r) => setTimeout(r, 700))
  bootReady.value = true
})

let wsUnsub = null
onUnmounted(() => {
  if (wsUnsub) {
    wsUnsub()
    wsUnsub = null
  }
})
</script>

<style scoped>
/* 启动 loading：与 Electron splash 呼应，页面初始化完成前显示 */
.boot-loading {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: var(--bg, #05080f);
  color: var(--text-secondary, #94a3b8);
  font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
}
.boot-logo {
  font-size: 30px;
  font-weight: 700;
  letter-spacing: 2px;
  color: var(--text, #e2e8f0);
  margin-bottom: 6px;
}
.boot-logo span { color: var(--primary, #3b82f6); }
.boot-sub {
  font-size: 12px;
  color: var(--text-muted, #64748b);
  margin-bottom: 28px;
}
.boot-spinner {
  width: 30px;
  height: 30px;
  margin-bottom: 18px;
  border: 3px solid rgba(139, 92, 246, 0.18);
  border-top-color: var(--primary, #3b82f6);
  border-radius: 50%;
  animation: boot-spin 0.9s linear infinite;
}
@keyframes boot-spin {
  to { transform: rotate(360deg); }
}
.boot-text {
  font-size: 12.5px;
  color: var(--text-muted, #64748b);
}
</style>
