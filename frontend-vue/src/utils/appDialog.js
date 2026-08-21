/**
 * 应用内自定义对话框（替代原生 confirm / alert / prompt）
 *
 * 为什么不用原生弹窗？
 *   Electron 桌面端中 window.confirm() / alert() / prompt() 是系统级模态对话框，
 *   关闭后 BrowserWindow 的系统级键盘焦点无法恢复，表现为"输入框打不了字"，
 *   必须点击标题栏或切换窗口才能恢复。此为 Electron 已知缺陷，唯一可靠解法
 *   是完全避免原生弹窗，改用页面内渲染的自定义对话框。
 *
 * 用法（Promise 风格，与原生语义一致）：
 *   const ok = await appConfirm('确定删除该会话？')
 *   await appAlert('已清空')
 *   const input = await appPrompt('请输入路径', 'D:\\projects')
 *     - 确认返回 true / 关闭文本；取消返回 false / null
 */
import { reactive } from 'vue'

export const dialogState = reactive({
  visible: false,
  type: 'confirm',        // 'confirm' | 'alert' | 'prompt'
  title: '提示',
  message: '',
  inputValue: '',
  defaultValue: '',
  resolve: null,
})

function open(type, title, message, defaultValue = '') {
  return new Promise((resolve) => {
    // 若上一个对话框尚未关闭，直接按取消处理，避免 Promise 悬挂
    if (dialogState.visible && dialogState.resolve) {
      dialogState.resolve(type === 'confirm' ? false : (type === 'prompt' ? null : undefined))
    }
    dialogState.type = type
    dialogState.title = title
    dialogState.message = message
    dialogState.defaultValue = defaultValue
    dialogState.inputValue = defaultValue
    dialogState.resolve = resolve
    dialogState.visible = true
  })
}

/** 确认框：确定 -> true，取消/关闭 -> false */
export function appConfirm(message, title = '请确认') {
  return open('confirm', title, message)
}

/** 提示框：确定 -> undefined */
export function appAlert(message, title = '提示') {
  return open('alert', title, message)
}

/** 输入框：确定 -> 输入内容（字符串），取消/关闭 -> null */
export function appPrompt(message, defaultValue = '', title = '请输入') {
  return open('prompt', title, message, defaultValue)
}

/** 对话框内部使用：结束当前对话框并返回结果 */
export function _settleDialog(result) {
  dialogState.visible = false
  const resolve = dialogState.resolve
  dialogState.resolve = null
  if (resolve) resolve(result)
}
