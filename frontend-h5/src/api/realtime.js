/**
 * 实时检测 WS 连接工具。
 *
 * 端点：`WS /api/v1/detection/ws/realtime?token=<jwt>`（任何已登录用户可用）。
 * 浏览器 WebSocket 无法自定义请求头，token 走 query 参数（与 monitor WS 一致）；
 * 服务端 accept-first 鉴权，失败按 close code 关闭：
 *   4401 未登录/token 无效 · 4403 单帧超限 · 4503 模型未就绪。
 */

// 与 api/request.js 同源的后端地址（http://host/api/v1）
const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api/v1'

/**
 * 构造实时检测 WS 完整 URL。
 * @param {string} token 登录 JWT（可空，空时由服务端 close 4401）
 * @returns {string} ws(s)://host/api/v1/detection/ws/realtime?token=xxx
 */
export function buildRealtimeWsUrl(token) {
  const base = API_BASE.replace(/^http/, 'ws').replace(/\/+$/, '')
  const url = new URL(`${base}/detection/ws/realtime`)
  if (token) url.searchParams.set('token', token)
  return url.toString()
}

/** 二进制帧协议：4 字节大端 frame_id + JPEG（与后端 _split_frame_payload 约定一致） */
export const JPEG_MAGIC_PREFIX_BYTES = 4

/**
 * 把 JPEG blob 打包为 WS 二进制帧（frame_id 前缀 + JPEG）。
 * @param {ArrayBuffer} jpegBuf JPEG 字节流
 * @param {number} frameId 帧序号（uint32）
 * @returns {Uint8Array}
 */
export function packFrame(jpegBuf, frameId) {
  const out = new Uint8Array(JPEG_MAGIC_PREFIX_BYTES + jpegBuf.byteLength)
  new DataView(out.buffer).setUint32(0, frameId >>> 0)
  out.set(new Uint8Array(jpegBuf), JPEG_MAGIC_PREFIX_BYTES)
  return out
}
