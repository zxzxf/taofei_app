# 侧边栏插件机制（Contribution API）

## 一、原理

应用启动时自动扫描 `src/plugins/modules/` 目录，目录下**每个 .js 文件 = 一个插件**。
文件默认导出插件描述对象，即可向侧边栏贡献入口项——**加文件即加插件，无需改动 App.vue**。

## 二、插件描述结构

```js
export default {
  id: 'my-plugin',          // 必填，全局唯一（重复注册会被忽略）
  name: '我的插件',          // 插件名
  version: '1.0.0',         // 可选

  // 侧边栏贡献项（可多个）
  sidebar: [
    {
      id: 'entry-1',        // 必填，插件内唯一
      label: '入口名称',     // 必填，显示文本
      icon: '🔧',            // 必填，显示图标（emoji 或 svg 文本）
      badge: '新',           // 可选，右上角角标

      // 二选一：
      path: '/chat',        // ① 跳转已有路由
      action: ({ router, toast, appConfirm, appPrompt }) => {
        // ② 自定义动作，注入宿主能力（见下）
      },

      order: 90,            // 可选，排序（越小越靠前，默认 100）
      section: 'nav' | 'bottom', // 可选，nav=主导航区（默认）/ bottom=底部状态区上方
    },
  ],
}
```

## 三、action 注入的宿主能力

| 参数 | 说明 |
|------|------|
| `router` | Vue Router 实例，可 `router.push('/path')` |
| `toast(msg)` | 轻提示 |
| `appConfirm(msg)` | 确认框（Promise<boolean>） |
| `appPrompt(msg, def)` | 输入框（Promise<string\|null>） |

## 四、示例

- `modules/example-shortcuts.js`：path 型，往主导航加两个快捷入口
- `modules/example-actions.js`：action 型，演示 toast 动作 + bottom 区贡献

## 五、禁用插件

在插件对象里加 `enabled: false` 即不渲染贡献项（保留注册）。

## 六、API（src/plugins/registry.js）

| 函数 | 说明 |
|------|------|
| `contribute(plugin)` | 手动注册插件（幂等） |
| `unregister(pluginId)` | 注销插件 |
| `getSidebarContributions(section)` | 取某区贡献项（按 order 排序） |
| `loadPluginModules()` | 扫描 modules/ 自动注册（App 启动时调用） |
| `pluginRegistry` | 响应式插件清单（reactive 数组） |
