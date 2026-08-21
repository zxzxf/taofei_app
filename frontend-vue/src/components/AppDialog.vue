<template>
  <div v-if="dialogState.visible" class="app-dialog-overlay" @click.self="onCancel">
    <div class="app-dialog" role="dialog" aria-modal="true">
      <div class="app-dialog-header">
        <span class="app-dialog-title">{{ dialogState.title }}</span>
      </div>
      <div class="app-dialog-body">
        <div class="app-dialog-message">{{ dialogState.message }}</div>
        <input
          v-if="dialogState.type === 'prompt'"
          ref="inputRef"
          v-model="dialogState.inputValue"
          class="app-dialog-input"
          type="text"
          @keydown.enter="onPromptOk"
          @keydown.esc="onCancel"
        >
      </div>
      <div class="app-dialog-footer">
        <button v-if="dialogState.type !== 'alert'" class="app-dialog-btn cancel" @click="onCancel">取消</button>
        <button class="app-dialog-btn ok" @click="onOk">确定</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { dialogState, _settleDialog } from '../utils/appDialog.js'

const inputRef = ref(null)

// 对话框打开时：prompt 自动聚焦输入框；alert/confirm 聚焦确定按钮
// （全程页面内交互，不涉及系统级窗口焦点切换，Electron 输入不受影响）
watch(() => dialogState.visible, async (v) => {
  if (v) {
    await nextTick()
    if (dialogState.type === 'prompt' && inputRef.value) {
      inputRef.value.focus()
      inputRef.value.select()
    }
  }
})

function onOk() {
  if (dialogState.type === 'confirm') {
    _settleDialog(true)
  } else if (dialogState.type === 'prompt') {
    _settleDialog(dialogState.inputValue)
  } else {
    _settleDialog(undefined)
  }
}

function onPromptOk() {
  _settleDialog(dialogState.inputValue)
}

function onCancel() {
  if (dialogState.type === 'confirm') {
    _settleDialog(false)
  } else if (dialogState.type === 'prompt') {
    _settleDialog(null)
  } else {
    _settleDialog(undefined)
  }
}
</script>

<style scoped>
.app-dialog-overlay {
  position: fixed; top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(4px);
  z-index: 3000;
  display: flex; align-items: center; justify-content: center;
  padding: 16px;
}
.app-dialog {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  width: 100%; max-width: 420px;
  box-shadow: var(--shadow);
  display: flex; flex-direction: column;
  overflow: hidden;
}
.app-dialog-header {
  padding: 16px 20px 0;
}
.app-dialog-title {
  font-size: 15px; font-weight: 700; color: var(--text);
}
.app-dialog-body {
  padding: 12px 20px 16px;
}
.app-dialog-message {
  font-size: 13.5px; line-height: 1.65; color: var(--text);
  white-space: pre-wrap; word-break: break-word;
}
.app-dialog-input {
  width: 100%;
  margin-top: 12px;
  padding: 9px 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-strong);
  background: var(--bg-soft);
  color: var(--text);
  font-size: 13px;
  outline: none;
  box-sizing: border-box;
}
.app-dialog-input:focus {
  border-color: var(--accent, #3b82f6);
}
.app-dialog-footer {
  display: flex; justify-content: flex-end; gap: 10px;
  padding: 0 20px 18px;
}
.app-dialog-btn {
  padding: 8px 18px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-strong);
  background: var(--bg-soft);
  color: var(--text);
  font-size: 13px; font-weight: 600;
  cursor: pointer;
  transition: all .15s;
}
.app-dialog-btn:hover { filter: brightness(1.12); }
.app-dialog-btn.ok {
  background: var(--primary, #3b82f6);
  border-color: var(--primary, #3b82f6);
  color: #fff;
}
</style>
