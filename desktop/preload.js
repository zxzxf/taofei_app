/**
 * 预加载脚本：在隔离环境中向前端暴露最小能力。
 * - 桌面端（Electron 打包后）点击「浏览器打开本地目录」时，会通过这里调主进程的
 *   dialog.showOpenDialog，直接弹系统原生的「选择文件夹」对话框（和 Windows
 *   资源管理器一致的体验，而不是 prompt 粘贴路径）。
 * - 其他后端交互仍通过 HTTP /api 完成，不在这里暴露 Node 能力。
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktop', {
  isDesktop: true,
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
  },
  /**
   * 弹系统原生「选择文件夹」对话框。
   *
   * @returns {Promise<{canceled: boolean, path: string}>}
   *   - 用户点取消：{ canceled: true, path: '' }
   *   - 用户选定目录：{ canceled: false, path: 'E:\\...' }
   */
  openDirectoryPicker(options = {}) {
    return ipcRenderer.invoke('open-directory-picker', options);
  },
});
