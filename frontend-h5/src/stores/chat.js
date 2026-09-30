import { defineStore } from 'pinia'
import { reactive } from 'vue'
import { showToast } from 'vant'

import * as chatApi from '@/api/chat'
import * as detectionApi from '@/api/detection'
import { ssePost } from '@/utils/sse'
import { useUserStore } from '@/stores/user'

/** 语义色 4 档：0 无 / 1 轻微 / 2 中等 / 3 严重（对齐 ui-design.md §2.1） */
export const SEVERITY_COLORS = ['#6B7B71', '#2BA471', '#F5A623', '#E5534B']

/** 「健康」展示色（绿色语义，仅前端展示映射；后端词表仍为「无」） */
export const HEALTHY_COLOR = '#2BA471'

/**
 * 由模型原始类名（如 `Tomato___Late_blight`）派生可读英文名。
 * 仅在后端 detection_context 缺失时作为兜底展示；中文名一律以后端为准。
 */
function prettifyClassName(label) {
  if (!label) return '未知病害'
  const tail = label.includes('___') ? label.split('___').slice(1).join('___') : label
  return tail.replace(/_/g, ' ').trim()
}

/**
 * 对话状态：会话列表、当前会话、消息、流式态、引用、检测上下文、快捷问题。
 */
export const useChatStore = defineStore('chat', {
  state: () => ({
    /** 会话列表 [{id,title,detection_id,updated_at}] */
    sessions: [],
    /** 当前会话 ID；为空表示尚未建会话 */
    currentSessionId: null,
    /** 消息列表 [{id,role,content,citations,created_at,streaming?}] */
    messages: [],
    /** 是否正在流式接收 */
    streaming: false,
    /** 后端是否降级（meta.degraded / error.degraded） */
    degraded: false,
    /** 检测上下文（DetectionContextOut 结构） */
    detectionContext: null,
    /**
     * 知识库是否缺该作物资料（meta.kb_scope_miss）。
     * §5 契约向后兼容新增字段：缺失（旧后端）时按 false 处理。
     */
    kbScopeMiss: false,
    /** 待注入的检测 ID：会话尚未建立时，走 /chat/ask 需带上它 */
    pendingDetectionId: null,
    /** 快捷问题（空态与引导使用） */
    quickQuestions: [
      '番茄叶子发黄怎么办？',
      '晚疫病怎么识别和防治？',
      '叶片上有褐色斑点是什么病？',
      '如何预防真菌性病害？',
    ],
    /** 最近一次错误信息 */
    lastError: '',
    /** 内部：当前 SSE AbortController */
    _controller: null,
  }),

  getters: {
    /** 是否已有消息 */
    hasMessages: (state) => state.messages.length > 0,
    /** 当前会话对象 */
    currentSession: (state) =>
      state.sessions.find((s) => s.id === state.currentSessionId) || null,
    /**
     * 缺资料提示条里的作物名（优先中文名，其次原始作物名）。
     * 无检测上下文时返回空串，由视图层回退为「该作物」。
     */
    scopeCropName: (state) => {
      const ctx = state.detectionContext
      if (!ctx) return ''
      return ctx.crop_cn || ctx.crop || ''
    },
  },

  actions: {
    /** 载入会话列表（首页/切换用） */
    async loadSessions() {
      try {
        const page = await chatApi.listSessions({ page: 1, page_size: 50 })
        this.sessions = (page && page.items) || []
      } catch (e) {
        // 错误已在 axios 拦截器 toast，这里只保证不崩
        this.sessions = []
      }
      return this.sessions
    },

    /**
     * 新建会话。
     * @param {number|null} detectionId 携带检测上下文
     * @returns {Promise<object|null>} 新建的会话
     */
    async createSession(detectionId = null) {
      try {
        const session = await chatApi.createSession(detectionId)
        this.currentSessionId = session.id
        this.messages = []
        this.kbScopeMiss = false
        await this.loadSessions()
        return session
      } catch (e) {
        return null
      }
    },

    /**
     * 打开已有会话：拉详情（含检测上下文）+ 消息（倒序反转为正序）。
     * @param {number} id
     */
    async openSession(id) {
      this.currentSessionId = id
      this.degraded = false
      this.lastError = ''
      this.kbScopeMiss = false
      this.pendingDetectionId = null
      this.detectionContext = null
      try {
        const detail = await chatApi.getSession(id)
        this.detectionContext = (detail && detail.detection_context) || null
      } catch (e) {
        this.detectionContext = null
      }
      try {
        const page = await chatApi.getMessages(id, { page: 1, page_size: 100 })
        const items = (page && page.items) || []
        // 后端倒序返回 → 前端反转为正序渲染
        this.messages = items
          .slice()
          .reverse()
          .map((m) => ({
            id: m.id,
            role: m.role,
            content: m.content || '',
            citations: m.citations || [],
            created_at: m.created_at,
            streaming: false,
          }))
      } catch (e) {
        this.messages = []
      }
    },

    /** 删除会话；若删除的是当前会话则清空当前状态 */
    async deleteSession(id) {
      try {
        await chatApi.deleteSession(id)
      } catch (e) {
        return false
      }
      this.sessions = this.sessions.filter((s) => s.id !== id)
      if (this.currentSessionId === id) {
        this.currentSessionId = null
        this.messages = []
        this.detectionContext = null
        this.degraded = false
        this.kbScopeMiss = false
      }
      return true
    },

    /**
     * 从检测详情进入：新建会话 → 取检测上下文（优先后端 detection_context，
     * 缺失时回退到 GET /detection/records/{id}）→ 追加一条本地概述消息。
     * @param {number} detectionId
     */
    async initForDetection(detectionId) {
      this.pendingDetectionId = detectionId
      const session = await this.createSession(detectionId)
      let ctx = null
      if (session) {
        try {
          const detail = await chatApi.getSession(session.id)
          ctx = (detail && detail.detection_context) || null
        } catch (e) {
          ctx = null
        }
      }
      if (!ctx) {
        ctx = await this.fetchDetectionContext(detectionId)
      }
      this.detectionContext = ctx
      // 会话已建立则可清除 pending（后续走 sessions 端点）
      if (this.currentSessionId != null) {
        this.pendingDetectionId = null
      }
      this.addDetectionGreeting()
      return ctx
    },

    /**
     * 兜底：直接查询检测记录并组装上下文卡片数据。
     * @param {number} detectionId
     * @returns {Promise<object|null>}
     */
    async fetchDetectionContext(detectionId) {
      try {
        const rec = await detectionApi.getDetectionRecord(detectionId)
        return {
          detection_id: rec.id,
          crop: rec.crop || null,
          crop_cn: null,
          disease_cn: prettifyClassName(rec.top_disease),
          class_name: rec.top_disease || null,
          severity_level: rec.severity_level,
          severity_label: rec.severity_label,
          top_conf: rec.top_conf,
          thumb_url: detectionApi.resolveStaticUrl(rec.annotated_url || rec.image_url),
        }
      } catch (e) {
        return null
      }
    },

    /** 本地追加一条检测结论概述（仅前端展示，不落库） */
    addDetectionGreeting() {
      const ctx = this.detectionContext
      if (!ctx) return
      const name = ctx.disease_cn || ctx.class_name || '该病害'
      const sev = ctx.severity_label || '未知'
      const conf = ctx.top_conf != null ? `${Math.round(ctx.top_conf * 100)}%` : '—'
      this.messages.push({
        id: `greet-${Date.now()}`,
        role: 'assistant',
        content: `本次检测到「${name}」（严重度：${sev}，置信度：${conf}）。您可以问我如何识别、如何防治，或描述田间的具体症状。`,
        citations: [],
        created_at: new Date().toISOString(),
        local: true,
        streaming: false,
      })
    },

    /**
     * 核心：发送问题 → 立即插入用户气泡与 AI 占位 → SSE 流式增量渲染。
     * - 已有会话：POST /chat/sessions/{id}/messages
     * - 无会话：POST /chat/ask（后端自动建会话，meta 带回 session_id）
     * @param {string} question
     */
    send(question) {
      const q = (question || '').trim()
      if (!q || this.streaming) return

      const userStore = useUserStore()

      // 1) 用户气泡（右侧绿色）
      this.messages.push({
        id: `u-${Date.now()}`,
        role: 'user',
        content: q,
        citations: [],
        created_at: new Date().toISOString(),
        streaming: false,
      })

      // 2) AI 占位气泡（左侧白色 + 打字光标）
      const placeholder = reactive({
        id: `a-${Date.now()}`,
        role: 'assistant',
        content: '',
        citations: [],
        created_at: new Date().toISOString(),
        streaming: true,
      })
      this.messages.push(placeholder)

      this.streaming = true
      this.degraded = false
      this.kbScopeMiss = false
      this.lastError = ''

      // 3) 选择端点
      const useSession = this.currentSessionId != null
      const url = useSession
        ? chatApi.messagesSseUrl(this.currentSessionId)
        : chatApi.askSseUrl()
      // 无会话时走 /chat/ask，并按需带上检测上下文
      const body = useSession
        ? { question: q }
        : this.pendingDetectionId != null
          ? { question: q, detection_id: this.pendingDetectionId }
          : { question: q }

      // 4) 发起 SSE（token 以 store 为准，兜底读 localStorage，避免 store 早于登录初始化）
      const token = userStore.token || localStorage.getItem('cd_token') || ''
      this._controller = ssePost(url, body, {
        token,
        onMeta: (data) => {
          if (!data) return
          if (data.session_id != null) {
            this.currentSessionId = data.session_id
          }
          if (Array.isArray(data.citations)) {
            placeholder.citations = data.citations
          }
          this.degraded = !!data.degraded
          // 向后兼容：旧后端无此字段时按 false 处理
          this.kbScopeMiss = !!data.kb_scope_miss
        },
        onDelta: (data) => {
          if (data && typeof data.text === 'string') {
            placeholder.content += data.text
          }
        },
        onDone: (data) => {
          placeholder.streaming = false
          if (data && data.assistant_message_id != null) {
            placeholder.id = data.assistant_message_id
          }
          this.streaming = false
          this._controller = null
          // 新会话产生后刷新会话列表（拿到标题/时间）
          if (useSession === false) {
            this.pendingDetectionId = null
            this.loadSessions()
          }
        },
        onError: (data) => {
          placeholder.streaming = false
          this.streaming = false
          this._controller = null
          const aborted = !!(data && data.aborted)
          if (aborted) {
            // 用户主动停止：保留已产出文本，不作错误提示
            if (!placeholder.content) {
              placeholder.content = '已停止生成。'
            }
            return
          }
          if (data && data.degraded) {
            this.degraded = true
          }
          // 保留已产出文本；若为空则用错误文案兜底
          if (!placeholder.content) {
            placeholder.content =
              (data && data.message) || '抱歉，服务暂时不可用，请稍后再试。'
          } else if (data && data.message) {
            // 已有部分内容：以 toast 提示，不覆盖正文
            showToast(data.message)
          }
          this.lastError = (data && data.message) || '服务异常'
        },
        onClose: () => {
          placeholder.streaming = false
          this.streaming = false
          this._controller = null
        },
      })
    },

    /** 停止生成（abort 当前 SSE） */
    stop() {
      if (this._controller) {
        this._controller.abort()
        this._controller = null
      }
      this.streaming = false
      const last = this.messages[this.messages.length - 1]
      if (last && last.streaming) {
        last.streaming = false
      }
    },

    /** 关闭检测上下文卡片 */
    clearDetectionContext() {
      this.detectionContext = null
    },

    /** 重置（登出时调用） */
    reset() {
      this.stop()
      this.sessions = []
      this.currentSessionId = null
      this.messages = []
      this.degraded = false
      this.detectionContext = null
      this.pendingDetectionId = null
      this.lastError = ''
    },
  },
})
