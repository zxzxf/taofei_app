/**
 * 示例插件：动作按钮（演示 action 型贡献 + 宿主能力注入）
 *
 * action 接收注入的宿主 API：
 *   { router, toast, appConfirm }
 * 可执行任意自定义逻辑（跳转、提示、调用后端等）。
 */
export default {
  id: 'demo-actions',
  name: '动作按钮示例',
  version: '1.0.0',
  sidebar: [
    {
      id: 'demo-hello',
      label: '打招呼',
      icon: '👋',
      action: ({ toast }) => toast('你好！插件机制已就绪 🎉'),
      order: 97,
      section: 'nav',
    },
    {
      id: 'demo-bottom',
      label: '版本信息',
      icon: 'ℹ️',
      action: ({ toast }) => toast('淘飞AI · 插件化侧边栏 v1.0'),
      order: 10,
      section: 'bottom',
    },
  ],
}
