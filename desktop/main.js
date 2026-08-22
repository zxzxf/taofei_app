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
const { app, BrowserWindow, Menu, dialog, ipcMain } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');
const os = require('os');

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
// 说明：splash 改用本地 HTML 文件（而非 data: URL），并等 ready-to-show
//       再显示。首次启动时 CPU 被 PyInstaller 冷启动/杀软扫描占用，
//       data: URL 渲染可能延迟，导致窗口先显示为空白框。
// ---------------------------------------------------------------
function getSplashPath() {
  // 打包模式：splash.html 随 extraResources 打进 resources/ 根目录
  if (isDev) return path.join(__dirname, 'splash.html');
  return path.join(process.resourcesPath, 'splash.html');
}

function createSplash() {
  const splashHtml = getSplashPath();
  splashWindow = new BrowserWindow({
    width: 460,
    height: 340,
    frame: false,
    resizable: false,
    center: true,
    show: false, // 等页面渲染完成再显示，避免首次启动出现空白框
    backgroundColor: '#0f172a',
    icon: path.join(__dirname, 'icon.ico'),
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });

  // 渲染完成后再显示：保证用户看到的是完整闪屏而不是空白
  splashWindow.once('ready-to-show', () => {
    if (splashWindow && !splashWindow.isDestroyed()) splashWindow.show();
  });

  // 加载失败兜底：本地 HTML 异常时也显示窗口，避免永远看不到任何反馈
  splashWindow.webContents.on('did-fail-load', () => {
    if (splashWindow && !splashWindow.isDestroyed()) splashWindow.show();
  });

  if (fs.existsSync(splashHtml)) {
    splashWindow.loadFile(splashHtml);
  } else {
    // 兜底：HTML 文件缺失时显示纯色窗口（至少不是白屏）
    if (splashWindow && !splashWindow.isDestroyed()) splashWindow.show();
  }
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
    icon: path.join(__dirname, 'icon.ico'),
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

// ---------------------------------------------------------------
// IPC：原生目录选择（前端「浏览器打开本地目录」按钮调用）
//   返回值 { canceled: true } 或 { canceled: false, path: 'E:\\...' }
//
//   关键：每次都显式传 defaultPath（经验 912091），避免依赖系统记忆机制导致
//   默认打开位置不确定。渲染进程也可以通过 options.defaultPath 指定首选目录。
// ---------------------------------------------------------------
async function handleOpenDirectoryPicker(options = {}) {
  const owner = mainWindow && !mainWindow.isDestroyed() ? mainWindow : null;
  const userHome = (os.homedir && fs.existsSync(os.homedir())) ? os.homedir() : process.cwd();
  const defaultPath = (options.defaultPath && fs.existsSync(options.defaultPath))
    ? options.defaultPath
    : userHome;
  const res = await dialog.showOpenDialog(owner, {
    // Windows 下 Electron dialog 标题如果直接用中文，某些系统会出现 GBK/UTF-8 解码错误导致乱码，
    // 因此默认 title 使用英文；调用方可通过 options.title 自行覆盖。
    title: options.title || 'Browser Open Local Directory · Select Folder',
    buttonLabel: options.buttonLabel || '选择文件夹',
    defaultPath,
    properties: ['openDirectory'],
  });
  if (res.canceled || !res.filePaths || !res.filePaths[0]) {
    return { canceled: true, path: '' };
  }
  return { canceled: false, path: String(res.filePaths[0]) };
}
ipcMain.handle('open-directory-picker', (_event, options = {}) =>
  handleOpenDirectoryPicker(options)
);

// ---------------------------------------------------------------
// 自动化测试钩子：设置 TAOFEI_TEST_PICKER=1 启动 electron 时，
// 主窗口加载完成后会主动触发一次「选择文件夹」对话框，并把结果写入
// %TEMP%\\taofei_picker_result.json，用于脚本侧验证。
//
// 判定规则：
//   - JSON.timedOut === true        → 系统原生模态对话框真实弹出（等用户交互） ✓ PASS
//   - JSON.canceled / JSON.path     → 用户提前点了按钮 / 接口异常（非预期）
// ---------------------------------------------------------------
function installPickerTestHook() {
  if (process.env.TAOFEI_TEST_PICKER !== '1') return;
  const outFile = path.join(os.tmpdir ? os.tmpdir() : process.cwd(), 'taofei_picker_result.json');
  try { fs.unlinkSync(outFile); } catch (_) { /* noop */ }
  const writeResult = (obj) => {
    try { fs.writeFileSync(outFile, JSON.stringify({ ts: Date.now(), ...obj }), 'utf-8'); }
    catch (_) { /* noop */ }
  };
  app.on('browser-window-created', (_, win) => {
    const doRun = async () => {
      try {
        await win.webContents.executeJavaScript('true'); // 等 webContents 初始化
      } catch (_) { /* noop */ }
      // 主窗 ready-to-show 后再等一小会，让页面+上下文就位
      const timedRace = new Promise((resolve) => {
        setTimeout(() => resolve({ timedOut: true }), 5000);
      });
      const pickResult = handleOpenDirectoryPicker({
        title: '[Test] Browser Open Local Directory · Pick a folder within 5s',
        defaultPath: process.cwd(),
      }).then((r) => ({ settled: true, canceled: r.canceled, path: r.path }))
        .catch((e) => ({ settled: true, error: String(e && e.message || e) }));
      const result = await Promise.race([timedRace, pickResult]);
      writeResult(result);
      // 写结果后 1s 自动退出 electron，避免挂着对话框挡用户
      setTimeout(() => {
        try { app.quit(); } catch (_) { process.exit(0); }
      }, 1000);
    };
    if (win === mainWindow) {
      win.once('ready-to-show', () => { setTimeout(doRun, 800); });
    }
  });
}
installPickerTestHook();
