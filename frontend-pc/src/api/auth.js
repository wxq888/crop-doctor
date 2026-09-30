import request from './request'

/**
 * 管理员登录。
 * @param {string} username 登录名
 * @param {string} password 密码
 * @returns {Promise<{access_token:string,token_type:string,expires_in:number,user:object}>}
 */
export function login(username, password) {
  return request.post('/auth/login', { username, password })
}

/**
 * 获取当前登录用户资料（用于校验角色 / 刷新缓存）。
 * @returns {Promise<object>}
 */
export function getProfile() {
  return request.get('/auth/profile')
}
