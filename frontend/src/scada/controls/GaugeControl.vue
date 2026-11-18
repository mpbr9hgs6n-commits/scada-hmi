<template>
  <div class="ctl gauge" :class="{ 'ctl-edit': edit }">
    <div v-if="P.title" class="ttl">{{ P.title }}</div>
    <svg class="sv" :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="xMidYMid meet">
      <!-- 底弧 -->
      <path :d="arcPath(0, 1)" fill="none" stroke="#16283d" :stroke-width="bw" stroke-linecap="butt" />
      <!-- 分区色（0-60 绿 / 60-80 黄 / 80-100 红 这类） -->
      <path v-for="(r, i) in rangeArcs" :key="i" :d="arcPath(r.a, r.b)" fill="none"
            :stroke="r.color" :stroke-width="bw" stroke-linecap="butt" :opacity="0.9" />
      <!-- 刻度 -->
      <line v-for="(t, i) in ticks" :key="'t' + i" :x1="t.x1" :y1="t.y1" :x2="t.x2" :y2="t.y2"
            stroke="#5b82a8" stroke-width="1.2" />
      <!-- 指针：CSS transition 让数值变化平滑转动，不跳变 -->
      <g class="needle" :style="{ transform: `rotate(${deg}deg)`, transformOrigin: `${cx}px ${cy}px` }">
        <line :x1="cx" :y1="cy" :x2="cx + len" :y2="cy" :stroke="needleColor" :stroke-width="Math.max(2, W * 0.014)"
              stroke-linecap="round" />
        <circle :cx="cx + len" :cy="cy" :r="Math.max(2, W * 0.012)" :fill="needleColor" />
      </g>
      <circle :cx="cx" :cy="cy" :r="Math.max(3, W * 0.03)" fill="#0e1f33" :stroke="needleColor" stroke-width="1.5" />
      <!-- 量程端点 -->
      <text :x="cx - r * 0.86" :y="cy + r * 0.45" class="sc" text-anchor="middle">{{ fmt(P.min) }}</text>
      <text :x="cx + r * 0.86" :y="cy + r * 0.45" class="sc" text-anchor="middle">{{ fmt(P.max) }}</text>
    </svg>
    <div v-if="P.showValue !== false" class="val" :class="{ bad: bad }">
      {{ shown }}<span v-if="P.unit" class="un">{{ P.unit }}</span>
    </div>
  </div>
</template>

<script setup>
// 仪表盘：SVG 圆弧 + 指针。值来自 env.read()（与画面其它数字同一套求值引擎）。
import { computed } from 'vue'

const props = defineProps({ item: { type: Object, required: true }, env: { type: Object, required: true } })
const P = computed(() => props.item.props || {})
const edit = computed(() => props.env.mode === 'edit')

const W = computed(() => Math.max(80, Number(props.item.w) || 160))
const H = computed(() => {
  const h = Math.max(80, Number(props.item.h) || 160)
  // 直径按宽度算，给下方数值留 18%
  return Math.max(80, Math.min(h, W.value * 0.98)) * 0.86
})
const cx = computed(() => W.value / 2)
const cy = computed(() => H.value * 0.62)
const r = computed(() => Math.min(W.value * 0.44, H.value * 0.52))
const bw = computed(() => Math.max(6, r.value * 0.16))
const len = computed(() => r.value * 0.82)

const min = computed(() => num(P.value.min, 0))
const max = computed(() => num(P.value.max, 100))

const r0 = computed(() => props.env.read(P.value['var'] || ''))
const val = computed(() => {
  const x = r0.value
  if (!x || !x.ok) return null
  const n = Number(x.value)
  return isFinite(n) ? n : null
})
const bad = computed(() => !r0.value || !r0.value.ok || r0.value.quality === 'bad')

const ratio = computed(() => {
  const v = val.value
  if (v == null) return 0
  const a = min.value, b = max.value
  return Math.max(0, Math.min(1, (v - a) / (b - a || 1)))
})
// 弧：150° 起，顺时针 240°，缺底部 120°（WinCC 仪表盘的标准形态）
const deg = computed(() => 150 + 240 * ratio.value)

function ang(ra) { return (150 + 240 * ra) * Math.PI / 180 }
function pt(ra, rr) {
  const a = ang(ra)
  return [cx.value + Math.cos(a) * rr, cy.value + Math.sin(a) * rr]
}
function arcPath(a, b) {
  const R = r.value
  const [x1, y1] = pt(a, R)
  const [x2, y2] = pt(b, R)
  const large = Math.abs((b - a) * 240) > 180 ? 1 : 0
  return `M${x1.toFixed(2)},${y1.toFixed(2)} A${R.toFixed(2)},${R.toFixed(2)} 0 ${large} 1 ${x2.toFixed(2)},${y2.toFixed(2)}`
}

const rangeArcs = computed(() => {
  const out = []
  for (const g of P.value.ranges || []) {
    const a = clamp01((num(g.from, min.value) - min.value) / ((max.value - min.value) || 1))
    const b = clamp01((num(g.to, max.value) - min.value) / ((max.value - min.value) || 1))
    if (b > a) out.push({ a, b, color: g.color || '#22c55e' })
  }
  return out
})

const ticks = computed(() => {
  const out = []
  for (let i = 0; i <= 10; i++) {
    const rr = i / 10
    const [x1, y1] = pt(rr, r.value * 0.99)
    const [x2, y2] = pt(rr, r.value * 0.9)
    out.push({ x1, y1, x2, y2 })
  }
  return out
})

const needleColor = computed(() => P.value.needleColor || '#f87171')
const shown = computed(() => {
  if (val.value == null) return '--'
  // 按点位类型决定小数位：整数（uint32/uint16/byte/bool）不能补 .0。
  // r0 就是 rt.read() 的完整记录，dtype 现成的。
  const dt = String((r0.value && r0.value.dtype) || '').toLowerCase()
  if (dt === 'bool') return val.value ? '1' : '0'
  if (['byte', 'int16', 'uint16', 'int32', 'uint32', 'int64', 'uint64'].includes(dt)) {
    return String(Math.round(val.value))
  }
  const d = Number(P.value.decimals)
  return val.value.toFixed(isFinite(d) ? d : 1)
})

function num(v, d) { const n = Number(v); return (v === '' || v == null || isNaN(n)) ? d : n }
function clamp01(x) { return Math.max(0, Math.min(1, x)) }
function fmt(v) { const n = num(v, 0); return String(Math.abs(n) >= 100 ? Math.round(n) : Number(n.toFixed(1))) }
</script>

<style scoped>
.ctl { width: 100%; height: 100%; box-sizing: border-box; display: flex; flex-direction: column;
  align-items: center; justify-content: center; overflow: hidden; position: relative; }
.ctl-edit { pointer-events: none; }
.ttl { font-size: 11px; color: #9fc3e8; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sv { width: 100%; flex: 1 1 auto; min-height: 0; }
.needle { transition: transform .45s cubic-bezier(.34, 1.2, .64, 1); }
.sc { font-size: 9px; fill: #5b82a8; }
.val { font-weight: 600; color: #e2e8f0; font-variant-numeric: tabular-nums; line-height: 1; margin-top: -6px;
  font-size: 16px; }
.val.bad { color: #f59e0b; }
.un { font-size: 10px; color: #9fc3e8; margin-left: 2px; font-weight: 400; }
</style>
