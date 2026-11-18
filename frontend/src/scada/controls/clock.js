// 全局时钟（P6）——所有时钟控件共用一个定时器
//
// 任务书：「用一个全局定时器广播时间，不要让每个时钟各自 setInterval」。
// 一张画面挂 6 个时钟 = 6 个 timer，一屏 20 个控件就是 20 个 timer，
// 每个都独立漂移，秒针还会不同步。这里只有一个 1s 定时器，
// 引用计数归零就自动停（切走画面不留后台定时器）。
import { reactive } from 'vue'

export const clock = reactive({ t: Date.now(), n: 0 })

let timer = 0
let refs = 0

function tick() {
  clock.t = Date.now()
  clock.n++
}

export function acquireClock() {
  refs++
  if (!timer) {
    clock.t = Date.now()
    timer = setInterval(tick, 1000)
  }
}

export function releaseClock() {
  refs = Math.max(0, refs - 1)
  if (refs === 0 && timer) {
    clearInterval(timer)
    timer = 0
  }
}

// 时区格式化：不依赖浏览器 locale（现场机器可能是英文系统/UTC）
export function fmtTime(ms, format = 'HH:mm:ss', tz = 'Asia/Shanghai') {
  const d = new Date(ms || Date.now())
  let parts
  try {
    const f = new Intl.DateTimeFormat('en-CA', {
      timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    })
    parts = {}
    for (const p of f.formatToParts(d)) parts[p.type] = p.value
    if (parts.hour === '24') parts.hour = '00'
  } catch (e) {
    // 浏览器不支持该时区（极老内核）：退回本地时间，不能因此不显示
    parts = {
      year: String(d.getFullYear()), month: String(d.getMonth() + 1).padStart(2, '0'),
      day: String(d.getDate()).padStart(2, '0'), hour: String(d.getHours()).padStart(2, '0'),
      minute: String(d.getMinutes()).padStart(2, '0'), second: String(d.getSeconds()).padStart(2, '0')
    }
  }
  return String(format || 'HH:mm:ss')
    .replace('yyyy', parts.year).replace('MM', parts.month).replace('dd', parts.day)
    .replace('HH', parts.hour).replace('mm', parts.minute).replace('ss', parts.second)
}
