<template>
  <div class="ctl xy" :class="{ 'ctl-edit': edit }">
    <canvas ref="cv" @mousemove="onMove" @mouseleave="onLeave" />
    <div v-if="tip" class="tip" :style="{ left: tip.x + 'px', top: tip.y + 'px' }">{{ tip.text }}</div>
    <div v-if="hint" class="hint">{{ hint }}</div>
    <div v-if="P.title" class="ttl">{{ P.title }}</div>
    <!-- 图例：多条 Y 曲线要能对上颜色（用户要求"正确体现各自的数据线"） -->
    <div v-if="!edit && pairs.length" class="lg">
      <span v-for="(s, i) in pairs" :key="i" class="lgi">
        <i :style="{ background: s.color }" />{{ s.name }}<b>{{ s.lastText }}</b>
      </span>
    </div>
  </div>
</template>

<script setup>
// X-Y 曲线：取同一时间窗内 xVar 与 yVar 的历史，按时间戳配对成 (x,y)，
// 再按 x 排序连线 —— 用于流量-扬程、泵特性这类"两个量之间的关系"。
import { tagText } from '../varbind'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { get } from '../../utils/request'

const props = defineProps({ item: { type: Object, required: true }, env: { type: Object, required: true } })
const P = computed(() => props.item.props || {})
const edit = computed(() => props.env.mode === 'edit')

const cv = ref(null)
const pairs = ref([])      // [{name, color, pts:[{x,y}]}]
const hint = ref('')
const tip = ref(null)
let timer = 0
let ro = null
let stopped = false
let mx = null, my = null

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

function parseTs(s) {
  const m = String(s || '').match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/)
  return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]).getTime() : 0
}

async function hist(expr, minutes) {
  const { site, point } = splitTag(expr)
  if (!site || !point) return new Map()
  const qs = new URLSearchParams({ site, point, minutes: String(minutes), limit: '2000' }).toString()
  try {
    const r = await get('/api/history?' + qs, { silent: true })
    const m = new Map()
    for (const x of r.rows || []) {
      const t = parseTs(x.ts), v = Number(x.val)
      if (t && isFinite(v)) m.set(t, v)
    }
    return m
  } catch (e) { return new Map() }
}

async function load() {
  const mins = Math.max(1, Number(P.value.minutes) || 60)
  const ym = await hist(P.value.xVar, mins)
  const out = []
  if (ym.size) {
    for (const y of (P.value.yVars || []).filter(v => String(v.expr || '').trim())) {
      const yv = await hist(y.expr, mins)
      const pts = []
      for (const [t, x] of ym) {
        if (!yv.has(t)) continue
        pts.push({ x, y: yv.get(t) })
      }
      pts.sort((a, b) => a.x - b.x)
      // 图例要显示当前值：用实时值（X-Y 图的最后一个历史点不代表"现在"）
      const cur = props.env && props.env.num ? props.env.num(y.expr) : null
      const n = Number(cur)
      out.push({ name: tagText(y.expr).split('.').pop(), color: y.color || '#2ecc71', pts,
                 lastText: (cur == null || !isFinite(n)) ? '--' : n.toFixed(2) })
    }
  }
  pairs.value = out
  hint.value = out.some(p => p.pts.length) ? '' : (P.value.xVar ? '历史数据积累中…' : '未配置 X 轴变量')
  draw()
}

function cssW() { return Math.max(40, (cv.value && cv.value.parentElement && cv.value.parentElement.offsetWidth) || Number(props.item.w) || 400) }
function cssH() { return Math.max(40, (cv.value && cv.value.parentElement && cv.value.parentElement.offsetHeight) || Number(props.item.h) || 260) }

function draw() {
  const el = cv.value
  if (!el) return
  const dpr = window.devicePixelRatio || 1
  const w = cssW(), h = cssH()
  el.width = Math.round(w * dpr); el.height = Math.round(h * dpr)
  el.style.width = w + 'px'; el.style.height = h + 'px'
  const g = el.getContext('2d')
  g.setTransform(dpr, 0, 0, dpr, 0, 0)
  g.clearRect(0, 0, w, h)

  // 顶部：标题 / 图例各占一行，否则曲线会压在图例上
  const lgH = (!edit.value && pairs.value.length) ? 16 : 0
  const pl = 44, pr = 10, pt = (P.value.title ? 20 : 8) + lgH, pb = 24
  const iw = Math.max(10, w - pl - pr), ih = Math.max(10, h - pt - pb)
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity
  for (const s of pairs.value) for (const p of s.pts) {
    if (p.x < x0) x0 = p.x; if (p.x > x1) x1 = p.x
    if (p.y < y0) y0 = p.y; if (p.y > y1) y1 = p.y
  }
  if (!isFinite(x0)) { x0 = 0; x1 = 1; y0 = 0; y1 = 1 }
  if (x1 - x0 < 1e-6) { x0 -= 1; x1 += 1 }
  if (y1 - y0 < 1e-6) { y0 -= 1; y1 += 1 }
  const px = (x1 - x0) * 0.05, py = (y1 - y0) * 0.06
  x0 -= px; x1 += px; y0 -= py; y1 += py

  g.fillStyle = '#0a1520'
  g.fillRect(pl, pt, iw, ih)
  if (P.value.grid !== false) {
    g.strokeStyle = '#16283d'; g.lineWidth = 1; g.beginPath()
    for (let i = 0; i <= 4; i++) { const y = pt + ih * i / 4; g.moveTo(pl, y); g.lineTo(pl + iw, y) }
    for (let i = 0; i <= 5; i++) { const x = pl + iw * i / 5; g.moveTo(x, pt); g.lineTo(x, pt + ih) }
    g.stroke()
  }
  g.fillStyle = '#5b82a8'; g.font = '10px system-ui, sans-serif'
  g.textAlign = 'right'; g.textBaseline = 'middle'
  for (let i = 0; i <= 4; i++) {
    const v = y1 - (y1 - y0) * i / 4
    g.fillText(v.toFixed(1), pl - 4, pt + ih * i / 4)
  }
  g.textAlign = 'center'; g.textBaseline = 'top'
  for (let i = 0; i <= 5; i++) g.fillText((x0 + (x1 - x0) * i / 5).toFixed(1), pl + iw * i / 5, pt + ih + 4)

  const X = (v) => pl + iw * (v - x0) / (x1 - x0 || 1)
  const Y = (v) => pt + ih * (1 - (v - y0) / (y1 - y0 || 1))
  for (const s of pairs.value) {
    if (!s.pts.length) continue
    g.strokeStyle = s.color; g.lineWidth = 1.6; g.beginPath()
    s.pts.forEach((p, i) => { const x = X(p.x), y = Y(p.y); i ? g.lineTo(x, y) : g.moveTo(x, y) })
    g.stroke()
    g.fillStyle = s.color
    const r = Math.max(1.5, Number(P.value.pointSize) || 2)
    for (const p of s.pts) { g.beginPath(); g.arc(X(p.x), Y(p.y), r, 0, Math.PI * 2); g.fill() }
  }

  if (mx != null && my != null && pairs.value.length) {
    let best = null
    for (const s of pairs.value) for (const p of s.pts) {
      const dx = X(p.x) - mx, dy = Y(p.y) - my
      const d = dx * dx + dy * dy
      if (!best || d < best.d) best = { d, s, p }
    }
    if (best && best.d < 900) {
      tip.value = {
        x: Math.min(w - 150, Math.max(2, X(best.p.x) + 8)),
        y: Math.max(2, Y(best.p.y) - 26),
        text: `${best.s.name}  (${best.p.x.toFixed(2)}, ${best.p.y.toFixed(2)})`
      }
    } else tip.value = null
  } else tip.value = null
}

function onMove(e) {
  const r = cv.value.getBoundingClientRect()
  mx = e.clientX - r.left; my = e.clientY - r.top
  draw()
}
function onLeave() { mx = null; my = null; tip.value = null; draw() }

onMounted(() => {
  load()
  timer = setInterval(() => { if (!stopped && !document.hidden) load() }, 10000)
  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(() => draw())
    if (cv.value && cv.value.parentElement) ro.observe(cv.value.parentElement)
  }
})
onUnmounted(() => { stopped = true; clearInterval(timer); if (ro) { try { ro.disconnect() } catch (e) { /* 忽略 */ } } })
watch(() => JSON.stringify([P.value.xVar, P.value.yVars, P.value.minutes]), load)
watch(() => props.env.site, load)
</script>

<style scoped>
.ctl { width: 100%; height: 100%; box-sizing: border-box; overflow: hidden; background: #0b1622; position: relative; }
canvas { display: block; }
.ttl { position: absolute; left: 46px; top: 3px; font-size: 11px; color: #c3ddf5; pointer-events: none; }
.tip { position: absolute; pointer-events: none; background: rgba(10, 22, 34, .94); border: 1px solid #1e3a5f;
  color: #dbeafe; font-size: 11px; padding: 2px 6px; border-radius: 3px; white-space: nowrap; z-index: 3; }
.hint { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  color: #4a6d92; font-size: 12px; pointer-events: none; }

/* X-Y 曲线图例（与趋势曲线同一套视觉） */
.lg { position: absolute; left: 44px; right: 4px; top: 18px; height: 16px;
      display: flex; gap: 10px; align-items: center; overflow: hidden; pointer-events: none; }
.lgi { display: flex; align-items: center; gap: 4px; font-size: 10px; color: #9fc3e8; white-space: nowrap; }
.lgi i { width: 10px; height: 3px; border-radius: 1px; flex: 0 0 10px; }
.lgi b { color: #dbeafe; font-weight: 600; font-variant-numeric: tabular-nums; }
</style>
