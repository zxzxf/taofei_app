class WSManager {
  constructor() {
    this.status = 'disconnected' // disconnected | connecting | connected
    this.ws = null
    this.reconnectAttempts = 0
    this.reconnectTimer = null
    this.heartbeatTimer = null
    this.connId = null

    this.subscribers = new Map() // task_id -> Set<callback>
    this.pendingSubs = new Set() // 重连后需要重新订阅的 task_id

    this.logSubscribers = new Map() // filterKey('__all__' or task_id) -> Set<callback>
    this.pendingLogSubs = new Set() // 重连后需要重新订阅的日志 filter

    this._listeners = new Set() // 全局状态监听
    this._manualClose = false
  }

  get wsUrl() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${location.host}/api/ws`
  }

  connect() {
    if (this.status === 'connecting' || this.status === 'connected') return
    this._manualClose = false
    this._doConnect()
  }

  _doConnect() {
    this.status = 'connecting'
    this._emitStatus()

    try {
      this.ws = new WebSocket(this.wsUrl)
    } catch (e) {
      this.status = 'disconnected'
      this._emitStatus()
      this._scheduleReconnect()
      return
    }

    this.ws.onopen = () => {
      this.reconnectAttempts = 0
      this.status = 'connected'
      this._emitStatus()
      this._startHeartbeat()

      for (const taskId of this.pendingSubs) {
        this._send({ type: 'subscribe', task_id: taskId })
      }
      for (const filterKey of this.pendingLogSubs) {
        if (filterKey === '__all__') {
          this._send({ type: 'subscribe_logs' })
        } else {
          this._send({ type: 'subscribe_logs', task_id: filterKey })
        }
      }
    }

    this.ws.onmessage = (event) => {
      let msg
      try {
        msg = JSON.parse(event.data)
      } catch {
        return
      }
      this._handleMessage(msg)
    }

    this.ws.onerror = () => {
      // 错误会触发 close，在 onclose 里处理重连
    }

    this.ws.onclose = () => {
      this._stopHeartbeat()
      this.connId = null
      this.status = 'disconnected'
      this._emitStatus()
      if (!this._manualClose) {
        this._scheduleReconnect()
      }
    }
  }

  disconnect() {
    this._manualClose = true
    this._stopHeartbeat()
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      try { this.ws.close() } catch {}
      this.ws = null
    }
    this.status = 'disconnected'
    this._emitStatus()
  }

  _scheduleReconnect() {
    if (this._manualClose) return
    if (this.reconnectTimer) return
    this.reconnectAttempts += 1
    const delay = Math.min(30000, 1000 * Math.pow(2, Math.min(this.reconnectAttempts - 1, 5)))
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this._doConnect()
    }, delay)
  }

  _startHeartbeat() {
    this._stopHeartbeat()
    this.heartbeatTimer = setInterval(() => {
      if (this.status === 'connected' && this.ws && this.ws.readyState === WebSocket.OPEN) {
        this._send({ type: 'ping', ts: Date.now() })
      }
    }, 30000)
  }

  _stopHeartbeat() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  _send(data) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data))
      return true
    }
    return false
  }

  _handleMessage(msg) {
    const type = msg.type
    if (type === 'connected') {
      this.connId = msg.conn_id
      return
    }
    if (type === 'pong') {
      return
    }
    if (type === 'task_update' || type === 'task_done') {
      const taskId = msg.task_id
      const callbacks = this.subscribers.get(taskId)
      if (callbacks) {
        for (const cb of callbacks) {
          try { cb(msg) } catch (e) { console.error('[ws] callback error', e) }
        }
      }
      if (type === 'task_done') {
        // 保留订阅，不自动移除（前端可能还想看历史）
      }
      return
    }
    if (type === 'task_list') {
      // 全局事件
      this._emitGlobal('task_list', msg.tasks)
      return
    }
    if (type === 'log') {
      const rec = msg.record || {}
      const taskId = rec.task_id
      const allCallbacks = this.logSubscribers.get('__all__')
      if (allCallbacks) {
        for (const cb of allCallbacks) {
          try { cb(rec) } catch (e) { console.error('[ws] log callback error', e) }
        }
      }
      if (taskId) {
        const taskCallbacks = this.logSubscribers.get(taskId)
        if (taskCallbacks) {
          for (const cb of taskCallbacks) {
            try { cb(rec) } catch (e) { console.error('[ws] log callback error', e) }
          }
        }
      }
      return
    }
    if (type === 'cancelled') {
      this._emitGlobal('cancelled', msg.task_id)
      return
    }
    if (type === 'error') {
      this._emitGlobal('error', msg)
      return
    }
  }

  subscribe(taskId, callback) {
    if (!this.subscribers.has(taskId)) {
      this.subscribers.set(taskId, new Set())
    }
    this.subscribers.get(taskId).add(callback)
    this.pendingSubs.add(taskId)

    if (this.status === 'connected') {
      this._send({ type: 'subscribe', task_id: taskId })
    }

    return () => this.unsubscribe(taskId, callback)
  }

  unsubscribe(taskId, callback) {
    const callbacks = this.subscribers.get(taskId)
    if (!callbacks) return
    if (callback) {
      callbacks.delete(callback)
    }
    if (!callback || callbacks.size === 0) {
      this.subscribers.delete(taskId)
      this.pendingSubs.delete(taskId)
      if (this.status === 'connected') {
        this._send({ type: 'unsubscribe', task_id: taskId })
      }
    }
  }

  cancelTask(taskId) {
    return this._send({ type: 'cancel_task', task_id: taskId })
  }

  subscribeLogs(callback, taskId = null) {
    const key = taskId || '__all__'
    if (!this.logSubscribers.has(key)) {
      this.logSubscribers.set(key, new Set())
    }
    this.logSubscribers.get(key).add(callback)
    this.pendingLogSubs.add(key)

    if (this.status === 'connected') {
      if (taskId) {
        this._send({ type: 'subscribe_logs', task_id: taskId })
      } else {
        this._send({ type: 'subscribe_logs' })
      }
    }

    return () => this.unsubscribeLogs(callback, taskId)
  }

  unsubscribeLogs(callback, taskId = null) {
    const key = taskId || '__all__'
    const callbacks = this.logSubscribers.get(key)
    if (!callbacks) return
    if (callback) {
      callbacks.delete(callback)
    }
    if (!callback || callbacks.size === 0) {
      this.logSubscribers.delete(key)
      this.pendingLogSubs.delete(key)
      if (this.status === 'connected') {
        if (taskId) {
          this._send({ type: 'unsubscribe_logs', task_id: taskId })
        } else {
          this._send({ type: 'unsubscribe_logs' })
        }
      }
    }
  }

  listTasks() {
    return this._send({ type: 'list_tasks' })
  }

  onStatus(callback) {
    this._listeners.add(callback)
    callback(this.status)
    return () => this._listeners.delete(callback)
  }

  _emitStatus() {
    for (const cb of this._listeners) {
      try { cb(this.status) } catch (e) { console.error('[ws] status listener error', e) }
    }
  }

  onGlobal(eventName, callback) {
    const handler = (name, data) => { if (name === eventName) callback(data) }
    this._globalListeners = this._globalListeners || new Set()
    this._globalListeners.add(handler)
    return () => this._globalListeners.delete(handler)
  }

  _emitGlobal(name, data) {
    if (!this._globalListeners) return
    for (const cb of this._globalListeners) {
      try { cb(name, data) } catch (e) { console.error('[ws] global listener error', e) }
    }
  }
}

const wsManager = new WSManager()
export default wsManager
