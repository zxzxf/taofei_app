/**
 * 轻量 i18n（6.1 国际化）
 *
 * 设计：零依赖、响应式、点路径取值。
 *   - locale：'zh-CN' | 'en-US'，localStorage 持久化（key: locale）
 *   - t('a.b.c')：从当前语言包按点路径取文案；缺失回退中文包；再缺失返回 key 本身
 *   - 语言包按需渐进补充：新界面文案先加 zh-CN/en-US 两个文件即可
 *
 * 组件内用法：
 *   import { t } from '../i18n'
 *   // 模板：{{ t('nav.chat') }}  脚本：const label = t('sidebar.newChat')
 *   // t() 内部读取响应式 locale，切换语言自动触发重渲染
 */
import { ref, computed } from 'vue'
import zhCN from './zh-CN.js'
import enUS from './en-US.js'

const messages = {
  'zh-CN': zhCN,
  'en-US': enUS,
}

/** 当前语言（响应式） */
const locale = ref(localStorage.getItem('locale') || 'zh-CN')
// 不支持的 locale 兜底
if (!messages[locale.value]) locale.value = 'zh-CN'

/** 语言列表（用于切换菜单） */
const locales = [
  { code: 'zh-CN', label: '简体中文', short: '中' },
  { code: 'en-US', label: 'English', short: 'EN' },
]

/** 深拷贝式的简单 get：按点路径取对象值 */
function lookup(obj, path) {
  const parts = path.split('.')
  let cur = obj
  for (const p of parts) {
    if (cur == null) return undefined
    cur = cur[p]
  }
  return typeof cur === 'string' ? cur : undefined
}

/** 翻译函数（响应式：读 locale）。t(key) 或 t(key, { n: 5 }) 插值 {n} */
export function t(key, params) {
  if (!key) return key
  const dict = messages[locale.value]
  // 当前语言 → 中文兜底 → key
  let text = lookup(dict, key) ?? lookup(messages['zh-CN'], key) ?? key
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      text = text.replaceAll(`{${k}}`, String(v))
    }
  }
  return text
}

/** 当前语言代码（响应式） */
export const currentLocale = computed(() => locale.value)

/** 切换语言并持久化 */
export function setLocale(code) {
  if (!messages[code]) return
  locale.value = code
  localStorage.setItem('locale', code)
  // 通知文档语言属性（辅助阅读器/字体渲染）
  document.documentElement.lang = code === 'zh-CN' ? 'zh-CN' : 'en'
}

/** 初始化：应用文档 lang */
export function initI18n() {
  document.documentElement.lang = locale.value === 'zh-CN' ? 'zh-CN' : 'en'
}

export { locales }
