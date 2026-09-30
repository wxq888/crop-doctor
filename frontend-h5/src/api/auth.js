import request from './request'

/**
 * 用户登录。
 * @param {string} username 登录名
 * @param {string} password 密码
 * @returns {Promise<{access_token:string,token_type:string,expires_in:number,user:object}>}
 */
export function login(username, password) {
  return request.post('/auth/login', { username, password })
}

/**
 * 用户注册。
 * @param {{username:string,password:string,nickname?:string,phone?:string}} payload
 * @returns {Promise<{id:number,username:string,role:string}>}
 */
export function register(payload) {
  return request.post('/auth/register', payload)
}

/**
 * 获取当前登录用户资料。
 * @returns {Promise<object>}
 */
export function getProfile() {
  return request.get('/auth/profile')
}

/**
 * 更新当前用户资料（昵称 / 头像）。
 * @param {{nickname?:string,avatar?:string}} payload
 */
export function updateProfile(payload) {
  return request.put('/auth/profile', payload)
}

/**
 * 修改密码。
 * @param {{old_password:string,new_password:string}} payload
 */
export function changePassword(payload) {
  return request.put('/auth/password', payload)
}
