<template>
  <div class="ctl trend" :class="{ 'ctl-edit': edit, 'has-rg': !edit && P.allowRange !== false }" :style="{ paddingTop: P.legend === 'top' ? '16px' : '0' }">
    <!-- 运行态：自定义时间区间（精确到分钟）。用户 2026-11-14 要求：
         发布后可以随意设开始和结束时间，区间大时标签格式自动跟着变。 -->
    <div v-if="!edit && P.allowRange !== false" class="rgbar">
      <input class="rg" type="datetime-local" step="60" v-model="startStr" @change="onRange" title="开始时间" />
      <span class="rgsep">→</span>
      <input class="rg" type="datetime-local" step="60" v-model="endStr" @change="onRange" title="结束时间" />
      <button class="rgbtn" :class="{ on: !useAbs }" @click="toLive">回到实时</button>
      <span class="rgspan">{{ spanText }}</span>
    </div>
    <div class="wrap">
      <canvas ref="cv" @mousemove="onMove" @mouseleave="onLeave" />
      <div v-if="tip" class="tip" :style="{ left: tip.x + 'px', top: tip.y + 'px' }">{{ tip.text }}</div>
      <div v-if="hint" class="hint">{{ hint }}</div>
      <div v-if="P.legend === 'top'" class="lg top">
        <span v-for="(s, i) in series" :key="i" class="lgi">
          <i :style="{ background: s.color }" />{{ short(s.expr) }}<b>{{ s.lastText }}</b>
        </span>
      </div>
      <div v-if="P.legend === 'right'" class="lg right">
        <div v-for="(s, i) in series" :key="i" class="lgi">
          <i :style="{ background: s.color }" />{{ short(s.expr) }}<b>{{ s.lastText }}</b>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
// 趋势曲线：canvas 折线。
// 数据源按跨度自动切换 —— ≤5m 走实时（先拉一段历史打底，之后从运行时值采样），
// 更长跨度走 /api/history。刷新周期默认 5s：20 万点位时前端不能跟 250ms 广播走。
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { tagText } from '../varbind'
import { get } from '../../utils/request'

const props = defineProps({ item: { type: Object, required: true }, env: { type: Object, required: true } })
const P = computed(() => props.item.props || {})
const edit = computed(() => props.env.mode === 'edit')

const cv = ref(null)
const series = ref([])
const hint = ref('')
const tip = ref(null)
let ro = null
let timer = 0
let stopped = false
let mx = null

const SPAN = {
  '5m': 5, '30m': 30, '1h': 60, '8h': 480, '24h': 1440
}
// —— 运行态自定义时间区间 ——
// 绝对区间优先；没设就用 timeSpan 相对窗口（原行为）。
const rangeStart = ref(0)
const rangeEnd = ref(0)
const useAbs = computed(() => rangeStart.value > 0 && rangeEnd.value > rangeStart.value)
const startStr = ref('')
const endStr = ref('')
function pad2(n) { return String(n).padStart(2, '0') }
function isoLocal(ms) {
  const d = new Date(ms)
  const d2 = new Date(ms)
  const pad = (n) => String(n).padStart(2, '0')
  return d2.getFullYear() + '-' + pad(d2.getMonth() + 1) + '-' + pad(d2.getDate()) +
         'T' + pad(d2.getHours()) + ':' + pad(d2.getMinutes()) + ':' + pad(d2.getSeconds())
}
function toLocalInput(ms) {
  const d = new Date(ms)
  return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) +
         'T' + pad2(d.getHours()) + ':' + pad2(d.getMinutes())
}
function onRange() {
  const a = startStr.value ? new Date(startStr.value).getTime() : 0
  const b = endStr.value ? new Date(endStr.value).getTime() : 0
  if (!a || !b || b <= a) return
  rangeStart.value = a
  rangeEnd.value = b
  load(true)
}
function toLive() {
  rangeStart.value = 0; rangeEnd.value = 0
  startStr.value = ''; endStr.value = ''
  load(true)
}
onMounted(() => {
  // 默认把输入框填成「最近一个 timeSpan」作为起点，方便用户改
  const now = Date.now()
  const m = SPAN[P.value.timeSpan] || 60
  startStr.value = toLocalInput(now - m * 60000)
  endStr.value = toLocalInput(now)
})

const spanMin = computed(() => {
  if (useAbs.value) return Math.max(1, (rangeEnd.value - rangeStart.value) / 60000)
  if (P.value.timeSpan === 'custom') return Math.max(1, Number(P.value.customMinutes) || 60)
  return SPAN[P.value.timeSpan] || 60
})
// 绝对区间时不做「实时补点」——看的是历史那一段
const isLive = computed(() => !useAbs.value && spanMin.value <= 5)

/** 区间跨度决定时间轴标签格式（用户要求：区间大时自动调整） */
const spanText = computed(() => {
  const m = spanMin.value
  if (m < 60) return Math.round(m) + ' 分钟'
  if (m < 1440) return (m / 60).toFixed(m % 60 ? 1 : 0) + ' 小时'
  return (m / 1440).toFixed(m % 1440 ? 1 : 0) + ' 天'
})
function fmtAxis(ms) {
  const m = spanMin.value
  const d = new Date(ms)
  if (m <= 10) return pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds())
  if (m <= 360) return pad2(d.getHours()) + ':' + pad2(d.getMinutes())
  if (m <= 2880) return pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) + ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes())
  if (m <= 86400) return pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
  return d.getFullYear() + '-' + pad2(d.getMonth() + 1)
}
const vars = computed(() => (P.value.vars || []).filter(v => String(v.expr || '').trim() && v.visible !== false))

// 变量可能是对象，必须 tagText；String(对象) 会显示 [object Object]
function short(e) { const s = tagText(e); return s.length > 14 ? s.slice(s.length - 14) : s }

function cssW() {
  const el = cv.value
  const box = el && el.parentElement
  // 首帧 clientWidth 可能是 0（还没进文档/缩放未完成）→ 退回配置宽度
  return Math.max(40, (box && box.offsetWidth) || Number(props.item.w) || 400)
}
function cssH() {
  const el = cv.value
  const box = el && el.parentElement
  return Math.max(40, (box && box.offsetHeight) || Number(props.item.h) || 200)
}

function splitTag(expr) {
  // 变量可能是 {site, point} 对象（4.3 规范）。
  // String(对象) 得到 "[object Object]" → 拆出 point='[object Object]' → 取历史必失败，
  // 界面上还会显示成 [object Object]。对象先拍平，再走下面的字符串分支。
  if (expr && typeof expr === 'object') {
    const st = typeof expr.site === 'string' ? expr.site.trim() : ''
    const pt = typeof expr.point === 'string' ? expr.point.trim() : ''
    if (pt) return { site: st || props.env.site || '', point: pt }
  }
  const s = String(expr || '').trim()
  const i = s.indexOf('.')
  if (i > 0) return { site: s.slice(0, i), point: s.slice(i + 1) }
  return { site: props.env.site || '', point: s }
}

async function fetchSeries(v, minutes) {
  const { site, point } = splitTag(v.expr)
  if (!site || !point) return []
  const q = { site, point, limit: minutes <= 5 ? '300' : (minutes <= 60 ? '1200' : '2000') }
  if (useAbs.value) {
    // 后端 require_ts 用 dt.datetime.fromisoformat → 必须传 ISO 字符串。
    // 之前传的是秒级时间戳（1794643210），后端解析失败直接 400，
    // 前端 catch 成空数组，表现为「设了区间但没数据」。
    q.from_ts = isoLocal(rangeStart.value)
    q.to_ts = isoLocal(rangeEnd.value)
  } else {
    q.minutes = String(minutes)
  }
  const qs = new URLSearchParams(q).toString()
  try {
    const r = await get('/api/history?' + qs, { silent: true })
    return (r.rows || []).map(x => {
      const t = parseTs(x.ts)
      const n = Number(x.val)
      return (t && isFinite(n)) ? { t, v: n } : null
    }).filter(Boolean)
  } catch (e) { return [] }
}

function parseTs(s) {
  // 后端给的是 'yyyy-mm-dd hh:mm:ss'（TDengine to_char），本地时区
  const m = String(s || '').match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/)
  if (!m) return 0
  return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]).getTime()
}

async function load(full) {
  const mins = spanMin.value
  const out = []
  for (const v of vars.value) {
    // 对象不能用 === 比较（每次重建都是新引用），统一按 tag 文本比
const _vTag = tagText(v.expr)
    const old = (series.value.find(s => tagText(s.expr) === _vTag) || {}).pts || []
    let pts = full || !isLive.value ? await fetchSeries(v, mins) : old.slice()
    // 实时模式：把运行时当前值接上去，否则两次刷新之间没有新点
    if (isLive.value) {
      const cur = props.env.num(v.expr)
      const now = Date.now()
      if (cur != null) {
        const last = pts[pts.length - 1]
        if (!last || now - last.t > 800) pts.push({ t: now, v: cur })
        else { last.t = now; last.v = cur }
      }
      const since = now - mins * 60000
      pts = pts.filter(p => p.t >= since)
    }
    out.push({
      expr: v.expr, color: v.color || '#2ecc71', width: Number(v.width) || 2,
      pts
    })
  }
  series.value = out
  const hasData = out.some(s => s.pts.length >= 2)
  // 历史为空：用当前值画一个点，并且明说"积累中"，不要空白让人以为坏了
  hint.value = hasData ? '' : (vars.value.length ? '历史数据积累中…' : '未配置曲线')
  draw()
}

function draw() {
  const el = cv.value
  if (!el) return
  // 时间轴标签画在 canvas 里，DOM 读不到。把当前格式记到 dataset 上，
  // 方便自动化断言「区间变大时格式确实变了」，对显示无影响。
  try {
    const _m = spanMin.value
    el.dataset.axisFmt = _m <= 10 ? 'HH:mm:ss' : (_m <= 360 ? 'HH:mm'
      : (_m <= 2880 ? 'MM-DD HH:mm' : (_m <= 86400 ? 'MM-DD' : 'YYYY-MM')))
    el.dataset.axisFmtSample = fmtAxis(useAbs.value ? rangeStart.value : Date.now() - _m * 60000)
  } catch (e) {}
  const dpr = window.devicePixelRatio || 1
  const w = cssW(), h = cssH()
  el.width = Math.round(w * dpr)
  el.height = Math.round(h * dpr)
  el.style.width = w + 'px'
  el.style.height = h + 'px'
  const g = el.getContext('2d')
  g.setTransform(dpr, 0, 0, dpr, 0, 0)
  g.clearRect(0, 0, w, h)

  const pl = 46, pr = (P.value.legend === 'right' ? 76 : 8), pt = 6, pb = 20
  const iw = Math.max(10, w - pl - pr), ih = Math.max(10, h - pt - pb)
  // 绝对区间看历史那段；否则跟当前时间走
  const t1 = useAbs.value ? rangeEnd.value : Date.now()
  const t0 = useAbs.value ? rangeStart.value : t1 - spanMin.value * 60000

  // 量程
  let lo = NaN, hi = NaN
  if (P.value.yMode === 'fixed') {
    lo = Number(P.value.yMin); hi = Number(P.value.yMax)
  } else {
    for (const s of series.value) for (const p of s.pts) {
      if (p.t < t0) continue
      if (!isFinite(lo) || p.v < lo) lo = p.v
      if (!isFinite(hi) || p.v > hi) hi = p.v
    }
  }
  if (!isFinite(lo) || !isFinite(hi)) { lo = 0; hi = 100 }
  if (hi - lo < 1e-6) { hi = lo + 1; lo = lo - 1 }
  const pad = (hi - lo) * 0.06
  if (P.value.yMode !== 'fixed') { lo -= pad; hi += pad }

  // 背景
  g.fillStyle = '#0a1520'
  g.fillRect(pl, pt, iw, ih)

  // 网格
  if (P.value.grid !== false) {
    g.strokeStyle = '#16283d'
    g.lineWidth = 1
    g.beginPath()
    for (let i = 0; i <= 4; i++) {
      const y = pt + ih * i / 4
      g.moveTo(pl, y); g.lineTo(pl + iw, y)
    }
    for (let i = 0; i <= 5; i++) {
      const x = pl + iw * i / 5
      g.moveTo(x, pt); g.lineTo(x, pt + ih)
    }
    g.stroke()
  }

  // 轴标签
  g.fillStyle = '#5b82a8'
  g.font = '10px system-ui, sans-serif'
  g.textAlign = 'right'
  g.textBaseline = 'middle'
  for (let i = 0; i <= 4; i++) {
    const v = hi - (hi - lo) * i / 4
    const y = pt + ih * i / 4
    g.fillText(Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(1), pl - 4, y)
  }
  g.textAlign = 'center'
  g.textBaseline = 'top'
  const spanTxt = (t) => {
    const d = new Date(t)
    return spanMin.value <= 5
      ? fmtAxis(t)
      : fmtAxis(t)
  }
  for (let i = 0; i <= 5; i++) {
    const t = t0 + (t1 - t0) * i / 5
    const x = pl + iw * i / 5
    g.fillText(spanTxt(t), x, pt + ih + 4)
  }

  // 曲线
  const X = (t) => pl + iw * (t - t0) / (t1 - t0 || 1)
  const Y = (v) => pt + ih * (1 - (v - lo) / (hi - lo || 1))
  for (const s of series.value) {
    if (s.pts.length === 0) continue
    g.strokeStyle = s.color
    g.lineWidth = s.width
    g.lineJoin = 'round'
    g.beginPath()
    let started = false
    for (const p of s.pts) {
      if (p.t < t0 - 60000) continue
      const x = X(p.t), y = Y(p.v)
      if (!started) { g.moveTo(x, y); started = true } else g.lineTo(x, y)
    }
    if (started) g.stroke()
    const last = s.pts[s.pts.length - 1]
    s.lastText = last ? last.v.toFixed(2) : '--'
  }

  // 十字线
  if (mx != null && P.value.crosshair !== false) {
    let best = null
    for (const s of series.value) {
      for (const p of s.pts) {
        const x = X(p.t)
        if (!best || Math.abs(x - mx) < Math.abs(X(best.p.t) - mx)) best = { s, p, x }
      }
    }
    if (best) {
      g.strokeStyle = 'rgba(30,200,255,.55)'
      g.lineWidth = 1
      g.beginPath()
      g.moveTo(best.x, pt); g.lineTo(best.x, pt + ih)
      g.moveTo(pl, Y(best.p.v)); g.lineTo(pl + iw, Y(best.p.v))
      g.stroke()
      g.fillStyle = best.s.color
      g.beginPath()
      g.arc(best.x, Y(best.p.v), 3, 0, Math.PI * 2)
      g.fill()
      const d = new Date(best.p.t)
      tip.value = {
        x: Math.min(w - 130, Math.max(2, best.x + 8)),
        y: Math.max(2, Y(best.p.v) - 26),
        text: `${short(best.s.expr)}  ${best.p.v.toFixed(2)}  ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
      }
    }
  } else {
    tip.value = null
  }
}

function onMove(e) {
  const r = cv.value.getBoundingClientRect()
  mx = e.clientX - r.left
  draw()
}
function onLeave() { mx = null; tip.value = null; draw() }

onMounted(() => {
  load(true)
  const refresh = Math.max(1, Number(P.value.refresh) || 5) * 1000
  timer = setInterval(() => {
    if (stopped || document.hidden) return
    // 实时模式不用重新拉历史，直接采样重绘即可；长跨度才周期性拉库
    if (isLive.value) {
      for (const s of series.value) {
        const cur = props.env.num(s.expr)
        const now = Date.now()
        if (cur == null) continue
        const last = s.pts[s.pts.length - 1]
        if (!last || now - last.t > 800) s.pts.push({ t: now, v: cur })
        else { last.t = now; last.v = cur }
      }
      const since = Date.now() - spanMin.value * 60000
      for (const s of series.value) s.pts = s.pts.filter(p => p.t >= since)
      const hasData = series.value.some(s => s.pts.length >= 2)
      hint.value = hasData ? '' : (vars.value.length ? '历史数据积累中…' : '未配置曲线')
      draw()
    } else {
      load(false)
    }
  }, refresh)
  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(() => draw())
    if (cv.value && cv.value.parentElement) ro.observe(cv.value.parentElement)
  }
})
onUnmounted(() => {
  stopped = true
  clearInterval(timer)
  if (ro) { try { ro.disconnect() } catch (e) { /* 忽略 */ } }
})
watch(() => JSON.stringify(P.value.vars || []), () => load(true))
watch(() => [P.value.timeSpan, P.value.yMode, P.value.yMin, P.value.yMax], () => load(true))
watch(() => [rangeStart.value, rangeEnd.value], () => load(true))
watch(() => props.env.site, () => load(true))
</script>

<style scoped>
.ctl { width: 100%; height: 100%; box-sizing: border-box; overflow: hidden; background: #0b1622; position: relative; }
.wrap { position: absolute; inset: 0; }
.ctl.has-rg .wrap { top: 23px; }
canvas { display: block; }
.tip { position: absolute; pointer-events: none; background: rgba(10, 22, 34, .94); border: 1px solid #1e3a5f;
  color: #dbeafe; font-size: 11px; padding: 2px 6px; border-radius: 3px; white-space: nowrap; z-index: 3; }
.hint { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  color: #4a6d92; font-size: 12px; pointer-events: none; }
.lg { position: absolute; display: flex; gap: 10px; pointer-events: none; overflow: hidden; }
.lg.top { left: 48px; top: 0; height: 16px; align-items: center; right: 4px; }
.lg.right { right: 4px; top: 6px; width: 72px; flex-direction: column; gap: 3px; }
.lgi { display: flex; align-items: center; gap: 4px; font-size: 10px; color: #9fc3e8; white-space: nowrap; }
.lgi i { width: 10px; height: 3px; border-radius: 1px; flex: 0 0 10px; }
.lgi b { color: #dbeafe; font-weight: 600; font-variant-numeric: tabular-nums; }
/* 运行态时间区间选择条 */
/* .wrap 是 absolute inset:0 撑满整个控件，普通流里的时间条会被它整块盖住
   （表现：看得见但点不到，canvas 拦截 pointer events）→ 必须绝对定位到最上层 */
.rgbar { display: flex; align-items: center; gap: 4px; padding: 1px 3px; font-size: 11px;
         position: absolute; top: 0; left: 0; right: 0; height: 23px;
         z-index: 10; box-sizing: border-box; background: #0b1622; }
.rg { background: #0b1a29; border: 1px solid #24405c; color: #cfe4f7; border-radius: 3px;
      padding: 1px 3px; font-size: 11px; height: 21px; font-family: Consolas, monospace; }
.rg:focus { border-color: #1ec8ff; outline: none; }
.rgsep { color: #5f7f9f; }
.rgbtn { background: #16283c; border: 1px solid #24405c; color: #7cc4ff; border-radius: 3px;
         padding: 1px 6px; font-size: 11px; height: 21px; cursor: pointer; }
.rgbtn:hover { border-color: #1ec8ff; color: #cdeaff; }
.rgbtn.on { border-color: #1ec8ff; color: #1ec8ff; background: rgba(30,200,255,.12); }
.rgspan { margin-left: auto; color: #5f7f9f; }
</style>
