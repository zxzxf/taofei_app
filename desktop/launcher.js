/**
 * 启动器：清除 ELECTRON_RUN_AS_NODE 环境变量后启动 electron。
 *
 * 背景：宿主环境（部分 IDE/终端，如 WorkBuddy/VS Code 系）会全局注入
 * ELECTRON_RUN_AS_NODE=1，导致 electron.exe 以纯 Node 模式运行，
 * require('electron') 拿不到 app 等 API。此脚本删除该变量后再拉起真正的 Electron。
 */
const { spawn } = require('child_process');
const path = require('path');

const env = { ...process.env };
delete env.ELECTRON_RUN_AS_NODE;

// 在普通 Node 模式下，require('electron') 返回 electron.exe 的路径字符串
const electronPath = require('electron');

const child = spawn(electronPath, ['.'], {
  stdio: 'inherit',
  env,
  cwd: __dirname,
});

child.on('close', (code) => process.exit(code ?? 0));
