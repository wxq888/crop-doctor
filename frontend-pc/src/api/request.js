import axios from 'axios'
import { ElMessage } from 'element-plus'

// 本地存储键（与 router/index.js、stores/user.js 保持一致；PC 与 H5 隔离）
const TOKEN_KEY = 'cd_pc_token'
const USER_KEY = 'cd_pc_user'

/** 后端错误码：未登录 / Token 无效或过期（见 impl-backend-v1 §5.3） */
const CODE_UNAUTHORIZED = 1003

/**
 * 统一 axios 实例。
 * - baseURL 取自 VITE_API_BASE_URL（如 http://127.0.0.1:8000/api/v1）
 * - 请求拦截：自动注入 `Authorization: Bearer <token>`
 * - 响应拦截：解开 `{code, message, data}` 信封，成功直接返回 data
 * - 业务错误：code=1003（未登录/过期）清 token 并跳登录；其余 ElMessage 提示
 */
const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 30000,
})

/** 清除本地登录态并跳转登录页（hash 路由） */
function redirectToLogin(message) {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  if (!window.location.hash.includes('/login')) {
    window.location.hash = '#/login'
  }
  if (message) {
    ElMessage.error(message)
  }
}

/**
 * 统一处理业务错误码。
 * @param {number} code 业务错误码
 * @param {string} message 后端返回的面向用户的消息
 */
function handleBusinessError(code, message) {
  if (code === CODE_UNAUTHORIZED) {
    redirectToLogin(message || '登录已过期，请重新登录')
    return
  }
  ElMessage.error(message || '请求失败')
}

request.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem(TOKEN_KEY)
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

request.interceptors.response.use(
  (response) => {
    const body = response.data
    // 非信封响应（如二进制流）原样返回
    if (!body || typeof body !== 'object' || !('code' in body)) {
      return body
    }
    if (body.code === 0) {
      return body.data
    }
    // 业务失败（HTTP 200 但 code != 0）
    handleBusinessError(body.code, body.message)
    const err = new Error(body.message || '请求失败')
    err.code = body.code
    err.data = body.data
    return Promise.reject(err)
  },
  (error) => {
    const resp = error.response
    if (resp && resp.data && typeof resp.data === 'object' && 'code' in resp.data) {
      handleBusinessError(resp.data.code, resp.data.message)
      const err = new Error(resp.data.message || '请求失败')
      err.code = resp.data.code
      err.data = resp.data.data
      return Promise.reject(err)
    }
    ElMessage.error((error && error.message) || '网络异常')
    return Promise.reject(error)
  },
)

export default request
