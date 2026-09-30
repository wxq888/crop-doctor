/* ==========================================================================
   WebSocket 封装（监控大屏实时事件流）
   契约见 impl-pc-admin-v1 §3.2：
   - 信封 {v:1,type,ts,data}
   - 鉴权用 query 参数 ?token=<jwt>（浏览器 WS 无法带请求头）
   - 服务端每 25s 发 ping；前端 60s 看门狗；指数退避重连 1→30s（±20% 抖动）
   ========================================================================== */

/** 看门狗：60s 内无任何帧判定掉线 */
const WATCHDOG_TIMEOUT = 60 * 1000
/** 退避起始 / 上限 */
const BASE_DELAY = 1000
const MAX_DELAY = 30000

/**
 * 单例 WebSocket 客户端：负责连接、心跳看门狗、指数退避重连与事件分发。
 * 通过 on('open'|'message'|'close'|'status', fn) 订阅，返回取消订阅函数。
 */
class WsClient {
  constructor() {
    /** @type {WebSocket|null} */
    this.ws = null
    this.url = ''
    this.token = ''
    /** 主动关闭标记：为 true 时不触发重连 */
    this.manualClosed = false
    /** 已重连次数（用于退避） */
    this.attempt = 0
    /** @type {ReturnType<typeof setTimeout>|null} */
    this.reconnectTimer = null
    /** @type {ReturnType<typeof setTimeout>|null} */
    this.watchdogTimer = null
    /** 订阅表 */
    this.handlers = { open: [], message: [], close: [], status: [] }
  }

  /**
   * 订阅事件。
   * @param {'open'|'message'|'close'|'status'} type
   * @param {(payload:any)=>void} fn
   * @returns {()=>void} 取消订阅
   */
  on(type, fn) {
    if (!this.handlers[type]) this.handlers[type] = []
    this.handlers[type].push(fn)
    return () => this.off(type, fn)
  }

  /** 取消订阅 */
  off(type, fn) {
    const list = this.handlers[type]
    if (!list) return
    const idx = list.indexOf(fn)
    if (idx >= 0) list.splice(idx, 1)
  }

  /** 内部：触发某类事件 */
  emit(type, payload) {
    const list = this.handlers[type] || []
    list.slice().forEach((fn) => {
      try {
        fn(payload)
      } catch (e) {
        // 单个订阅者异常不影响其余订阅者
        console.error('[ws] handler error', e)
      }
    })
  }

  /**
   * 建立连接（同 URL 重复调用会重置连接）。
   * @param {string} url 形如 ws://host/api/v1/admin/ws/monitor
   * @param {string} token JWT
   */
  connect(url, token) {
    this.url = url
    this.token = token || ''
    this.manualClosed = false
    this.attempt = 0
    this._open()
  }

  /** 主动断开（不再重连） */
  close() {
    this.manualClosed = true
    this._clearTimers()
    this._teardownSocket()
    this.emit('status', false)
  }

  /** 发送 JSON 帧（如 pong 心跳） */
  send(obj) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      try {
        this.ws.send(JSON.stringify(obj))
      } catch (e) {
        console.error('[ws] send error', e)
      }
    }
  }

  /** 内部：真正打开 socket */
  _open() {
    this._teardownSocket()
    if (!this.url) return
    const fullUrl = `${this.url}?token=${encodeURIComponent(this.token)}`
    let socket
    try {
      socket = new WebSocket(fullUrl)
    } catch (e) {
      console.error('[ws] create error', e)
      this._scheduleReconnect()
      return
    }
    this.ws = socket

    socket.onopen = () => {
      this.attempt = 0
      this._resetWatchdog()
      this.emit('open')
      this.emit('status', true)
    }
    socket.onmessage = (ev) => {
      this._resetWatchdog()
      this.emit('message', ev.data)
    }
    socket.onerror = () => {
      // 具体错误随 onclose 处理，这里仅静默
    }
    socket.onclose = (ev) => {
      this.emit('status', false)
      this.emit('close', ev)
      if (!this.manualClosed) {
        this._scheduleReconnect()
      }
    }
  }

  /** 内部：看门狗重置 */
  _resetWatchdog() {
    if (this.watchdogTimer) clearTimeout(this.watchdogTimer)
    this.watchdogTimer = setTimeout(() => {
      // 超时无帧 → 强制断开并重连
      this._teardownSocket()
      if (!this.manualClosed) this._scheduleReconnect()
    }, WATCHDOG_TIMEOUT)
  }

  /** 内部：排定重连（指数退避 + ±20% 抖动） */
  _scheduleReconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    const delay = this._nextBackoff()
    this.reconnectTimer = setTimeout(() => this._open(), delay)
  }

  /** 内部：计算下一次退避时长 */
  _nextBackoff() {
    const raw = Math.min(MAX_DELAY, BASE_DELAY * Math.pow(2, this.attempt))
    this.attempt += 1
    const jitter = raw * 0.2 * (Math.random() * 2 - 1)
    return Math.max(BASE_DELAY, Math.round(raw + jitter))
  }

  /** 内部：清理定时器 */
  _clearTimers() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.watchdogTimer) {
      clearTimeout(this.watchdogTimer)
      this.watchdogTimer = null
    }
  }

  /** 内部：销毁当前 socket 且不触发重连 */
  _teardownSocket() {
    if (this.watchdogTimer) {
      clearTimeout(this.watchdogTimer)
      this.watchdogTimer = null
    }
    if (this.ws) {
      const s = this.ws
      this.ws = null
      s.onopen = null
      s.onmessage = null
      s.onclose = null
      s.onerror = null
      try {
        s.close()
      } catch (e) {
        // 忽略关闭异常
      }
    }
  }
}

/** 全局单例 */
export const wsClient = new WsClient()
