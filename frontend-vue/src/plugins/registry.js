/**
 * 侧边栏插件注册表（Contribution API）
 *
 * 用法：
 *   import { contribute } from '../plugins/registry.js'
 *   contribute({
 *     id: 'my-plugin',
 *     name: '我的插件',
 *     version: '1.0.0',
 *     sidebar: [
 *       {
 *         id: 'my-entry',
 *         label: '入口名称',
 *         icon: '🔧',
 *         // 二选一：
 *         path: '/chat',            // 跳转已有路由
 *         action: ({ router, toast }) => {...},  // 或自定义动作
 *         order: 90,                // 排序（越大越靠后，默认 100）
 *         section: 'nav' | 'bottom' // 渲染位置：主导航 / 底部（默认 nav）
 *       }
 *     ]
 *   })
 *
 * 贡献点 sidebar 项要求：id / label / icon 必填，path 与 action 至少一个。
 */
import { reactive } from 'vue'

// 插件清单（响应式：App.vue 计算属性依赖它）
export const pluginRegistry = reactive([])

/**
 * 注册一个插件。返回是否成功。
 * 同一 id 重复注册会被忽略（幂等）。
 */
export function contribute(plugin) {
  if (!plugin || typeof plugin.id !== 'string' || !plugin.id) {
    console.warn('[plugin] 插件缺少 id，忽略注册', plugin)
    return false
  }
  if (pluginRegistry.some(p => p.id === plugin.id)) {
    console.warn(`[plugin] 插件 ${plugin.id} 已注册，跳过重复注册`)
    return false
  }
  // 规范化 sidebar 项
  const sidebar = (plugin.sidebar || []).map(item => ({
    order: item.order ?? 100,
    section: item.section || 'nav',
    ...item,
  }))
  pluginRegistry.push({
    version: '0.1.0',
    enabled: true,
    ...plugin,
    sidebar,
  })
  console.log(`[plugin] 已注册插件：${plugin.id}（${sidebar.length} 个侧边栏贡献项）`)
  return true
}

/** 注销插件（按 id）。返回是否成功。 */
export function unregister(pluginId) {
  const idx = pluginRegistry.findIndex(p => p.id === pluginId)
  if (idx < 0) return false
  pluginRegistry.splice(idx, 1)
  console.log(`[plugin] 已注销插件：${pluginId}`)
  return true
}

/** 取全部启用的侧边栏贡献项（按 section 分组、组内按 order 排序）。 */
export function getSidebarContributions(section = 'nav') {
  const items = []
  for (const plugin of pluginRegistry) {
    if (plugin.enabled === false) continue
    for (const item of plugin.sidebar) {
      if (item.section !== section) continue
      items.push({ ...item, pluginId: plugin.id })
    }
  }
  items.sort((a, b) => a.order - b.order)
  return items
}

/** 自动发现并注册 src/plugins/modules/ 下的所有插件文件 */
export function loadPluginModules() {
  try {
    // vite 构建时静态扫描 modules 目录，每文件默认导出即插件描述
    const modules = import.meta.glob('./modules/*.js', { eager: true })
    let count = 0
    for (const filePath of Object.keys(modules)) {
      const mod = modules[filePath]
      const plugin = mod.default || mod.plugin
      if (plugin && contribute(plugin)) count++
    }
    if (count > 0) {
      console.log(`[plugin] 自动加载完成，共 ${count} 个文件插件`)
    }
  } catch (e) {
    console.error('[plugin] 插件目录扫描失败', e)
  }
}
