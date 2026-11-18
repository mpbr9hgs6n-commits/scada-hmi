// 视频流播放地址（03 整改）
// token 由后端按 stream 签发，默认 5 分钟有效；这里做缓存 + 临期自动续签。
// 注意：token 只能放在 URL 的 query 上（ZLM hook 从 params 里读），
// 不要试图放 header —— flv.js 发出的请求是 ZLM 直接处理的，header 到不了 hook。
import { get } from './request'

const cache = new Map()   // stream -> { token, exp }

export async function liveUrl(stream, force = false) {
  if (!stream) return ''
  const now = Math.floor(Date.now() / 1000)
  let c = cache.get(stream)
  if (force || !c || c.exp - now < 60) {
    try {
      const r = await get('/api/video/token?stream=' + encodeURIComponent(stream))
      c = { token: r.token, exp: r.exp }
      cache.set(stream, c)
    } catch (e) {
      return ''
    }
  }
  return `/live/${stream}.live.flv?token=${encodeURIComponent(c.token)}`
}

export function clearLiveToken(stream) {
  if (stream) cache.delete(stream)
  else cache.clear()
}
