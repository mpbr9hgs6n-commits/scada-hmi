<template>
  <div class="ctl tbl" :class="{ 'ctl-edit': edit }">
    <!-- 运行态自定义时间区间（精确到分钟） -->
    <div v-if="!edit && P.allowRange !== false" class="rgbar">
      <input class="rg" type="datetime-local" step="60" v-model="startStr" @change="onRange" title="开始时间" />
      <span class="rgsep">→</span>
      <input class="rg" type="datetime-local" step="60" v-model="endStr" @change="onRange" title="结束时间" />
      <button class="rgbtn" :class="{ on: !useAbs }" @click="toLive">回到实时</button>
      <span class="rgspan">{{ spanText }}</span>
    </div>
    <div class="hd">
      <span class="ttl">{{ P.title || '数据表格' }}</span>
      <span class="sp" />
      <span v-if="busy" class="busy">读取中…</span>
      <button v-if="P.exportCsv !== false && !edit" class="btn" :disabled="!rows.length" @click="exportCsv">导出 CSV</button>
    </div>
    <div class="wrap">
      <table>
        <thead>
          <tr>
            <th v-if="P.showTime !== false" class="tm">时间</th>
            <th v-for="(c, i) in cols" :key="i">{{ c.label || tagText(c.expr) || ('列' + (i + 1)) }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, i) in pageRows" :key="i">
            <td v-if="P.showTime !== false" class="tm">{{ r.ts }}</td>
            <td v-for="(c, j) in cols" :key="j" class="nm">{{ r.v[j] }}</td>
          </tr>
          <tr v-if="!pageRows.length">
            <td :colspan="cols.length + (P.showTime !== false ? 1 : 0)" class="empty">
              {{ busy ? '读取中…' : (err || '暂无数据') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="P.pageSize" class="ft">
      <button class="pg" :disabled="page <= 1 || edit" @click="page--">上一页</button>
      <span class="pi">{{ page }} / {{ pages }}</span>
      <button class="pg" :disabled="page >= pages || edit" @click="page++">下一页</button>
      <span class="sp" />
      <span class="cnt">共 {{ rows.length }} 行</span>
    </div>
  </div>
</template>

<script setup>
// 数据表格：多列历史值按秒对齐成行，本地分页，导出 CSV 加 BOM（不加 Excel 中文乱码）
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { tagText } from '../varbind'
import { get } from '../../utils/request'

const props = defineProps({ item: { type: Object, required: true }, env: { type: Object, required: true } })
const P = computed(() => props.item.props || {})
const edit = computed(() => props.env.mode === 'edit')
const cols = computed(() => (P.value.vars || []).filter(v => String(v.expr || '').trim()))
const pageSize = computed(() => Math.max(1, Number(P.value.pageSize) || 10))

const rows = ref([])
const page = ref(1)
const busy = ref(false)
const err = ref('')
let timer = 0
let stopped = false

const pages = computed(() => Math.max(1, Math.ceil(rows.value.length / pageSize.value)))
const pageRows = computed(() => {
  const p = Math.min(page.value, pages.value)
  return rows.value.slice((p - 1) * pageSize.value, p * pageSize.value)
})

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

// —— 运行态自定义时间区间 ——
const SPAN = { '5m': 5, '30m': 30, '1h': 60, '4h': 240, '8h': 480, '24h': 1440, '7d': 10080 }
const rangeStart = ref(0)
const rangeEnd = ref(0)
const useAbs = computed(() => rangeStart.value > 0 && rangeEnd.value > rangeStart.value)
const startStr = ref('')
const endStr = ref('')
const pad2 = (n) => String(n).padStart(2, '0')
function isoLocal(ms) {
  const d = new Date(ms)
  const pad = (n) => String(n).padStart(2, '0')
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
         'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds())
}
function toLocalInput(ms) {
  const d = new Date(ms)
  return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) +
         'T' + pad2(d.getHours()) + ':' + pad2(d.getMinutes())
}
const spanMin = computed(() => {
  if (useAbs.value) return Math.max(1, (rangeEnd.value - rangeStart.value) / 60000)
  const v = P.value.customMinutes
  if (P.value.timeSpan === 'custom') return Math.max(1, Number(v) || 240)
  return SPAN[P.value.timeSpan] || 240
})
const spanText = computed(() => {
  const m = spanMin.value
  if (m < 60) return Math.round(m) + ' 分钟'
  if (m < 1440) return (m / 60).toFixed(m % 60 ? 1 : 0) + ' 小时'
  return (m / 1440).toFixed(m % 1440 ? 1 : 0) + ' 天'
})
/** 时间列格式按跨度动态（用户要求：区间大时自动调整） */
function fmtTs(s) {
  const m = String(s || '').match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/)
  if (!m) return String(s || '')
  const span = spanMin.value
  if (span <= 10)  return m[4] + ':' + m[5] + ':' + m[6]
  if (span <= 360) return m[4] + ':' + m[5]
  if (span <= 2880) return m[2] + '-' + m[3] + ' ' + m[4] + ':' + m[5]
  if (span <= 86400) return m[2] + '-' + m[3]
  return m[1] + '-' + m[2]
}
function onRange() {
  const a = startStr.value ? new Date(startStr.value).getTime() : 0
  const b = endStr.value ? new Date(endStr.value).getTime() : 0
  if (!a || !b || b <= a) return
  rangeStart.value = a; rangeEnd.value = b
  load()
}
function toLive() {
  rangeStart.value = 0; rangeEnd.value = 0
  startStr.value = ''; endStr.value = ''
  load()
}

async function load() {
  if (!cols.value.length) { rows.value = []; return }
  busy.value = true
  err.value = ''
  try {
    const series = []
    for (const c of cols.value) {
      const { site, point } = splitTag(c.expr)
      if (!site || !point) { series.push([]); continue }
      // 时间窗口：绝对区间优先，否则按可配跨度（原来写死 240 分钟，用户改不了）
      const q = { site, point, limit: '500' }
      if (useAbs.value) {
        // 后端 require_ts = dt.fromisoformat，只吃 ISO 字符串，传时间戳会 400
        q.from_ts = isoLocal(rangeStart.value)
        q.to_ts = isoLocal(rangeEnd.value)
      } else {
        q.minutes = String(spanMin.value)
      }
      const qs = new URLSearchParams(q).toString()
      const r = await get('/api/history?' + qs, { silent: true })
      series.push((r.rows || []).map(x => ({ ts: x.ts, val: x.val })))
    }
    // 按秒对齐：同一时间戳的多列值拼成一行（没有的列留空，不补 0）
    const map = new Map()
    series.forEach((arr, j) => {
      for (const p of arr) {
        const k = p.ts
        if (!map.has(k)) map.set(k, new Array(series.length).fill(''))
        map.get(k)[j] = fmtCell(p.val, cols.value[j])
      }
    })
    rows.value = [...map.entries()]
      .sort((a, b) => (a[0] < b[0] ? 1 : -1))
      .map(([ts, v]) => ({ ts: fmtTs(ts), tsFull: ts, v }))
    if (page.value > pages.value) page.value = 1
  } catch (e) {
    err.value = '历史数据读取失败'
    rows.value = []
  } finally {
    busy.value = false
  }
}

function fmtCell(v, c) {
  const n = Number(v)
  if (v == null || v === '' || !isFinite(n)) return ''
  // 按点位类型决定小数位：整数（uint32/int16/byte/bool）不能补 .00。
  // 表格是历史数据，本身不带类型，从该列绑定的点位取一次 dtype。
  let dt = ''
  try {
    const rec = props.env && props.env.read ? props.env.read(c && c.expr) : null
    dt = (rec && rec.dtype) || ''
  } catch (e) { dt = '' }
  const t = String(dt || c?.dtype || '').toLowerCase()
  if (t === 'bool') return n ? '1' : '0'
  if (['byte', 'int16', 'uint16', 'int32', 'uint32', 'int64', 'uint64'].includes(t)) {
    return String(Math.round(n))
  }
  const d = Number(c && c.decimals)
  return n.toFixed(isFinite(d) ? d : 2)
}

function exportCsv() {
  const head = []
  if (P.value.showTime !== false) head.push('时间')
  for (const c of cols.value) head.push(c.label || tagText(c.expr))
  const lines = [head.join(',')]
  for (const r of rows.value) {
    const cells = []
    if (P.value.showTime !== false) cells.push(r.tsFull)
    cells.push(...r.v)
    lines.push(cells.map(x => `"${String(x == null ? '' : x).replace(/"/g, '""')}"`).join(','))
  }
  // BOM：没有它 Excel 会按 GBK 解 UTF-8，中文全变乱码
  const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = (P.value.title || '数据表格') + '_' + new Date().toISOString().slice(0, 19).replace(/[:T]/g, '') + '.csv'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(a.href), 3000)
}

onMounted(() => {
  load()
  timer = setInterval(() => { if (!stopped && !document.hidden) load() }, 5000)
  // 默认把输入框填成「最近一个跨度」，方便用户在此基础上改
  const now = Date.now()
  startStr.value = toLocalInput(now - spanMin.value * 60000)
  endStr.value = toLocalInput(now)
})
onUnmounted(() => { stopped = true; clearInterval(timer) })
watch(() => JSON.stringify(P.value.vars || []), load)
watch(() => props.env.site, load)
</script>

<style scoped>
.ctl { width: 100%; height: 100%; box-sizing: border-box; display: flex; flex-direction: column; overflow: hidden;
  background: #0b1622; color: #cfe4f7; font-size: 12px; }
.ctl-edit { pointer-events: none; }
.hd { display: flex; align-items: center; gap: 6px; padding: 3px 6px; border-bottom: 1px solid #16283d; flex: 0 0 auto; }
.ttl { font-weight: 600; color: #c3ddf5; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sp { flex: 1 1 auto; }
.busy { color: #5b82a8; font-size: 10px; }
.btn { font-size: 10px; padding: 1px 6px; background: #123a5c; color: #cfe4f7; border: 1px solid #1e3a5f;
  border-radius: 2px; cursor: pointer; }
.btn:disabled { opacity: .5; cursor: not-allowed; }
.wrap { flex: 1 1 auto; overflow: auto; min-height: 0; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 2px 6px; border-bottom: 1px solid #12233a; white-space: nowrap; font-variant-numeric: tabular-nums; }
th { position: sticky; top: 0; background: #102338; color: #9fc3e8; font-weight: 500; text-align: left; font-size: 11px; }
td { color: #dbeafe; }
td.tm, th.tm { color: #7fa8cc; width: 1%; }
td.nm { text-align: right; }
.empty { text-align: center; color: #4a6d92; padding: 14px 0; }
.ft { display: flex; align-items: center; gap: 6px; padding: 3px 6px; border-top: 1px solid #16283d; flex: 0 0 auto; }
.pg { font-size: 10px; padding: 1px 6px; background: #123a5c; color: #cfe4f7; border: 1px solid #1e3a5f;
  border-radius: 2px; cursor: pointer; }
.pg:disabled { opacity: .45; cursor: not-allowed; }
.pi, .cnt { color: #7fa8cc; font-size: 10px; }

/* 运行态时间区间选择条 */
.rgbar { display: flex; align-items: center; gap: 4px; padding: 1px 3px; font-size: 11px;
         flex: 0 0 auto; border-bottom: 1px solid #12233a; }
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
