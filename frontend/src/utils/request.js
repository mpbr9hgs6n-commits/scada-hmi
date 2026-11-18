import { ElMessage } from 'element-plus'

export async function api(path, opts = {}) {
  const token = localStorage.getItem('token') || ''
  const headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {})
  if (token) headers['Authorization'] = 'Bearer ' + token
  const res = await fetch(path, {
    method: opts.method || 'GET',
    headers,
    body: opts.body ? JSON.stringify(opts.body) : undefined
  })
  const data = await res.json().catch(() => ({}))

  if (res.status === 401) {
    // 登录接口的 401 是"用户名或密码错误"，必须明确提示；
    // 只有带 token 的请求 401 才是会话失效，需要跳登录页。
    if (String(path).startsWith('/api/auth/login')) {
      const msg = data.detail || '用户名或密码错误'
      if (!opts.silent) ElMessage.error(msg)
      throw new Error(msg)
    }
    localStorage.removeItem('token')
    // 发布态/只读态（现场电视）不踢登录页——它们本来就没人登录，
    // 踢过去等于把 Kiosk 变成登录页，还不如显示空数据
    const keep = location.pathname.startsWith('/publish') || location.pathname.startsWith('/view/')
    if (!keep && !location.pathname.startsWith('/login')) location.href = '/login'
    throw new Error('未登录')
  }
  // 未改初始密码：后端一律 403，前端强制跳改密页
  if (res.status === 403 && data.detail === 'must_change_password') {
    if (!location.pathname.startsWith('/change-password')) location.href = '/change-password'
    throw new Error('must_change_password')
  }
  if (!res.ok) {
    if (!opts.silent) ElMessage.error(data.detail || ('请求失败 ' + res.status))
    throw new Error(data.detail || res.status)
  }
  return data
}

export const get = (p, o) => api(p, o)
export const post = (p, body, o) => api(p, Object.assign({ method: 'POST', body }, o))
export const put = (p, body, o) => api(p, Object.assign({ method: 'PUT', body }, o))
export const del = (p, o) => api(p, Object.assign({ method: 'DELETE' }, o))
