<template>
  <div class="cd-rt">
    <!-- 相机铺底 -->
    <video ref="videoEl" class="cd-rt__video" playsinline muted autoplay></video>
    <!-- 检测框叠加层（透明 canvas，绝对定位） -->
    <canvas ref="overlayEl" class="cd-rt__overlay"></canvas>
    <!-- 抓帧用隐藏画布 -->
    <canvas ref="captureEl" class="cd-rt__hidden" />

    <!-- 顶部栏 -->
    <div class="cd-rt__top">
      <van-icon name="arrow-left" class="cd-rt__back" @click="goBack" />
      <span class="cd-rt__title">摄像头实时检测</span>
      <span class="cd-rt__status" :class="`cd-rt__status--${statusLevel}`">{{ statusText }}</span>
    </div>

    <!-- 底部控制区 -->
    <div class="cd-rt__panel">
      <div class="cd-rt__result" v-if="running && lastLabel">
        <span class="cd-rt__result-name">{{ lastLabel }}</span>
        <span class="cd-rt__result-conf" v-if="lastConf !== null">{{ (lastConf * 100).toFixed(0) }}%</span>
      </div>
      <div class="cd-rt__tip">
        <van-icon name="info-o" />
        实时结果仅供参考，请以拍摄检测为准
      </div>

      <div v-if="errorMsg" class="cd-rt__error">
        <span class="cd-rt__error-text">{{ errorMsg }}</span>
        <van-button size="small" round type="primary" class="cd-rt__retry" @click="retry">重试</van-button>
      </div>

      <van-button
        round
        block
        :type="running ? 'default' : 'primary'"
        class="cd-rt__btn"
        :loading="starting"
        loading-text="启动中…"
        @click="running ? stopAll() : start()"
      >
        {{ running ? '停止检测' : '开始实时检测' }}
      </van-button>
    </div>
  </div>
</template>

<script setup>
import { computed, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { buildRealtimeWsUrl, packFrame } from '@/api/realtime'

/**
 * 摄像头实时检测页（architecture.md §2.1 首页 · 实时检测）：
 * getUserMedia 后置摄像头 → 隐藏 canvas 抓帧（~2.5fps）→ WS 二进制发送 →
 * frame.result 按比例映射画到叠加 canvas。离开页面必须释放全部资源。
 */
const router = useRouter()

// ===== 常量 =====
const TOKEN_KEY = 'cd_token'
const CAPTURE_INTERVAL_MS = 400 // ~2.5fps，后端 CPU 推理单帧数百 ms，过高只会被 skip
const JPEG_QUALITY = 0.7
const DEFAULT_CONF = 0.25
const RECONNECT_BASE_MS = 1000 // 指数退避：1s → 2s → 4s … 上限 10s
const RECONNECT_MAX_MS = 10000
const BRAND_GREEN = '#2ba471'

// ===== 响应式状态 =====
const videoEl = ref(null)
const overlayEl = ref(null)
const captureEl = ref(null)
const running = ref(false)
const starting = ref(false)
const errorMsg = ref('')
const wsState = ref('idle') // idle | connecting | open | closed
const lastLabel = ref('')
const lastConf = ref(null)
/** 未绘制任何框时的最近一次「未检出」提示时间戳（避免闪烁，略） */
const lastResultAt = ref(0)

// ===== 非响应式资源句柄（泄漏即事故，onUnmounted 全量回收）=====
let stream = null // MediaStream
let ws = null // WebSocket
let captureTimer = null // 抓帧 setInterval
let reconnectTimer = null // 重连 setTimeout
let reconnectAttempts = 0
let manualStop = false // 用户主动停止 → 不再自动重连
let frameId = 0
let lastFrameW = 0 // 最近发送帧的原始分辨率（bbox 映射基准）
let lastFrameH = 0
/** 释放证据（供 QA 断言）：离开页面后 tracks / ws / timer 状态 */
const releaseLog = { tracksStopped: 0, wsClosed: false, timerCleared: false }

const statusLevel = computed(() => {
  if (!running.value) return 'idle'
  if (wsState.value === 'open') return 'live'
  return 'connecting'
})

const statusText = computed(() => {
  if (!running.value) return '未开始'
  if (wsState.value === 'open') return '实时检测中'
  if (wsState.value === 'connecting') return '连接服务…'
  return '重连中…'
})

// ===== 相机 =====

/** 请求后置摄像头；失败时给出可操作的错误提示 */
async function openCamera() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    throw new Error('当前浏览器不支持摄像头访问')
  }
  stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } },
    audio: false,
  })
  videoEl.value.srcObject = stream
  try {
    await videoEl.value.play()
  } catch (e) {
    // 自动播放被拦截时可忽略：用户点击画面后即可播放
  }
}

/** 停止所有相机 track 并解绑 */
function closeCamera() {
  if (stream) {
    stream.getTracks().forEach((t) => {
      try {
        t.stop()
        releaseLog.tracksStopped += 1
      } catch (e) {
        /* 忽略单个 track 停止失败 */
      }
    })
    stream = null
  }
  if (videoEl.value) videoEl.value.srcObject = null
}

// ===== WebSocket =====

function connectWs() {
  if (manualStop) return
  wsState.value = 'connecting'
  const token = localStorage.getItem(TOKEN_KEY) || ''
  let socket
  try {
    socket = new WebSocket(buildRealtimeWsUrl(token))
  } catch (e) {
    scheduleReconnect()
    return
  }
  socket.binaryType = 'arraybuffer'
  ws = socket

  socket.onopen = () => {
    if (ws !== socket) return // 已被新连接替换
    wsState.value = 'open'
    reconnectAttempts = 0
    errorMsg.value = ''
    // 首帧 JSON 消息：置信度阈值（服务端默认 0.25）
    try {
      socket.send(JSON.stringify({ type: 'config', conf: DEFAULT_CONF }))
    } catch (e) {
      /* 发送失败交由 onclose 处理 */
    }
  }

  socket.onmessage = (ev) => {
    if (typeof ev.data !== 'string') return
    let msg
    try {
      msg = JSON.parse(ev.data)
    } catch (e) {
      return
    }
    if (msg.type === 'frame.result') {
      handleResult(msg.data || {})
    } else if (msg.type === 'error') {
      errorMsg.value = (msg.data && msg.data.message) || '服务异常，请稍后重试'
    }
    // ping / pong / frame.skipped：静默
  }

  socket.onclose = (ev) => {
    if (ws !== socket) return
    wsState.value = 'closed'
    ws = null
    if (!manualStop && running.value) {
      // 4401 未登录：跳登录页；其余断开指数退避自动重连
      if (ev && ev.code === 4401) {
        running.value = false
        closeCamera()
        stopCaptureTimer()
        router.push({ name: 'login', query: { redirect: '/realtime' } })
        return
      }
      scheduleReconnect()
    }
  }

  socket.onerror = () => {
    /* 错误细节由 onclose 统一处理 */
  }
}

/** 指数退避重连（页面存活且非手动停止时） */
function scheduleReconnect() {
  if (manualStop || reconnectTimer || !running.value) return
  const delay = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** reconnectAttempts)
  reconnectAttempts += 1
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    if (running.value && !manualStop) connectWs()
  }, delay)
}

function closeWs() {
  if (ws) {
    const socket = ws
    ws = null
    try {
      socket.close(1000, 'client stop')
    } catch (e) {
      /* 已断开时 close 可能抛错，忽略 */
    }
    releaseLog.wsClosed = true
  }
  wsState.value = 'idle'
}

// ===== 抓帧与绘制 =====

function startCaptureTimer() {
  stopCaptureTimer()
  captureTimer = setInterval(captureOnce, CAPTURE_INTERVAL_MS)
}

function stopCaptureTimer() {
  if (captureTimer) {
    clearInterval(captureTimer)
    captureTimer = null
    releaseLog.timerCleared = true
  }
}

/** 抓一帧：video → 隐藏 canvas → JPEG → WS 二进制（frame_id 前缀） */
function captureOnce() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return
  const v = videoEl.value
  const c = captureEl.value
  if (!v || !c || !v.videoWidth) return

  c.width = v.videoWidth
  c.height = v.videoHeight
  c.getContext('2d').drawImage(v, 0, 0)
  lastFrameW = c.width
  lastFrameH = c.height

  c.toBlob(
    (blob) => {
      if (!blob || !ws || ws.readyState !== WebSocket.OPEN) return
      blob.arrayBuffer().then((buf) => {
        if (!ws || ws.readyState !== WebSocket.OPEN) return
        frameId = (frameId + 1) % 0xffffffff
        try {
          ws.send(packFrame(buf, frameId))
        } catch (e) {
          /* 发送失败由 onclose 兜底 */
        }
      })
    },
    'image/jpeg',
    JPEG_QUALITY,
  )
}

/** 收到 frame.result：把原始分辨率 bbox 映射到叠加 canvas 并画框 */
function handleResult(data) {
  lastResultAt.value = Date.now()
  const overlay = overlayEl.value
  if (!overlay || !lastFrameW || !lastFrameH) return

  // 叠加 canvas 尺寸与显示区一致（cover 铺满）
  syncOverlaySize()
  const ctx = overlay.getContext('2d')
  ctx.clearRect(0, 0, overlay.width, overlay.height)

  const boxes = data.boxes || []
  if (!boxes.length) {
    lastLabel.value = '未检出目标'
    lastConf.value = null
    return
  }

  // object-fit: cover 的坐标映射：等比放大取 max，居中裁切
  const scale = Math.max(overlay.width / lastFrameW, overlay.height / lastFrameH)
  const dx = (overlay.width - lastFrameW * scale) / 2
  const dy = (overlay.height - lastFrameH * scale) / 2

  ctx.lineWidth = 2.5
  ctx.font = '12px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif'
  boxes.forEach((b) => {
    const [x1, y1, x2, y2] = b.bbox
    const bx = x1 * scale + dx
    const by = y1 * scale + dy
    const bw = (x2 - x1) * scale
    const bh = (y2 - y1) * scale

    // 框线：品牌绿
    ctx.strokeStyle = BRAND_GREEN
    ctx.strokeRect(bx, by, bw, bh)

    // 标签：中文病名 + 置信度（框上方绿底白字）
    const text = `${b.label_cn || b.label} ${(b.conf * 100).toFixed(0)}%`
    const tw = ctx.measureText(text).width + 10
    const th = 18
    const ty = by > th + 4 ? by - th - 2 : by + 2
    ctx.fillStyle = BRAND_GREEN
    ctx.fillRect(bx, ty, tw, th)
    ctx.fillStyle = '#fff'
    ctx.fillText(text, bx + 5, ty + 13)
  })

  const top = boxes[0]
  lastLabel.value = top.label_cn || top.label
  lastConf.value = typeof top.conf === 'number' ? top.conf : null
}

/** 叠加 canvas 尺寸对齐显示区（启动与窗口变化时调用） */
function syncOverlaySize() {
  const overlay = overlayEl.value
  if (!overlay || !overlay.parentElement) return
  const { clientWidth, clientHeight } = overlay.parentElement
  if (overlay.width !== clientWidth || overlay.height !== clientHeight) {
    overlay.width = clientWidth
    overlay.height = clientHeight
  }
}

// ===== 生命周期控制 =====

/** 开始：开相机 → 连 WS → 起抓帧循环 */
async function start() {
  if (running.value || starting.value) return
  starting.value = true
  errorMsg.value = ''
  manualStop = false
  lastLabel.value = ''
  lastConf.value = null
  try {
    await openCamera()
    syncOverlaySize()
    running.value = true
    connectWs()
    startCaptureTimer()
  } catch (e) {
    errorMsg.value =
      (e && e.name === 'NotAllowedError')
        ? '相机权限被拒绝，请在浏览器设置中允许后重试'
        : (e && e.message) || '相机启动失败，请重试'
    closeCamera()
  } finally {
    starting.value = false
  }
}

/** 全量停止：抓帧 → WS → 相机 → 叠加层（幂等，可重复调用） */
function stopAll() {
  manualStop = true
  running.value = false
  stopCaptureTimer()
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  closeWs()
  closeCamera()
  const overlay = overlayEl.value
  if (overlay) {
    const ctx = overlay.getContext('2d')
    ctx && ctx.clearRect(0, 0, overlay.width, overlay.height)
  }
  wsState.value = 'idle'
}

/** 错误态重试：先全量停，再重新开始 */
function retry() {
  stopAll()
  manualStop = false
  start()
}

function goBack() {
  router.back()
}

onUnmounted(() => {
  stopAll()
  window.removeEventListener('resize', syncOverlaySize)
  // 释放证据挂到 window（QA 断言用；不影响业务）
  window.__cdRtRelease = { ...releaseLog, at: Date.now() }
})

// 窗口尺寸变化时同步叠加层（与 onUnmounted 的 removeEventListener 成对）
window.addEventListener('resize', syncOverlaySize)
</script>

<style scoped>
/* 固定视口高度：相机页满屏，不随 body 滚动（100vh 回退 + 100dvh） */
.cd-rt {
  position: relative;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
  background: #0c1512;
}

.cd-rt__video {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.cd-rt__overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.cd-rt__hidden {
  display: none;
}

/* 顶部栏（悬浮在相机上） */
.cd-rt__top {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  padding-top: calc(12px + env(safe-area-inset-top));
  background: linear-gradient(180deg, rgba(0, 0, 0, 0.55), rgba(0, 0, 0, 0));
  color: #fff;
  z-index: 3;
}

.cd-rt__back {
  font-size: 20px;
  padding: 4px;
  cursor: pointer;
}

.cd-rt__title {
  flex: 1;
  font: var(--font-h2);
  color: #fff;
}

.cd-rt__status {
  font: var(--font-mini);
  padding: 2px 10px;
  border-radius: var(--radius-button);
  background: rgba(255, 255, 255, 0.18);
}

.cd-rt__status--live {
  background: rgba(43, 164, 113, 0.85);
}

.cd-rt__status--connecting {
  background: rgba(245, 166, 35, 0.85);
}

/* 底部控制区（悬浮面板） */
.cd-rt__panel {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 3;
  padding: 14px 16px calc(14px + env(safe-area-inset-bottom));
  background: linear-gradient(0deg, rgba(0, 0, 0, 0.65), rgba(0, 0, 0, 0));
}

.cd-rt__result {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 8px;
  color: #fff;
}

.cd-rt__result-name {
  font: var(--font-h2);
  font-weight: 600;
}

.cd-rt__result-conf {
  font: var(--font-caption);
  color: rgba(255, 255, 255, 0.8);
}

/* 免责提示（适老化：常驻显著） */
.cd-rt__tip {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 12px;
  padding: 8px 10px;
  border-radius: 10px;
  background: rgba(255, 246, 230, 0.92);
  border-left: 3px solid var(--severity-2);
  color: #8a5a00;
  font: var(--font-mini);
}

.cd-rt__error {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding: 8px 10px;
  border-radius: 10px;
  background: rgba(229, 83, 75, 0.92);
  color: #fff;
  font: var(--font-mini);
}

.cd-rt__error-text {
  flex: 1;
}

.cd-rt__retry {
  flex: 0 0 auto;
  color: var(--color-primary);
}

.cd-rt__btn {
  height: 48px;
  border-radius: var(--radius-button);
  font-size: 16px;
  font-weight: 600;
}

.cd-rt__btn[type='primary'] {
  background: var(--gradient-brand-135);
  border: none;
}
</style>
