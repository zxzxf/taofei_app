/**
 * 示例插件：快捷跳转（演示 path 型贡献）
 *
 * 复制本文件即可添加新的"侧边栏入口 → 已有页面"导航项，
 * 或参照 example-action.js 添加自定义动作型入口。
 */
export default {
  id: 'demo-shortcuts',
  name: '快捷导航示例',
  version: '1.0.0',
  sidebar: [
    {
      id: 'demo-go-agents',
      label: 'Agent 快捷入口',
      icon: '🧭',
      path: '/agents',
      order: 95,
      section: 'nav',
    },
    {
      id: 'demo-go-task',
      label: '任务编排直达',
      icon: '🧭',
      path: '/task',
      order: 96,
      section: 'nav',
    },
  ],
}
