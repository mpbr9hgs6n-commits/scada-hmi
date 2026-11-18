// 组件模板（Faceplate）实例展开（P8）
//
// 官方 4.6：类型（type）里画对象，实例（instance）只是「使用地点」。
// 实例只存 { type:'faceplate', fptId, x,y,w,h, bindings:{PV:'S001.LEVEL'} }，
// **不拷贝模板 json** —— 拷贝了「改模板 → 所有实例同步变」这条立刻失效（任务书要点②）。
//
// 类型内部用 @PV / @RUN 引用接口变量：
//   { "type":"tank",  "dyn": { "height": { "mode":"tag", "expr":"@PV" } } }
//   { "type":"lamp",  "dyn": { "running": { "mode":"tag", "expr":"@RUN" } } }
// 实例上把 PV 绑成 S001.LEVEL，渲染时就把 @PV 换成 S001.LEVEL。
//
// 一条硬约束：@CurrentSite 是运行时的站点关键字，**不是**接口变量，永不替换。

const RESERVED = new Set(['CurrentSite'])
const VAR_RE = /@([A-Za-z_][A-Za-z0-9_]*)/g

export function ifaceOf(def) {
  return def && Array.isArray(def.iface) ? def.iface : []
}

export function cloneJson(o) {
  try {
    return JSON.parse(JSON.stringify(o))
  } catch (e) {
    return o
  }
}

// 某个接口变量在实例上的生效值：绑了就用绑定值，没绑退回模板里的默认值
export function valueOf(inst, iface, name) {
  const b = (inst && inst.bindings) || {}
  if (b[name] !== undefined && b[name] !== null && b[name] !== '') return b[name]
  const t = iface.find(x => x && x.name === name)
  if (t && t.default !== undefined && t.default !== null && t.default !== '') return t.default
  return ''
}

function replStr(s, inst, iface, stat) {
  if (s.indexOf('@') < 0) return s
  return s.replace(VAR_RE, (m, name) => {
    if (RESERVED.has(name)) return m          // @CurrentSite 原样留着
    if (!iface.some(t => t && t.name === name)) return m  // 不是接口变量，不碰
    const v = valueOf(inst, iface, name)
    if (v === '' || v === undefined) return m
    stat.replaced++
    return String(v)
  })
}

function walk(node, inst, iface, stat) {
  if (typeof node === 'string') return replStr(node, inst, iface, stat)
  if (Array.isArray(node)) return node.map(v => walk(v, inst, iface, stat))
  if (node && typeof node === 'object') {
    const out = {}
    for (const k of Object.keys(node)) out[k] = walk(node[k], inst, iface, stat)
    return out
  }
  return node
}

// 实例 + 模板定义 → 一份「已经把 @接口变量 换成实际变量」的对象数组
// 每次渲染都重新展开：改模板后实例自然跟着变（不缓存、不落库）
export function expandInstance(inst, def, outStat) {
  const src = (def && def.json && Array.isArray(def.json.items)) ? def.json.items : []
  const iface = ifaceOf(def)
  const stat = outStat || { replaced: 0 }
  const items = walk(src, inst || {}, iface, stat)
  return Array.isArray(items) ? items : []
}

// 模板没绑的接口变量：属性面板与列表页都用它提示「还差几个没绑」
export function unboundOf(inst, def) {
  const b = (inst && inst.bindings) || {}
  return ifaceOf(def).filter(t => t && !b[t.name]).map(t => t.name)
}

// 实例上绑定的全部变量名（铺站预览、模板用量统计用）
export function bindingsOf(inst) {
  const b = (inst && inst.bindings) || {}
  return Object.keys(b).map(k => b[k]).filter(v => v !== undefined && v !== null && v !== '')
}

// 模板原始尺寸（实例默认按它落地；缩放由实例 w/h 决定）
export function sizeOf(def) {
  const w = Number(def && def.w) || 200
  const h = Number(def && def.h) || 200
  return { w, h }
}

// 在画面 json 里找某个模板的全部实例（列表页统计「被用了几次」）
export function instancesOf(items, fid) {
  const out = []
  const walkIn = (arr) => {
    for (const it of arr || []) {
      if (!it) continue
      if (it.type === 'faceplate' && Number(it.fptId) === Number(fid)) out.push(it)
      if (Array.isArray(it.items)) walkIn(it.items)
    }
  }
  walkIn(items)
  return out
}
