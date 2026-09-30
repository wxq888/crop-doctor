import { defineStore } from 'pinia'

import { wsClient } from '@/utils/ws'
import { getRecentEvents } from '@/api/monitor'
import { useUserStore } from '@/stores/user'

/** WS 地址（见 .env.development §7.1） */
const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL
/** 事件环形缓冲上限（见 §7.6） */
const MAX_EVENTS = 50

/** 取消订阅句柄（模块级，防止热更新重复绑定） */
let bound = false
let unsubs = []

/** 事件类型 → 语义色分类（绿=检测 / 红=预警 / 琥珀=工单） */
export const EVENT_KIND = {
  'detection.created': 'detection',
  'warning.created': 'warning',
  'feedback.created': 'feedback',
  'feedback.replied': 'feedback',
}

/**
 * 监控大屏实时状态：WS 连接态 + 事件环形缓冲 + 增量计数。
 * WS 仅承载事件流与增量计数；聚合数据由 REST 轮询（见 §7.6）。
 */
export const useMonitorStore = defineStore('monitor', {
  state: () => ({
    /** WS 是否已连接（驱动「● LIVE」） */
    connected: false,
    /** 事件环形缓冲（最新在首位） */
    events: [],
    /** 本次会话内检测增量（叠加到今日检测卡） */
    detectionDelta: 0,
    /** 本次会话内预警增量 */
    warningDelta: 0,
    /** 本次会话内工单增量 */
    feedbackDelta: 0,
  }),

  getters: {
    /** 最近一条事件 */
    latestEvent: (state) => state.events[0] || null,
  },

  actions: {
    /**
     * 建立 WS 连接并绑定事件处理（幂等，仅首次真正绑定）。
     */
    connect() {
      const userStore = useUserStore()
      if (!userStore.token) return
      this._bindHandlers()
      wsClient.connect(WS_BASE_URL, userStore.token)
    },

    /** 主动断开（登出 / 离开大屏）：关闭连接并解绑事件，允许下次登录重新绑定 */
    disconnect() {
      wsClient.close()
      this.connected = false
      unsubs.forEach((fn) => fn && fn())
      unsubs = []
      bound = false
    },

    /** 清空缓冲与增量（登出时） */
    reset() {
      this.events = []
      this.detectionDelta = 0
      this.warningDelta = 0
      this.feedbackDelta = 0
    },

    /**
     * 拉取快照兜底补拉（重连后 / 首屏）。
     */
    async pullRecent() {
      try {
        const data = await getRecentEvents(MAX_EVENTS)
        const items = (data && data.items) || []
        // 快照为时间倒序（最新在前），直接作为初始缓冲
        if (items.length && this.events.length === 0) {
          this.events = items.slice(0, MAX_EVENTS)
        }
      } catch (e) {
        // 补拉失败不影响实时链路
      }
    },

    /** 内部：绑定 WS 事件（幂等） */
    _bindHandlers() {
      if (bound) return
      bound = true
      unsubs = [
        wsClient.on('status', (ok) => {
          this.connected = ok
          if (ok) {
            // 重连成功：快照兜底补拉
            this.pullRecent()
          }
        }),
        wsClient.on('message', (raw) => this._handleFrame(raw)),
      ]
    },

    /** 内部：处理单帧（信封 {v,type,ts,data}） */
    _handleFrame(raw) {
      let msg
      try {
        msg = JSON.parse(raw)
      } catch (e) {
        return
      }
      if (!msg || typeof msg !== 'object') return

      // 心跳：服务端 ping → 回 pong；pong 忽略
      if (msg.type === 'ping') {
        wsClient.send({ type: 'pong' })
        return
      }
      if (msg.type === 'pong') return

      // 握手：hello（含 recent 最近事件）
      if (msg.type === 'hello') {
        const recent = (msg.data && msg.data.recent) || []
        if (recent.length && this.events.length === 0) {
          this.events = recent.slice(0, MAX_EVENTS)
        }
        return
      }

      // 业务事件
      if (EVENT_KIND[msg.type]) {
        this._pushEvent(msg)
      }
    },

    /** 内部：插入事件（置顶 + 环形截断 + 增量计数） */
    _pushEvent(msg) {
      const kind = EVENT_KIND[msg.type]
      const evt = {
        id: `${msg.type}-${msg.ts}-${Math.random().toString(36).slice(2, 8)}`,
        type: msg.type,
        kind,
        ts: msg.ts,
        data: msg.data || {},
      }
      this.events.unshift(evt)
      if (this.events.length > MAX_EVENTS) {
        this.events.length = MAX_EVENTS
      }
      if (kind === 'detection') this.detectionDelta += 1
      else if (kind === 'warning') this.warningDelta += 1
      else if (kind === 'feedback') this.feedbackDelta += 1
    },
  },
})
