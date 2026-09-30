/**
 * POST 版 SSE 读取器。
 *
 * 为什么不用 EventSource：`EventSource` 只支持 GET，且无法携带 `Authorization` 头；
 * 而 chat 接口是 **POST + Bearer + JSON body** 的 SSE，故必须用 `fetch` +
 * `ReadableStream` 手动解析（design §9.3）。
 *
 * 事件契约（前后端冻结，不可改；字段可向后兼容新增）：
 *   event: meta   → 首帧，携带 session_id / citations / degraded / kb_scope_miss
 *                   （kb_scope_miss 为 §5 向后兼容新增：true 表示该作物在知识库中无任何文档；
 *                    旧后端可能不含此字段，调用方需按 false 处理）
 *   event: delta  → 增量文本 {text}，0..N 帧
 *   event: done   → 末帧，携带 assistant_message_id / finish_reason
 *   event: error  → 末帧（替代 done），携带 code / message / degraded
 *   心跳：注释行 `: ping`（每 15s），解析时忽略
 *
 * @param {string} url 完整 SSE 端点 URL
 * @param {object} body 请求体（JSON 序列化）
 * @param {{
 *   token?:string,
 *   onOpen?:Function,
 *   onMeta?:(data:object)=>void,
 *   onDelta?:(data:object)=>void,
 *   onDone?:(data:object)=>void,
 *   onError?:(data:object)=>void,
 *   onClose?:(info:object)=>void
 * }} handlers 回调集合
 * @returns {AbortController} 传入控制器以便「停止生成」时 abort()
 */
export function ssePost(url, body, handlers = {}) {
  const { token, onOpen, onMeta, onDelta, onDone, onError, onClose } = handlers
  const controller = new AbortController()

  // 一个帧最多触发一次终态回调
  let settled = false
  const settle = (type, data) => {
    if (settled) return
    settled = true
    if (type === 'done') onDone && onDone(data || {})
    else if (type === 'error') onError && onError(data || {})
  }

  const run = async () => {
    try {
      const resp = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body || {}),
        signal: controller.signal,
      })

      // 非 200：后端可能返回统一 JSON 信封（如 4001/4003）
      if (!resp.ok) {
        let code = resp.status
        let message = `请求失败（HTTP ${resp.status}）`
        try {
          const j = await resp.json()
          if (j && typeof j.code === 'number') code = j.code
          if (j && j.message) message = j.message
        } catch (e) {
          /* 非 JSON 响应，保留默认文案 */
        }
        settle('error', { code, message })
        onClose && onClose({ ok: false })
        return
      }

      if (!resp.body) {
        settle('error', { code: 9000, message: '当前浏览器不支持流式响应' })
        onClose && onClose({ ok: false })
        return
      }

      onOpen && onOpen()

      const reader = resp.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      // 逐块读取 → 按 \n\n 分帧 → 解析 event/data
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        let idx = buffer.indexOf('\n\n')
        while (idx !== -1) {
          const rawFrame = buffer.slice(0, idx)
          buffer = buffer.slice(idx + 2)
          const frame = parseFrame(rawFrame)
          if (frame) {
            if (frame.type === 'meta') onMeta && onMeta(frame.data)
            else if (frame.type === 'delta') onDelta && onDelta(frame.data)
            else if (frame.type === 'done') settle('done', frame.data)
            else if (frame.type === 'error') settle('error', frame.data)
          }
          idx = buffer.indexOf('\n\n')
        }
      }

      // 流自然结束但无终态帧：兜底触发 onClose 让调用方收敛 UI
      onClose && onClose({ ok: true })
    } catch (err) {
      if (err && err.name === 'AbortError') {
        // 用户主动「停止生成」
        settle('error', { code: 0, message: '', aborted: true })
        onClose && onClose({ ok: false, aborted: true })
        return
      }
      settle('error', { code: 9000, message: (err && err.message) || '网络异常，请稍后重试' })
      onClose && onClose({ ok: false })
    }
  }

  run()

  return controller
}

/**
 * 解析单个 SSE 帧文本 → `{ type, data }`。
 * 支持 `event:` / `data:` 行，忽略 `:` 注释行（心跳）与空行；data 尝试 JSON.parse。
 * @param {string} raw 单帧原始文本（不含帧尾空行）
 * @returns {{type:string,data:any}|null}
 */
function parseFrame(raw) {
  const lines = raw.split('\n')
  let type = 'message'
  const dataLines = []

  for (const line of lines) {
    if (!line) continue
    if (line.startsWith(':')) continue // 心跳/注释行
    if (line.startsWith('event:')) {
      type = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      // SSE 规范：去掉 `data:` 后的一个可选前导空格
      dataLines.push(line.slice(5).replace(/^ /, ''))
    }
  }

  if (dataLines.length === 0) return null

  const rawData = dataLines.join('\n')
  let data = rawData
  try {
    data = JSON.parse(rawData)
  } catch (e) {
    // 非 JSON 的 data 原样返回
  }
  return { type, data }
}
