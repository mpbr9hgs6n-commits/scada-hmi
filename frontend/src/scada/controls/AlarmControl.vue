<template>
  <div class="ctl alarms" :class="{ 'ctl-edit': edit }">
    <!-- 运行态自定义时间区间（按报警首次出现时间过滤，精确到分钟） -->
    <div v-if="!edit && P.allowRange !== false" class="rgbar">
      <input class="rg" type="datetime-local" step="60" v-model="startStr" @change="onRange" title="开始时间" />
      <span class="rgsep">→</span>
      <input class="rg" type="datetime-local" step="60" v-model="endStr" @change="onRange" title="结束时间" />
      <button class="rgbtn" :class="{ on: !useAbs }" @click="toLive">回到实时</button>
      <span class="rgspan">{{ spanText }}</span>
    </div>
    <div class="hd">
      <span class="ttl">{{ P.title || '实时报警' }}</span>
      <span class="tag">{{ P.source === 'global' ? '全部站点' : (env.site || '未选站点') }}</span>
      <span class="sp" />
      <span class="cnt" :class="{ hot: unacked > 0 }">未确认 {{ unacked }}</span>
      <span class="sse" :class="{ on: sseOk }" :title="sseOk ? '实时推送已连接' : '推送断开，正在重连'">●</span>
    </div>
    <div ref="body" class="body">
      <table>
        <thead>
          <tr>
            <th v-for="c in cols" :key="c" :class="'c-' + c">{{ COL[c] }}</th>
            <th v-if="!edit" class="c-act">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in shown" :key="a.id" :class="['lv' + a.level, { fresh: freshSet.has(a.id), acked: a.state === 1 }]">
            <td v-for="c in cols" :key="c" :class="'c-' + c">{{ cell(a, c) }}</td>
            <td v-if="!edit" class="c-act">
              <button v-if="a.state === 0" class="btn" @click="ack(a)">确认</button>
              <button class="btn ghost" @click="doClose(a)">关闭</button>
            </td>
          </tr>
          <tr v-if="!shown.length">
            <td :colspan="cols.length + (edit ? 0 : 1)" class="empty">当前无报警</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
// 报警窗：靠 SSE 推送（/api/alarm/subscribe），不轮询 ——
// 轮询 5 秒的后果是操作员看到报警时已经过去 5 秒。
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { post } from '../../utils/request'

const props = defineProps({ item: { type: Object, required: true }, env: { type: Object, required: true } })
const P = computed(() => props.item.props || {})
const edit = computed(() => props.env.mode === 'edit')

const COL = { time: '时间', site: '站点', point: '点位', msg: '内容', level: '级别', state: '状态', count: '次数' }
const ALL = ['time', 'site', 'point', 'msg', 'level', 'state', 'count']
const cols = computed(() => {
  const c = (P.value.columns || ALL).filter(x => ALL.includes(x))
  return c.length ? c : ALL
})
const maxRows = computed(() => Math.max(1, Number(P.value.maxRows) || 20))

const list = ref([])
const freshSet = ref(new Set())
const sseOk = ref(false)
const body = ref(null)
let es = null
let retry = 0

// —— 运行态自定义时间区间 ——
const SPAN = { '5m': 5, '30m': 30, '1h': 60, '4h': 240, '8h': 480, '24h': 1440, '7d': 10080 }
const rangeStart = ref(0)
const rangeEnd = ref(0)
const useAbs = computed(() => rangeStart.value > 0 && rangeEnd.value > rangeStart.value)
const startStr = ref('')
const endStr = ref('')
const pad2 = (n) => String(n).padStart(2, '0')
function toLocalInput(ms) {
  const d = new Date(ms)
  return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) +
         'T' + pad2(d.getHours()) + ':' + pad2(d.getMinutes())
}
const spanMin = computed(() => {
  if (useAbs.value) return Math.max(1, (rangeEnd.value - rangeStart.value) / 60000)
  if (P.value.timeSpan === 'custom') return Math.max(1, Number(P.value.customMinutes) || 1440)
  return SPAN[P.value.timeSpan] || 1440
})
const spanText = computed(() => {
  const m = spanMin.value
  if (m < 60) return Math.round(m) + ' 分钟'
  if (m < 1440) return (m / 60).toFixed(m % 60 ? 1 : 0) + ' 小时'
  return (m / 1440).toFixed(m % 1440 ? 1 : 0) + ' 天'
})
function tsMs(s) {
  if (!s) return 0
  const m = String(s).match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/)
  if (!m) return 0
  return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]).getTime()
}
/** 时间列格式按跨度动态（与 trend / table 同一套规则） */
function fmtTs(s) {
  const m = String(s || '').match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/)
  if (!m) return String(s || '').slice(5, 19)
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
}
function toLive() {
  rangeStart.value = 0; rangeEnd.value = 0
  startStr.value = ''; endStr.value = ''
}

// 只显示组态里关联的那些变量的报警（P.vars 为空 = 不限，显示本站全部）
const varSet = computed(() => {
  const vs = (P.value.vars || []).filter(v => v && v.expr)
  if (!vs.length) return null
  const set = new Set()
  for (const v of vs) {
    const e = v.expr
    const pt = (e && typeof e === 'object') ? String(e.point || '').trim() : String(e || '').trim()
    if (pt) set.add(pt)
  }
  return set.size ? set : null
})

const shown = computed(() => {
  let arr = list.value
  const vs = varSet.value
  if (vs) arr = arr.filter(a => vs.has(String(a.point_code || '').trim()))
  // 时间窗口：按首次出现时间过滤（用户要的「自定义区间」）
  if (useAbs.value) {
    arr = arr.filter(a => {
      const t = tsMs(a.first_ts || a.last_ts)
      return t >= rangeStart.value && t <= rangeEnd.value
    })
  } else {
    const since = Date.now() - spanMin.value * 60000
    arr = arr.filter(a => {
      const t = tsMs(a.first_ts || a.last_ts)
      return !t || t >= since
    })
  }
  if (P.value.onlyUnacked) arr = arr.filter(a => a.state === 0)
  return arr.slice(0, maxRows.value)
})
const unacked = computed(() => list.value.filter(a => a.state === 0).length)

function cell(a, c) {
  switch (c) {
    case 'time': return fmtTs(a.first_ts || a.last_ts)
    case 'site': return a.site_id || ''
    case 'point': return a.name || a.point_code || ''
    case 'msg': return a.msg || ''
    case 'level': return a.level_name || (a.level === 1 ? '提示' : a.level === 3 ? '严重' : '报警')
    case 'state': return a.state_name || STATE[a.state] || ''
    case 'count': return a.count || 1
    default: return ''
  }
}
const STATE = { 0: '未确认', 1: '已确认', 2: '已恢复', 3: '已关闭' }

function upsert(a) {
  const id = Number(a.id)
  if (!id) return
  const i = list.value.findIndex(x => x.id === id)
  const obj = {
    id,
    site_id: a.site || a.site_id,
    point_code: a.point,
    name: a.name || '',
    level: Number(a.level) || 2,
    level_name: a.level_name || '',
    state: Number(a.state) || 0,
    state_name: a.state_name || '',
    val: a.val == null ? null : Number(a.val),
    threshold: a.threshold == null ? null : Number(a.threshold),
    msg: a.msg || '',
    first_ts: a.first_ts || '',
    last_ts: a.last_ts || '',
    count: Number(a.count) || 1
  }
  if (i >= 0) list.value[i] = Object.assign({}, list.value[i], obj)
  else list.value.unshift(obj)
  // 关闭的从「当前报警」里移除；恢复的留着等确认
  if (obj.state === 3) list.value = list.value.filter(x => x.id !== id)
  list.value.sort((x, y) => String(y.last_ts).localeCompare(String(x.last_ts)))
  if (obj.state === 0 && (a.act === 'raise' || i < 0) && P.value.blinkNew !== false) blink(id)
}

function blink(id) {
  const s = new Set(freshSet.value)
  s.add(id)
  freshSet.value = s
  setTimeout(() => {
    const t = new Set(freshSet.value)
    t.delete(id)
    freshSet.value = t
  }, 3000)
}

function connect() {
  disconnect()
  const token = localStorage.getItem('token') || ''
  const site = P.value.source === 'global' ? '' : (props.env.site || '')
  const qs = new URLSearchParams({ token })
  if (site) qs.set('site', site)
  try {
    es = new EventSource('/api/alarm/subscribe?' + qs.toString())
    es.addEventListener('snapshot', (e) => {
      sseOk.value = true
      retry = 0
      try {
        const d = JSON.parse(e.data)
        list.value = (d.items || []).map(x => Object.assign({}, x, {
          state: Number(x.state), level: Number(x.level)
        })).sort((a, b) => String(b.last_ts).localeCompare(String(a.last_ts)))
      } catch (err) { /* 数据坏一条不影响已有列表 */ }
      scrollEnd()
    })
    es.addEventListener('alarm', (e) => {
      sseOk.value = true
      try { upsert(JSON.parse(e.data)) } catch (err) { /* 同上 */ }
      scrollEnd()
    })
    es.onerror = () => {
      sseOk.value = false
      // EventSource 自己会重连，但 token 过期（401）它不会换 token —— 退避重连一次拿新 token
      retry++
      if (retry >= 3) {
        retry = 0
        setTimeout(() => { if (!document.hidden) connect() }, 3000)
      }
    }
  } catch (e) {
    sseOk.value = false
  }
}

function disconnect() {
  if (es) { try { es.close() } catch (e) { /* 已关闭 */ } es = null }
}

function scrollEnd() {
  if (P.value.autoScroll === false) return
  setTimeout(() => { if (body.value) body.value.scrollTop = 0 }, 30)
}

async function ack(a) {
  if (edit.value) return
  try {
    await post('/api/alarm/' + a.id + '/ack', { note: '' }, { silent: true })
    upsert({ id: a.id, state: 1, state_name: '已确认', site: a.site_id, point: a.point_code, act: 'ack' })
  } catch (e) {
    props.env.toast('确认失败：' + (e && e.message ? e.message : ''), 'error')
  }
}
async function doClose(a) {
  if (edit.value) return
  try {
    await post('/api/alarm/' + a.id + '/close', {}, { silent: true })
    upsert({ id: a.id, state: 3, state_name: '已关闭', site: a.site_id, point: a.point_code, act: 'close' })
  } catch (e) {
    props.env.toast('关闭失败：' + (e && e.message ? e.message : ''), 'error')
  }
}

onMounted(connect)
onUnmounted(disconnect)
watch(() => [props.env.site, P.value.source], connect)
onMounted(() => {
  const now = Date.now()
  startStr.value = toLocalInput(now - spanMin.value * 60000)
  endStr.value = toLocalInput(now)
})
</script>

<style scoped>
.ctl { width: 100%; height: 100%; box-sizing: border-box; display: flex; flex-direction: column; overflow: hidden;
  background: #0b1622; color: #cfe4f7; font-size: 12px; }
.ctl-edit { pointer-events: auto; }
.hd { display: flex; align-items: center; gap: 6px; padding: 3px 6px; border-bottom: 1px solid #16283d; flex: 0 0 auto; }
.ttl { font-weight: 600; color: #c3ddf5; }
.tag { font-size: 10px; color: #5b82a8; border: 1px solid #16283d; border-radius: 2px; padding: 0 4px; }
.sp { flex: 1 1 auto; }
.cnt { font-size: 10px; color: #7fa8cc; }
.cnt.hot { color: #f87171; font-weight: 600; }
.sse { color: #475569; font-size: 9px; }
.sse.on { color: #22c55e; }
.body { flex: 1 1 auto; overflow: auto; min-height: 0; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 1px 5px; border-bottom: 1px solid #12233a; white-space: nowrap; text-align: left; font-size: 11px; }
th { position: sticky; top: 0; background: #102338; color: #9fc3e8; font-weight: 500; z-index: 1; }
.c-time { width: 1%; color: #7fa8cc; }
.c-site { width: 1%; }
.c-level { width: 1%; }
.c-state { width: 1%; }
.c-count { width: 1%; text-align: right; }
.c-msg { max-width: 240px; overflow: hidden; text-overflow: ellipsis; }
.c-act { width: 1%; text-align: right; }
tr.lv1 td { color: #fbbf24; }
tr.lv2 td { color: #f87171; }
tr.lv3 td { color: #ef4444; font-weight: 600; }
tr.acked td { opacity: .62; }
tr.fresh { animation: al-blk .8s ease-in-out 3; }
@keyframes al-blk { 0%, 100% { background: transparent; } 50% { background: rgba(248, 113, 113, .28); } }
.empty { text-align: center; color: #4a6d92; padding: 14px 0; }
.btn { font-size: 10px; padding: 0 5px; margin-left: 3px; background: #123a5c; color: #cfe4f7;
  border: 1px solid #1e3a5f; border-radius: 2px; cursor: pointer; line-height: 15px; }
.btn:hover { background: #17456b; }
.btn.ghost { background: transparent; color: #7fa8cc; }

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
