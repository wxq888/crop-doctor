/**
 * 预警实时推送 WS 客户端。
 *
 * 端点：`WS /api/v1/warning/ws/alerts?token=<jwt>`（任何已登录用户可用，非 admin-only）。
 * 浏览器 WebSocket 无法自定义请求头，token 走 query 参数（与 monitor WS / 实时检测 WS
 * 一致）。协议沿用 monitor WS 信封 `{v,type,ts,data}`，支持：
 *   hello            → 首帧，携带该用户可见的近期预警快照
 *   warning.created  → 新预警（全局广播或定向本人），前端弹通知 + 刷新角标
 *   ping / pong      → 心跳（服务端每 25s 发 ping）
 * close code：4401 未登录 / token 无效 · 4403 用户不存在或被禁用 · 4429 连接数超限。
 *
 * 设计要点：
 * - 登录后连接、登出 / 切到登录页断开；
 * - 断线**指数退避重连**（1→30s）；遇 4401 / 4403（鉴权类）**停止重连**，等重新登录；
 * - 连接失败 / 无 token 时**静默**，绝不影响其它功能；
 * - 仅作实时增强，**保留既有轮询兜底**（stores/badge.js 的 refresh）。
 */

// 与 api/request.js 同源的后端地址（如 http://127.0.0.1:8000/api/v1）
const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api/v1'

/** 重连退避上限（秒） */
const MAX_BACKOFF_SECONDS = 30
/** 客户端心跳间隔（秒）：服务端每 25s 也会发 ping，这里仅作额外保活 */
const CLIENT_PING_SECONDS = 20

/**
 * 构造预警 WS 完整 URL。
 * @param {string} token 登录 JWT（可空，空时由服务端 close 4401）
 * @returns {string} ws(s)://host/api/v1/warning/ws/alerts?token=xxx
 */
export function buildAlertsWsUrl(token) {
  const base = API_BASE.replace(/^http/, 'ws').replace(/\/+$/, '')
  const url = new URL(`${base}/warning/ws/alerts`)
  if (token) url.searchParams.set('token', token)
  return url.toString()
}

/**
 * 预警 WS 连接管理器（单例）：管理连接生命周期、指数退避重连、心跳与订阅分发。
 */
class AlertsWsManager {
  constructor() {
    /** @type {WebSocket|null} */
    this.ws = null
    /** 当前使用的 JWT */
    this.token = ''
    /** 是否应保持连接（登出 / 切登录页置 false，并阻止重连） */
    this.active = false
    /** 已连续重连次数（用于指数退避） */
    this.retry = 0
    /** @type {ReturnType<typeof setTimeout>|null} */
    this.reconnectTimer = null
    /** @type {ReturnType<typeof setInterval>|null} */
    this.pingTimer = null
    /** @type {Set<(data:object)=>void>} warning.created 订阅者 */
    this.listeners = new Set()
  }

  /** 是否已连接（OPEN） */
  get connected() {
    return !!this.ws && this.ws.readyState === WebSocket.OPEN
  }

  /**
   * 订阅 warning.created；返回取消订阅函数。
   * @param {(data:object)=>void} cb 回调（入参为事件载荷）
   * @returns {()=>void}
   */
  subscribe(cb) {
    this.listeners.add(cb)
    return () => this.listeners.delete(cb)
  }

  /**
   * 连接（幂等）。登录成功后调用。
   * @param {string} token 登录 JWT；为空则等价于 disconnect()
   */
  connect(token) {
    this.token = token || ''
    if (!this.token) {
      this.disconnect()
      return
    }
    this.active = true
    this._open()
  }

  /** 断开并停止重连（登出 / 切到登录页）。 */
  disconnect() {
    this.active = false
    this.retry = 0
    this._clearTimers()
    if (this.ws) {
      try {
        // 先摘回调，避免主动关闭触发 onclose 里的重连逻辑
        this.ws.onopen = null
        this.ws.onmessage = null
        this.ws.onclose = null
        this.ws.onerror = null
        this.ws.close()
      } catch (e) {
        /* 忽略关闭异常 */
      }
      this.ws = null
    }
  }

  /** 建立连接（内部）。 */
  _open() {
    if (!this.active || !this.token) return
    if (
      this.ws &&
      (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)
    ) {
      return
    }
    let url
    try {
      url = buildAlertsWsUrl(this.token)
    } catch (e) {
      this._scheduleReconnect()
      return
    }
    let socket
    try {
      socket = new WebSocket(url)
    } catch (e) {
      this._scheduleReconnect()
      return
    }
    this.ws = socket
    socket.onopen = () => {
      this.retry = 0
      this._startPing()
    }
    socket.onmessage = (ev) => this._onMessage(ev)
    socket.onclose = (ev) => {
      this._clearTimers()
      this.ws = null
      const code = ev && ev.code
      // 鉴权类关闭码：token 失效 / 用户被禁用 → 停止重连，等重新登录
      if (code === 4401 || code === 4403) {
        this.active = false
        return
      }
      this._scheduleReconnect()
    }
    socket.onerror = () => {
      // 浏览器 onerror 后必触发 onclose，统一在 onclose 里退避重连
    }
  }

  /** 指数退避重连（1→2→4→8→16→30s，封顶 30s）。 */
  _scheduleReconnect() {
    if (!this.active) return
    if (this.reconnectTimer) return
    const delay = Math.min(MAX_BACKOFF_SECONDS, Math.max(1, 2 ** this.retry))
    this.retry += 1
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this._open()
    }, delay * 1000)
  }

  /** 清理重连与心跳定时器。 */
  _clearTimers() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this._clearPing()
  }

  /** 启动客户端保活心跳。 */
  _startPing() {
    this._clearPing()
    this.pingTimer = setInterval(() => {
      if (this.connected) {
        try {
          this.ws.send(JSON.stringify({ type: 'ping' }))
        } catch (e) {
          /* 发送失败由 onclose 兜底重连 */
        }
      }
    }, CLIENT_PING_SECONDS * 1000)
  }

  /** 停止心跳。 */
  _clearPing() {
    if (this.pingTimer) {
      clearInterval(this.pingTimer)
      this.pingTimer = null
    }
  }

  /** 处理服务端帧。 */
  _onMessage(ev) {
    let frame
    try {
      frame = JSON.parse(ev.data)
    } catch (e) {
      return
    }
    if (!frame || typeof frame !== 'object') return
    const type = frame.type
    if (type === 'ping') {
      // 回 pong（保持对称，服务端不强制）
      if (this.connected) {
        try {
          this.ws.send(JSON.stringify({ type: 'pong' }))
        } catch (e) {
          /* 忽略 */
        }
      }
      return
    }
    if (type === 'warning.created') {
      this._emit(frame.data || {})
    }
    // hello / pong / 其它帧：忽略
  }

  /** 分发给订阅者；单个订阅者异常不影响其它。 */
  _emit(data) {
    for (const cb of Array.from(this.listeners)) {
      try {
        cb(data)
      } catch (e) {
        /* 订阅者异常不影响其它订阅者 */
      }
    }
  }
}

// 模块级单例（全应用共享一条连接）
const alertsWs = new AlertsWsManager()

export default alertsWs
