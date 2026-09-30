import { defineStore } from 'pinia'

import * as authApi from '@/api/auth'

// 本地存储键（与 router/index.js、api/request.js 保持一致）
export const TOKEN_KEY = 'cd_token'
export const USER_KEY = 'cd_user'

/** 从 localStorage 读取缓存的用户信息（容错） */
function readCachedUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch (e) {
    return null
  }
}

/**
 * 用户状态：登录态（token / user）与登录、注册、登出动作。
 */
export const useUserStore = defineStore('user', {
  state: () => ({
    /** JWT access token，初始从 localStorage 恢复 */
    token: localStorage.getItem(TOKEN_KEY) || '',
    /** 当前用户信息（含 nickname / avatar / role） */
    user: readCachedUser(),
  }),

  getters: {
    /** 是否已登录 */
    isLoggedIn: (state) => !!state.token,
    /** 展示名：昵称优先，其次用户名 */
    displayName: (state) =>
      (state.user && (state.user.nickname || state.user.username)) || '农户',
    /** 是否管理员 */
    isAdmin: (state) => !!state.user && state.user.role === 'admin',
  },

  actions: {
    /**
     * 写入 / 清除登录态（token + user 同步 localStorage）。
     * @param {string} token
     * @param {object|null} user
     */
    setAuth(token, user) {
      this.token = token || ''
      this.user = user || null
      if (this.token) {
        localStorage.setItem(TOKEN_KEY, this.token)
      } else {
        localStorage.removeItem(TOKEN_KEY)
      }
      if (this.user) {
        localStorage.setItem(USER_KEY, JSON.stringify(this.user))
      } else {
        localStorage.removeItem(USER_KEY)
      }
    },

    /**
     * 登录：调用 POST /auth/login，成功后持久化 token + user。
     * @param {string} username
     * @param {string} password
     * @returns {Promise<object>} 登录返回数据
     */
    async login(username, password) {
      const data = await authApi.login(username, password)
      this.setAuth(data.access_token, data.user)
      return data
    },

    /**
     * 注册：调用 POST /auth/register（不自动登录，由页面决定后续动作）。
     * @param {{username:string,password:string,nickname?:string,phone?:string}} payload
     * @returns {Promise<object>}
     */
    async register(payload) {
      return authApi.register(payload)
    },

    /**
     * 拉取当前用户资料并刷新缓存。
     * @returns {Promise<object>}
     */
    async loadProfile() {
      const user = await authApi.getProfile()
      this.user = user
      localStorage.setItem(USER_KEY, JSON.stringify(user))
      return user
    },

    /** 登出：清空本地登录态 */
    logout() {
      this.setAuth('', null)
    },
  },
})
