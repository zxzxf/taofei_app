/**
 * 预加载脚本：在隔离环境中向前端暴露最小能力。
 * 当前前端通过 HTTP 与后端通信，无需 Node 能力，仅暴露版本信息。
 */
const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('desktop', {
  isDesktop: true,
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
  },
});
