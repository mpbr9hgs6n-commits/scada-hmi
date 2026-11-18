// scada-deck 视觉基准（提示词 11）：设计 token、介质颜色、质量码三态、调试参数。
// 视觉规则与色值来自 github.com/agentthink/scada-deck（MIT，NOTICE 有归属声明）。
//
// 八条实战原则（2.1.1）里第 3/4/6/8 条对观感影响最大，落在本文件：
//   3 介质要有真实颜色 → MEDIUM 枚举（组件里不许手填色值）
//   8 离线/坏质量显示 -- 不是 0 → boundState 三态
// 第 4 条（设备不整体染色）在 render.js 的 VECTOR 状态色里；第 6 条（标签分级）后续做。

// —— 设计 token（照抄 scada-deck scenarios/water-treatment/21 的 :root，别"优化"）——
export const TK = {
  bg: '#071017',
  surface1: '#0a1722',
  surface2: '#0f2232',
  surface3: '#152e42',
  line: '#1b384e',
  lineLight: '#285270',
  accent: '#36c2ff',
  success: '#2fd67e',
  warning: '#f5aa39',
  danger: '#ff4d4f',
  offline: '#607382',
  text1: '#f0f5fa',
  text2: '#9ab0c2',
  text3: '#627c90',
  pipeBase: '#1b374d',
  // 数字等宽（防跳动）——所有数值组件必须用
  numFont: '"Bahnschrift","DIN Alternate",Consolas,monospace'
}

// —— 介质颜色（原则 3）：罐/管道/流向箭头一律从这里取色，不允许手填 ——
export const MEDIUM = {
  influent: { name: '进水（浑浊）', color: '#6b7a55', opacity: 0.85 },
  effluent: { name: '出水（清澈）', color: '#36c2ff', opacity: 0.75 },
  sludge:   { name: '污泥',        color: '#7a4b32', opacity: 0.9 },
  chemical: { name: '药剂',        color: '#b06bd4', opacity: 0.7 },
  clean:    { name: '清水',        color: '#8fd6ff', opacity: 0.6 },
  air:      { name: '空气',        color: '#a8bac8', opacity: 0.4 },
  steam:    { name: '蒸汽',        color: '#e8f4ff', opacity: 0.5 },
  gas:      { name: '沼气',        color: '#c9d47a', opacity: 0.45 }
}

/** 取介质色。未配/配错 → 清水（别让组件裸奔） */
export function mediumOf(item) {
  const key = item && item.medium
  return MEDIUM[key] || MEDIUM.clean
}

// 介质下拉选项（props.js / 属性面板用）
export const MEDIUM_OPTIONS = Object.entries(MEDIUM).map(([k, v]) => ({ value: k, label: v.name }))

// —— 质量码三态（提示词 11 §3.1 ①：所有绑定组件共用这一个，禁止各写各的）——
// values 里的条目：{ val, ts, q }，q：0=GOOD 1=BAD（Redis 质量码，网关断线写 1 不写 0）
// 返回 { found, val, state }：state = good / bad / stale / nodata
//   bad    读失败（q=1）
//   stale  超过 STALE_MS 没更新（含"站点离线"——离线后采集停了，点位时间戳不再前进，
//          超阈值后整站一起变 stale，动画停、数值 --，不需要每个组件单独判断离线）
//   nodata 没绑变量 / 从来没收到过值
//
// 🔴 stale 阈值 = 该点位「有效周期」× 3，有效周期取两者较大值：
//      pollMs —— 点位配置的 poll_ms（NULL 时继承站点 default_poll_ms）
//      obsMs  —— 前端实测的相邻两次更新间隔（指数平滑）
//    为什么要两个：poll_ms 是"配置意图"，网关按站点分片轮询，真实周期可能长很多
//    （实测 S001 配 500ms，实际 4s）。只信配置会把好数据判成 stale，只信实测则首帧没样本。
//    STALE_MIN_MS 是下限（10s），防 100ms 周期点位因一次网络抖动就闪 --；
//    STALE_MS 是无任何周期信息时（老接口/无快照）的兜底。
export const STALE_MS = 15000
export const STALE_MIN_MS = 10000
export const STALE_FACTOR = 3

/** 该条值记录的 stale 阈值（ms） */
export function staleLimit(rec) {
  const poll = Number(rec && rec.pollMs)
  const obs = Number(rec && rec.obsMs)
  const base = Math.max(poll || 0, obs || 0)
  if (base > 0) return Math.max(STALE_MIN_MS, base * STALE_FACTOR)
  return STALE_MS
}

export function boundState(rec, now) {
  if (!rec) return { found: false, val: null, state: 'nodata' }
  const val = rec.val
  const q = Number(rec.q || 0)
  const ts = Number(rec.ts || 0)
  if (q === 1) return { found: true, val: null, state: 'bad' }
  if (val === null || val === undefined) return { found: true, val: null, state: 'bad' }
  if (!ts || (now || Date.now()) - ts > staleLimit(rec)) return { found: true, val, state: 'stale' }
  return { found: true, val, state: 'good' }
}

// 三态 → 状态点颜色（原则 4：绿=正常 琥珀=预警 红=报警 灰=离线；不给颜色第二含义）
export const DOT_OF = { good: '#2fd67e', stale: '#f5aa39', bad: '#607382', nodata: '#607382' }

/** 三态 → 显示文本：非 good 一律 '--'，绝不显示 0（原则 8，与 BAD 显示灰是同一条） */
export function displayOf(rec, now) {
  const s = boundState(rec, now)
  // dtype 一起带出去：数值显示要按点位类型决定小数位（bool/整数 0 位，浮点按 decimals）。
  // 不在这里透传的话，render 那边永远拿不到类型，只能一律 toFixed(2)。
  return { ...s, dtype: (rec && rec.dtype) || undefined,
           display: s.state === 'good' ? s.val : '--', dot: DOT_OF[s.state] }
}


/**
 * 数值按点位类型格式化 —— 全组态唯一的数值显示入口。
 *
 * 为什么必须收敛成一个函数：以前 9 处各写 item.decimals ?? 2，
 * 导致 bool 显示 1.00、int16 显示 123.00。类型判断只写一次，以后加控件不会再漏。
 *
 * dtype 取不到时退回 item.decimals：老画面没有 dtype 字段，
 * 不能因此变成 NaN 或报错。
 */
export function fmtNum(val, rec, item) {
  if (val === null || val === undefined || val === '') return '--'
  const n = Number(val)
  if (!isFinite(n)) return '--'
  const dt = String((rec && rec.dtype) || (item && item.dtype) || '').toLowerCase()
  if (dt === 'bool') return n ? '1' : '0'
  if (['byte', 'int16', 'uint16', 'int32', 'uint32', 'int64', 'uint64'].includes(dt)) {
    return String(Math.round(n))
  }
  const dec = (item && item.decimals !== undefined && item.decimals !== null)
    ? Number(item.decimals) : 2
  return n.toFixed(Math.max(0, Math.min(6, isFinite(dec) ? dec : 2)))
}

// —— 调试与截图参数（提示词 11 §2.1.2：只影响展示层，不改后端数据）——
// ?demo=0 全部按离线渲染    ?fault=1 第一个可故障设备置故障
// ?freeze=1 冻结数值刷新    ?fx=0 关闭所有动画
// 生产构建（import.meta.env.PROD）必须再带 ?debug=1 才生效，平时不干扰运行画面。
const QUERY = (() => {
  try { return new URLSearchParams(location.search) } catch (e) { return null }
})()

const PROD = typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.PROD
const UNLOCKED = !!QUERY && QUERY.get('debug') === '1'

export const DECK_DEBUG = {
  demo:   !PROD || UNLOCKED ? (QUERY && QUERY.get('demo') !== null ? QUERY.get('demo') !== '0' : null) : null,
  fault:  !PROD || UNLOCKED ? (QUERY && QUERY.get('fault') === '1') : false,
  freeze: !PROD || UNLOCKED ? (QUERY && QUERY.get('freeze') === '1') : false,
  fx:     !PROD || UNLOCKED ? (QUERY && QUERY.get('fx') === '0' ? false : null) : null
}

/** demo=0：把一条记录改成"读失败"，用于验收"离线态显示 -- 不是 0" */
export function demoFilter(rec) {
  if (DECK_DEBUG.demo === false) return { val: null, ts: 0, q: 1 }
  return rec
}
