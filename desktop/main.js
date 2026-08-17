/**
 * 淘飞AI 桌面客户端 - Electron 主进程
 *
 * 架构：
 *   Electron 主进程
 *     ├── 启动 Python FastAPI 后端（子进程）
 *     ├── 解析后端输出的 __BACKEND_PORT__:{port} 获取端口
 *     ├── 等待 /api/health 就绪
 *     └── 创建 BrowserWindow 加载 http://127.0.0.1:{port}
 *
 * 运行模式：
 *   开发模式（electron . 未打包）：直接调 .venv/python.exe 运行 backend/main.py
 *   生产模式（安装后）：运行 resources/backend/CrewAIWorkbench.exe
 */
const { app, BrowserWindow, Menu, dialog } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');

// 远程桌面/虚拟化环境下 GPU 进程易崩溃，禁用硬件加速改软件渲染
app.disableHardwareAcceleration();
app.commandLine.appendSwitch('disable-gpu');
app.commandLine.appendSwitch('disable-gpu-compositing');
app.commandLine.appendSwitch('disable-gpu-sandbox');
// GPU 子进程完全不可用时，让渲染走主进程（最后兜底）
app.commandLine.appendSwitch('in-process-gpu');

const isDev = !app.isPackaged;
// 打包模式下 PyInstaller 冷启动 + 杀软首次扫描可能很慢，超时给足余量
const BACKEND_START_TIMEOUT = 150000;
const HEALTH_TIMEOUT = 120000;

let mainWindow = null;
let splashWindow = null;
let backendProcess = null;
let backendPort = null;
let quitting = false;

// ---------------------------------------------------------------
// 启动闪屏：双击后立即出现，避免「等待后端期间屏幕上什么都没有」
// ---------------------------------------------------------------
function createSplash() {
  const html = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body {
    width: 100%; height: 100%; overflow: hidden;
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 60%, #0f766e 100%);
    font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
    color: #e2e8f0;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    -webkit-app-region: drag;
  }
  .logo {
    font-size: 34px; font-weight: 700; letter-spacing: 2px;
    color: #ffffff; margin-bottom: 6px;
  }
  .logo span { color: #2dd4bf; }
  .sub { font-size: 13px; color: #94a3b8; margin-bottom: 34px; }
  .spinner {
    width: 34px; height: 34px; margin-bottom: 22px;
    border: 3px solid rgba(255,255,255,.15);
    border-top-color: #2dd4bf; border-radius: 50%;
    animation: spin .9s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  #msg { font-size: 13px; color: #cbd5e1; }
  #tip { font-size: 11px; color: #64748b; margin-top: 10px; }
</style>
</head>
<body>
  <div class="logo">淘飞<span>AI</span></div>
  <div class="sub">企业级 AI 智能体平台</div>
  <div class="spinner"></div>
  <div id="msg">正在启动本地服务…</div>
  <div id="tip">首次启动需进行安全扫描，可能需要 1-2 分钟，请稍候</div>
  <script>
    window.__setMsg = function (t) { document.getElementById("msg").textContent = t; };
  </script>
</body>
</html>`;
  splashWindow = new BrowserWindow({
    width: 460,
    height: 340,
    frame: false,
    resizable: false,
    center: true,
    show: true,
    backgroundColor: '#0f172a',
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  splashWindow.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html));
  splashWindow.on('closed', () => { splashWindow = null; });
  return splashWindow;
}

// 更新闪屏状态文案（窗口可能已关闭，需判空）
function setSplashMsg(text) {
  try {
    if (splashWindow && !splashWindow.isDestroyed()) {
      splashWindow.webContents.executeJavaScript(
        `window.__setMsg && window.__setMsg(${JSON.stringify(text)})`
      ).catch(() => {});
    }
  } catch (_) { /* 忽略 */ }
}

// ---------------------------------------------------------------
// 后端命令定位
// ---------------------------------------------------------------
function getBackendCommand() {
  if (isDev) {
    // 开发模式：优先用项目根 .venv 的 Python
    const projectRoot = path.join(__dirname, '..');
    const venvPython = path.join(projectRoot, '.venv', 'Scripts', 'python.exe');
    const python = fs.existsSync(venvPython) ? venvPython : 'python';
    return {
      cmd: python,
      args: [path.join(projectRoot, 'backend', 'main.py'), '--no-browser'],
      cwd: projectRoot,
      env: process.env,
    };
  }
  // 生产模式：打包进 resources/backend 的 PyInstaller 目录构建
  const backendDir = path.join(process.resourcesPath, 'backend');
  return {
    cmd: path.join(backendDir, 'CrewAIWorkbench.exe'),
    args: ['--no-browser'],
    cwd: backendDir,
    env: process.env,
  };
}

// ---------------------------------------------------------------
// 启动后端子进程，解析端口
// ---------------------------------------------------------------
function startBackend() {
  return new Promise((resolve, reject) => {
    const { cmd, args, cwd, env } = getBackendCommand();

    if (!fs.existsSync(cmd) && cmd !== 'python') {
      reject(new Error(`后端可执行文件不存在：${cmd}\n请先运行 build\\build.bat 生成后端。`));
      return;
    }

    console.log(`[electron] starting backend: ${cmd} ${args.join(' ')}`);
    backendProcess = spawn(cmd, args, { cwd, env });

    let settled = false;
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        reject(new Error(`后端启动超时（${Math.round(BACKEND_START_TIMEOUT / 1000)} 秒）`));
      }
    }, BACKEND_START_TIMEOUT);

    backendProcess.stdout.on('data', (data) => {
      const text = data.toString();
      console.log(`[backend] ${text.trim()}`);
      const match = text.match(/__BACKEND_PORT__:(\d+)/);
      if (match && !settled) {
        settled = true;
        clearTimeout(timer);
        backendPort = parseInt(match[1], 10);
        resolve(backendPort);
      }
    });

    backendProcess.stderr.on('data', (data) => {
      console.error(`[backend:err] ${data.toString().trim()}`);
    });

    backendProcess.on('error', (err) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        reject(err);
      }
    });

    backendProcess.on('exit', (code) => {
      console.log(`[backend] exited with code ${code}`);
      backendProcess = null;
      // 非正常退出且不是用户主动关闭时，提示并退出
      if (!quitting && mainWindow && code !== 0 && code !== null) {
        dialog.showErrorBox(
          '后端服务异常退出',
          `后端进程退出（代码 ${code}），应用即将关闭。\n` +
            '常见原因：.env 缺失或 API Key 无效、端口被占用、杀毒软件拦截。'
        );
        app.quit();
      }
    });
  });
}

// ---------------------------------------------------------------
// 轮询健康检查，等待 HTTP 服务就绪
// ---------------------------------------------------------------
function waitForServer(port) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const check = () => {
      const req = http.get(`http://127.0.0.1:${port}/api/health`, (res) => {
        res.resume();
        resolve();
      });
      req.on('error', () => {
        if (Date.now() - start > HEALTH_TIMEOUT) {
          reject(new Error('等待后端 HTTP 服务就绪超时'));
        } else {
          setTimeout(check, 300);
        }
      });
    };
    check();
  });
}

// ---------------------------------------------------------------
// 主窗口
// ---------------------------------------------------------------
function createWindow(port) {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 680,
    show: false, // 等页面加载完成再显示，避免白屏
    title: '淘飞AI · 企业级AI智能体平台',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // 去掉默认菜单栏（保留快捷键能力）
  Menu.setApplicationMenu(null);

  mainWindow.once('ready-to-show', () => {
    // 主界面就绪：关闪屏、亮主窗，切换几乎无感
    if (splashWindow && !splashWindow.isDestroyed()) splashWindow.close();
    mainWindow.show();
  });

  // 阻止页面内跳转离开本地服务（例如误点外链时用系统浏览器打开）
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http://127.0.0.1')) return { action: 'allow' };
    require('electron').shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  mainWindow.loadURL(`http://127.0.0.1:${port}/`);
}

// ---------------------------------------------------------------
// 杀死后端进程（Windows 需 kill 整个进程树）
// ---------------------------------------------------------------
function killBackend() {
  if (backendProcess && backendProcess.pid) {
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', String(backendProcess.pid), '/f', '/t']);
    } else {
      backendProcess.kill('SIGTERM');
    }
    backendProcess = null;
  }
}

// ---------------------------------------------------------------
// 应用生命周期
// ---------------------------------------------------------------
app.whenReady().then(async () => {
  // 双击后立刻出闪屏，给用户即时反馈
  createSplash();
  try {
    const port = await startBackend();
    setSplashMsg('服务已启动，正在初始化界面…');
    console.log(`[electron] backend ready on port ${port}, waiting for HTTP...`);
    await waitForServer(port);
    console.log('[electron] backend HTTP ready, opening window');
    createWindow(port);
  } catch (err) {
    if (splashWindow && !splashWindow.isDestroyed()) splashWindow.close();
    dialog.showErrorBox(
      '启动失败',
      `后端服务启动失败：\n${err.message}\n\n` +
        '排查建议：\n' +
        '1. 检查是否被杀毒软件拦截（可将安装目录加入信任区）\n' +
        '2. 重启电脑后再试\n' +
        '3. 重新安装应用'
    );
    app.quit();
  }
});

app.on('window-all-closed', () => {
  quitting = true;
  killBackend();
  app.quit();
});

app.on('before-quit', () => {
  quitting = true;
  killBackend();
});

// 禁止多实例：第二个实例启动时聚焦已有窗口
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
}
