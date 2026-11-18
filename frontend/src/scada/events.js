// 事件系统（P5）—— 让画面"点得动"
//
// 事件键名照 WinCC 官方事件表，不自创：
//   mouse.click / press.left / press.right / release.left / release.right
//   focus.change
//   object.change / gesture / picture.open / picture.close
//   <attr>.change（任意属性变化）
//
// mouse.leave 官方表里没有：WinCC 靠 "Mouse click" 事件的按下/松开属性配合，
// Web 的 DOM 里 mouseup 会绑在 document 上，按住拖出对象后 release 不会在对象上触发，
// 瞬时按钮的线圈就永远停在 1（现场表现=泵停不下来）。所以补这一条，并在 UI 上注明。
//
// 一期动作只做 Direct Connection（官方定位：画面内最快、性能最高）。
// VBS / C 动作在 UI 列出但标"二期支持"。
//
// 三条硬规矩：
// 1) 编辑态不执行鼠标动作（点对象是选中），只执行 object.change / picture.open 这类无副作用事件
// 2) 写点位必须走完整链路：rw 校验 → 写 → 回读比对 → 审计，失败绝不静默
// 3) 同一个按钮 300ms 内不重复提交（防连点导致设备抖动）；
//    但"同一个值再写一次"才丢，被上一条还没回来的写挡住时要把终值记下来补发，
//    否则瞬时按钮的松开会被吞掉，线圈停在 1（现场=泵停不下来）

import { applyAttrValues } from './dyn'
import { evaluate } from './expr'
import { splitTag } from './runtime'
import { post } from '../utils/request'
// 变量可能是 {site,point} 对象，拼人类可读文本必须走 tagText，
// 否则动作列会显示 [object Object]
import { tagText } from './varbind'

const WRITE_GAP = 300      // 防连点：同按钮 300ms 内不重复提交

// —— 事件目录（UI 的左树与右表都从这里来）——
// cn = 界面显示的中文名，key 仍是内部标识（存进画面 json，不能随便改）
export const EVENTS = {
  'mouse.press.left': { g: 'mouse', cn: '按下', d: '鼠标左键按下（按住 = 写 1，松开 = 写 0）' },
  'mouse.release.left': { g: 'mouse', cn: '松开', d: '鼠标左键松开（按下时在对象上）' },
  'mouse.click': { g: 'mouse', cn: '单击', d: '光标在对象上，按下并释放时触发' },
  'mouse.press.right': { g: 'mouse', cn: '右键按下', d: '鼠标右键按下' },
  'mouse.release.right': { g: 'mouse', cn: '右键松开', d: '鼠标右键松开' },
  'mouse.leave': { g: 'mouse', cn: '移出', d: '鼠标移出对象（官方表里没有，瞬时按钮必须要，我们补的）', ours: true },
  'focus.change': { g: 'focus', cn: '焦点变化', d: '焦点取得/切换（Tab 序列、鼠标点击都可触发）' },
  'object.change': { g: 'misc', cn: '对象变化', d: '对象至少一个属性变化时' },
  gesture: { g: 'misc', cn: '触摸手势', d: '滑动 / 长按 / 双击', p: 'gesture' },
  'picture.open': { g: 'misc', cn: '画面打开', d: '画面打开时触发一次' },
  'picture.close': { g: 'misc', cn: '画面关闭', d: '画面关闭时触发一次' }
}

export const EVENT_GROUPS = [
  { key: 'mouse', label: '鼠标' },
  { key: 'focus', label: '焦点' },
  { key: 'misc', label: '其他' },
  { key: 'attr', label: '对象属性' }
]

export const GESTURES = [
  { v: 'longpress', t: '长按（>600ms）' },
  { v: 'swipe', t: '滑动（位移 >30px）' },
  { v: 'doubletap', t: '双击' }
]

// 属性事件的目标属性：与动态化用同一份目录（能动态化的属性才谈得上"变化"）
export function eventListOf(type, dynAttrs) {
  const out = []
  for (const [k, v] of Object.entries(EVENTS)) out.push({ key: k, ...v })
  if (dynAttrs) for (const a of dynAttrs) out.push({ key: a.key + '.change', g: 'attr', d: '属性「' + a.label + '」变化时' })
  return out
}

export function isEventKey(k) {
  return !!EVENTS[k] || /\.change$/.test(k)
}

export function eventLabel(k) {
  // 界面统一显示中文名，内部 key 不变（画面 json 里存的是 key）
  const e = EVENTS[k]
  return (e && e.cn) || k
}

// —— 动作：预设（下拉首选，底层都落到 Direct Connection 结构）——
export const PRESETS = [
  { v: 'setTag', t: '置位（写 1 到变量）' },
  { v: 'resetTag', t: '复位（写 0 到变量）' },
  { v: 'toggleTag', t: '取反（读当前值 → 取反 → 写回）' },
  { v: 'momentary', t: '瞬时（按下写 A，松开写 B）' },
  { v: 'openPicture', t: '打开画面' },
  { v: 'closePicture', t: '关闭当前画面' },
  { v: 'custom', t: '自定义直接连接' }
]

export function blankAction() {
  return {
    type: 'direct',
    preset: 'setTag',
    src: { kind: 'constant', value: 1 },
    dst: { kind: 'tag', expr: '', sync: 'direct' },
    msg: ''
  }
}

// 预设 → action（瞬时由调用方展开成三条事件）
export function actionFromPreset(preset, prev) {
  const a = blankAction()
  a.preset = preset
  const expr = (prev && prev.dst && prev.dst.expr) || ''
  if (preset === 'setTag') {
    a.src = { kind: 'constant', value: 1 }
    a.dst = { kind: 'tag', expr, sync: 'direct' }
  } else if (preset === 'resetTag') {
    a.src = { kind: 'constant', value: 0 }
    a.dst = { kind: 'tag', expr, sync: 'direct' }
  } else if (preset === 'toggleTag') {
    a.src = { kind: 'tag', expr, sync: 'direct', readOnly: true }
    a.dst = { kind: 'tag', expr, sync: 'direct' }
    a.op = 'toggle'
  } else if (preset === 'momentary') {
    a.src = { kind: 'constant', value: 1 }
    a.dst = { kind: 'tag', expr, sync: 'direct' }
    a.off = 0
  } else if (preset === 'openPicture') {
    a.src = { kind: 'constant', value: '' }
    a.dst = { kind: 'window', attr: 'openPicture' }
  } else if (preset === 'closePicture') {
    a.src = { kind: 'constant', value: null }
    a.dst = { kind: 'window', attr: 'closePicture' }
  }
  return a
}

// 瞬时动作默认绑三条，且 mouse.leave 不允许删（任务书单条强调）
export const MOMENTARY_KEYS = ['mouse.press.left', 'mouse.release.left', 'mouse.leave']

export function humanAction(a) {
  if (!a) return ''
  if (a.type === 'vbs' || a.type === 'c') return (a.type === 'vbs' ? 'VBS' : 'C') + ' 动作（二期支持）'
  const d = a.dst || {}
  const s = a.src || {}
  // d.expr / s.expr 可能是对象，必须 tagText 归一化，否则显示 [object Object]
  const target = d.kind === 'tag' ? (tagText(d.expr) || '未选变量')
    : d.kind === 'attr' ? ((d.objectName || '?') + '.' + (d.attr || '?'))
      : (d.attr === 'openPicture' ? '打开画面' : d.attr === 'closePicture' ? '关闭画面' : '画面.' + (d.attr || '?'))
  const src = s.kind === 'constant' ? String(s.value)
    : s.kind === 'tag' ? ('[' + (tagText(s.expr) || '?') + ']')
      : ((s.objectName || '?') + '.' + (s.attr || '?'))
  if (a.preset === 'toggleTag' || a.op === 'toggle') return '取反 → ' + target
  return src + ' → ' + target
}

// —— 工具 ——
function findRec(st, name) {
  if (!st || !st.items) return null
  return st.items.find(r => r.item && r.item.name === name) || null
}

function fireOn(rec, key, ctx, st, param, detail) {
  const ev = rec.item && rec.item.events && rec.item.events[key]
  if (!ev || !ev.action) return false
  // 手势/按键这类带参数的事件：配了参数就只认这一个
  if (key === 'gesture' && ev.gesture && detail && ev.gesture !== detail.gesture) return false
  const n = Number(rec.node && rec.node.dataset.evCount || 0) + 1
  if (rec.node) rec.node.dataset.evCount = String(n)
  execAction(rec, ev.action, ctx, st, key)
  return true
}

function readValue(rec, attr, rt) {
  if (!rec) return undefined
  const item = rec.item || {}
  if (attr === 'value') {
    // I/O 域 / 液位罐的显示值：优先看实时值缓存，其次看 DOM 上的上一次渲染
    const t = item.dyn && item.dyn.value && item.dyn.value.mode === 'tag' ? item.dyn.value.expr
      : item.dyn && item.dyn.value && item.dyn.value.mode === 'indirect' ? item.dyn.value.nameExpr : null
    if (t && rt && rt.evalCtx) {
      const r = evaluate(t, rt.evalCtx())
      if (r.ok) return r.value
    }
    if (rec.R && rec.R.num) return Number(rec.R.num.textContent)
  }
  return item[attr]
}

function resolveSrc(src, rec, ctx, st) {
  if (!src) return undefined
  if (src.kind === 'constant') return src.value
  if (src.kind === 'attr') {
    const r = findRec(st, src.objectName)
    return readValue(r, src.attr, ctx.rt)
  }
  if (src.kind === 'tag') {
    const rt = ctx.rt
    if (!rt || !rt.evalCtx) return undefined
    // 4.3 对象变量：直接按 tag 读，不要先丢给表达式引擎
    // （对象会被 String 成 "[object Object]"，白跑一次解析还留一条语法错）
    if (src.expr && typeof src.expr === 'object') {
      const { site, code } = splitTag(src.expr)
      if (!code) return undefined
      const v = rt.read((site || rt.site) + '.' + code)
      return v && v.found ? v.val : undefined
    }
    const r = evaluate(src.expr, rt.evalCtx())
    if (r.ok) return r.value
    // 表达式可能是裸点位名，兜底按当前站点读一次
    const { site, code } = splitTag(src.expr)
    if (!code) return undefined
    const v = rt.read((site || rt.site) + '.' + code)
    return v && v.found ? v.val : undefined
  }
  return undefined
}

function toast(ctx, text, type) {
  if (ctx.onToast) ctx.onToast(text, type || 'info')
}

function isOn(v) {
  if (typeof v === 'string') return v !== '' && v !== '0' && v.toLowerCase() !== 'false'
  return !!Number(v) || v === true
}

// —— 执行一条动作 ——
function execAction(rec, action, ctx, st, evKey) {
  if (!action) return
  if (action.type === 'vbs' || action.type === 'c') {
    toast(ctx, '当前版本请用直接连接（VBS/C 动作二期支持）', 'warning')
    return
  }
  if (action.type !== 'direct') return

  const dst = action.dst || {}
  let value

  // 取反：读当前值 → 取反
  if (action.preset === 'toggleTag' || action.op === 'toggle') {
    const cur = resolveSrc(action.src && action.src.kind === 'tag' ? action.src : dst, rec, ctx, st)
    if (cur === undefined || cur === null) {
      toast(ctx, '取反失败：读不到当前值', 'error')
      return
    }
    value = isOn(cur) ? 0 : 1
  } else {
    value = resolveSrc(action.src, rec, ctx, st)
  }

  // 目标：变量（写回链路）
  if (dst.kind === 'tag') {
    doWrite(dst.expr, value, rec, ctx, action, evKey)
    return
  }

  // 目标：对象属性
  if (dst.kind === 'attr') {
    const tr = findRec(st, dst.objectName)
    if (!tr) { toast(ctx, '目标对象不存在：' + (dst.objectName || '?'), 'error'); return }
    if (tr === rec && action.src && action.src.kind === 'attr' && action.src.objectName === dst.objectName) return
    setAttr(tr, dst.attr, value, ctx, st)
    if (action.msg) post('/api/scada/oplog', { site: ctx.rt && ctx.rt.site, msg: action.msg }, { silent: true }).catch(() => {})
    return
  }

  // 目标：当前画面
  if (dst.kind === 'window') {
    const sd = st.data || {}
    if (dst.attr === 'openPicture') {
      if (ctx.openPage) ctx.openPage(value)
      else toast(ctx, '这里不能打开画面（编辑态）', 'warning')
    } else if (dst.attr === 'closePicture') {
      if (ctx.closePage) ctx.closePage()
      else toast(ctx, '这里不能关闭画面（编辑态）', 'warning')
    } else if (dst.attr === 'bg') {
      if (sd) sd.bg = String(value)
      const stage = st.inner && st.inner.parentElement
      if (stage) stage.style.background = String(value)
    } else {
      toast(ctx, '画面属性暂不支持：' + dst.attr, 'warning')
    }
    if (action.msg) post('/api/scada/oplog', { site: ctx.rt && ctx.rt.site, msg: action.msg }, { silent: true }).catch(() => {})
  }
}

// 写对象属性：走与动态化同一套施值逻辑，改完把结构签名同步掉（否则下次重绘会整棵重建）
export function setAttr(rec, attr, value, ctx, st) {
  if (!rec || !rec.item) return
  const item = rec.item
  item[attr] = value
  // 先 restyle 再施值：restyle 按 item 属性整刷一遍样式，顺序反了会把刚改的颜色刷回去
  if (st && st.restyle) { try { st.restyle() } catch (e) { /* 忽略 */ } }
  try {
    applyAttrValues(rec, item, { [attr]: { value } })
  } catch (e) { /* 单个属性异常不影响其他 */ }
  // 属性变化事件（<attr>.change / object.change）在改完后补发一轮
  fireAttrChange(ctx, st, item, [attr])
}

// 写点位：rw 校验 → 写 → 回读比对（后端做）→ 审计；防连点
function doWrite(expr, value, rec, ctx, action, evKey) {
  const rt = ctx.rt
  // expr 可能是 {site, point} 对象（VarPicker 选出来的），也可能是 "S001.X" 字符串。
  // 早期这里 String(expr)，对象变 "[object Object]" → 后端报「点位不存在：[object Object]」。
  const { site, code } = splitTag(expr)
  const raw = site ? site + '.' + code : code
  if (!code) { toast(ctx, '没有配变量，写不了', 'error'); return }
  const s = site || (rt && rt.site) || ''
  if (!s || !code) { toast(ctx, '变量要写成 站点.点位，如 S001.PUMP1_RUN', 'error'); return }
  const ro = rec && rec.__rw && rec.__rw[raw]
  if (ro === 0) { toast(ctx, '该点位只读，禁止写入', 'error'); return }

  const now = Date.now()
  if (rec) {
    // 防连点只该吃掉"同一个值又点了一遍"。被上一条还没回来的写挡住时直接 return，
    // 瞬时按钮的松开就没了：按住→拖出→松手，mouseleave 撞在飞行中的写上面被吞掉，
    // 线圈永远停在 1（现场表现就是泵停不下来）。所以这里改成"记下终值，等回来立刻补发"。
    const dup = rec.__lastVal !== undefined && String(rec.__lastVal) === String(value)
    if (rec.__writing || (dup && rec.__lastWrite && now - rec.__lastWrite < WRITE_GAP)) {
      if (!dup) rec.__pending = { expr: raw, value, action }
      return
    }
    rec.__lastWrite = now
    rec.__lastVal = value
    rec.__writing = true
  }

  post('/api/write', { site: s, point: code, value: Number(value) }, { silent: true })
    .then((r) => {
      toast(ctx, '已写入 ' + (r && r.value !== undefined ? r.value : value), 'success')
      if (action && action.msg) post('/api/scada/oplog', { site: s, point: code, msg: action.msg }, { silent: true }).catch(() => {})
    })
    .catch((e) => {
      const msg = (e && e.message) || ''
      let text = msg
      if (/写入超时|网关/.test(msg)) text = '写入超时，请检查网关'
      else if (/回读/.test(msg)) text = msg
      else if (msg) text = msg
      else text = '写入失败'
      toast(ctx, text, 'error')
    })
    .finally(() => {
      if (!rec) return
      rec.__writing = false
      // 补发被挡住的那一次（最后一次想要的终值）：瞬时按钮的松开就靠这一下落地
      const p = rec.__pending
      if (p) { rec.__pending = null; doWrite(p.expr, p.value, rec, ctx, p.action, evKey) }
    })
}

// item 里存的是 fill / stroke / color，事件目录里叫 fillColor / strokeColor / fontColor
// （跟动态化同一套名字，操作员只记一套）。改属性时两个名字都发一遍，谁配了谁响应。
const PROP_ALIAS = { fill: 'fillColor', stroke: 'strokeColor', color: 'fontColor' }

// 属性变化：改一个属性 → 该属性 .change + object.change
export function fireAttrChange(ctx, st, item, keys) {
  if (!st || !item) return
  const rec = (st.items || []).find(r => r.item === item)
  if (!rec) return
  for (const k of keys || []) {
    fireOn(rec, k + '.change', ctx, st)
    const alias = PROP_ALIAS[k]
    if (alias) fireOn(rec, alias + '.change', ctx, st)
  }
  fireOn(rec, 'object.change', ctx, st)
}

// 收集画面里所有"写点位"的目标（要在绑定时批量取 rw，rw=0 才能提前禁用按钮）
function collectTags(st) {
  const out = new Set()
  for (const rec of (st.items || [])) {
    const ev = (rec.item && rec.item.events) || {}
    for (const k of Object.keys(ev)) {
      const a = ev[k] && ev[k].action
      if (!a || a.type !== 'direct') continue
      const d = a.dst || {}
      if (d.kind === 'tag' && d.expr) {
        const { site, code } = splitTag(d.expr)
        out.add((site || '') + '.' + code)
      }
      const s = a.src || {}
      if (s.kind === 'tag' && s.expr) {
        const { site, code } = splitTag(s.expr)
        out.add((site || '') + '.' + code)
      }
    }
  }
  return [...out]
}

// —— 绑定 ——
// ctx: { rt, interactive, onToast, openPage, closePage, resolveTags }
export function attachEvents(container, ctx) {
  const st = container && container.__scada
  if (!st || !st.items) return { bound: 0 }
  let bound = 0
  for (const rec of st.items) {
    const ev = (rec.item && rec.item.events) || {}
    const keys = Object.keys(ev).filter(k => ev[k] && ev[k].action)
    const sig = JSON.stringify(keys.map(k => [k, ev[k].action, ev[k].key, ev[k].gesture]))
    if (rec.node && rec.node.__evSig === sig) continue
    if (rec.node) { rec.node.__evSig = sig; rec.node.__evTs = null }
    bindOne(rec, ctx, st)
    if (keys.length) bound++
  }
  // 变量可写性：rw=0 的对象标成禁用（悬停提示"只读点位"）
  applyReadonly(st, ctx)
  bindDocMouseup(st, ctx)
  if (ctx.interactive !== false
      && st.items.some(r => r.item && r.item.events && r.item.events['picture.open'])) {
    if (!container.__picOpened) {
      container.__picOpened = true
      for (const rec of st.items) fireOn(rec, 'picture.open', ctx, st)
    }
  }
  return { bound }
}

// document 级 mouseup 兜底：按住对象拖到画面外再松手时，mouseup 落在 document 上，
// 对象自己的 mouseup 收不到，只剩 mouse.leave 一条命；而 leave 一旦被"上一条写还没回来"
// 挡掉，瞬时按钮的线圈就停在 1（现场表现=泵停不下来、阀门关不上）。
// 所以按过就记账，松手时不管落在哪儿都执行一次 release。每画面只挂一条，销毁时摘掉。
function bindDocMouseup(st, ctx) {
  if (st.__docUp) return
  st.__docUp = (e) => {
    const key = e.button === 0 ? 'mouse.release.left' : e.button === 2 ? 'mouse.release.right' : null
    if (!key) return
    const set = key === 'mouse.release.left' ? st.__armedL : st.__armedR
    if (!set || !set.size) return
    const recs = [...set]
    set.clear()
    for (const rec of recs) fireOn(rec, key, ctx, st)
  }
  document.addEventListener('mouseup', st.__docUp)
}

// 画面关闭：由调用方在卸载时调一次
export function firePictureClose(container, ctx) {
  const st = container && container.__scada
  if (!st || !st.items) return
  for (const rec of st.items) fireOn(rec, 'picture.close', ctx, st)
}

// 手动触发（面板里的"测试"按钮）：不切运行态也执行一次
export function testEvent(item, key, ctx) {
  const st = ctx && ctx.container && ctx.container.__scada
  if (!st) return false
  const rec = (st.items || []).find(r => r.item === item) || { item, node: null, R: null }
  const ev = (item.events || {})[key]
  if (!ev || !ev.action) return false
  execAction(rec, ev.action, ctx, st, key)
  return true
}

function bindOne(rec, ctx, st) {
  const node = rec.node
  const item = rec.item
  const ev = (item && item.events) || {}
  if (!node) return
  const has = (k) => !!(ev[k] && ev[k].action)
  const fire = (k, detail) => fireOn(rec, k, ctx, st, null, detail)
  const live = ctx.interactive !== false

  // 编辑态：鼠标/键盘/焦点一律不执行（点对象是选中，不能顺手写 PLC）
  if (live) {
    if (has('mouse.click')) node.addEventListener('click', (e) => { e.stopPropagation(); fire('mouse.click') })
    // 按下过没松开的记在画面级集合里（st.__armedL / __armedR）：
    // 松开那一下必须一定执行，瞬时按钮的归零全靠它，见文件末尾的 document 兜底
    if (has('mouse.press.left')) node.addEventListener('mousedown', (e) => { if (e.button === 0) { (st.__armedL || (st.__armedL = new Set())).add(rec); fire('mouse.press.left') } })
    if (has('mouse.press.right')) node.addEventListener('mousedown', (e) => { if (e.button === 2) { (st.__armedR || (st.__armedR = new Set())).add(rec); fire('mouse.press.right') } })
    if (has('mouse.release.left')) node.addEventListener('mouseup', (e) => { if (e.button === 0) { st.__armedL && st.__armedL.delete(rec); fire('mouse.release.left') } })
    if (has('mouse.release.right')) node.addEventListener('mouseup', (e) => { if (e.button === 2) { st.__armedR && st.__armedR.delete(rec); fire('mouse.release.right') } })
    if (has('mouse.release.right') || has('mouse.press.right')) node.addEventListener('contextmenu', (e) => e.preventDefault())
    // 瞬时按钮的第三条命：按住拖出对象后 mouseup 落在 document 上，只有 leave 能把线圈复位
    if (has('mouse.leave')) node.addEventListener('mouseleave', () => fire('mouse.leave'))

    // 键盘事件已移除（用户要求只留鼠标），focus.change 自己拿 tabIndex
    if (has('focus.change')) {
      node.tabIndex = 0
      node.addEventListener('focus', () => fire('focus.change'))
      node.addEventListener('blur', () => fire('focus.change'))
    }
    if (has('gesture')) bindGesture(node, fire)
  }
}

function bindGesture(node, fire) {
  let t0 = 0, moved = false, lpTimer = 0, lastTap = 0, sx = 0, sy = 0
  node.addEventListener('touchstart', (e) => {
    const t = e.touches[0]
    t0 = Date.now(); moved = false; sx = t.clientX; sy = t.clientY
    lpTimer = setTimeout(() => { if (!moved) fire('gesture', { gesture: 'longpress' }) }, 600)
  }, { passive: true })
  node.addEventListener('touchmove', (e) => {
    const t = e.touches[0]
    if (Math.abs(t.clientX - sx) > 10 || Math.abs(t.clientY - sy) > 10) moved = true
  }, { passive: true })
  node.addEventListener('touchend', (e) => {
    clearTimeout(lpTimer)
    const t = e.changedTouches[0]
    const dx = Math.abs(t.clientX - sx), dy = Math.abs(t.clientY - sy)
    if (dx > 30 || dy > 30) { fire('gesture', { gesture: 'swipe' }); return }
    if (moved) return
    const now = Date.now()
    if (now - lastTap < 300) { fire('gesture', { gesture: 'doubletap' }); lastTap = 0; return }
    lastTap = now
  }, { passive: true })
}

// rw=0 → 对象禁用 + 悬停提示"只读点位"
function applyReadonly(st, ctx) {
  const tags = collectTags(st)
  if (!tags.length) return
  if (st.__rwTags && st.__rwTags.join('|') === tags.join('|')) { paintReadonly(st); return }
  st.__rwTags = tags
  if (!ctx.resolveTags) return
  ctx.resolveTags(tags).then((list) => {
    const map = {}
    for (const x of list || []) if (x && x.tag) map[x.tag] = x.found ? x.rw : -1
    st.__rw = map
    paintReadonly(st)
  }).catch(() => {})
}

function paintReadonly(st) {
  const map = st.__rw || {}
  for (const rec of st.items || []) {
    const ev = (rec.item && rec.item.events) || {}
    const writable = []
    for (const k of Object.keys(ev)) {
      const a = ev[k] && ev[k].action
      if (a && a.dst && a.dst.kind === 'tag' && a.dst.expr) writable.push(a.dst.expr)
    }
    if (!writable.length) continue
    // 一个对象上只要有任一条写动作指向只读点位，就把该点位记下，点击时拦掉
    const ro = {}
    let allReadonly = true
    for (const t of writable) {
      const rw = map[t]
      ro[t] = rw
      if (rw !== 0) allReadonly = false
    }
    rec.__rw = ro
    const node = rec.node
    if (!node) continue
    if (allReadonly) {
      node.classList.add('scada-ro')
      node.title = '只读点位'
      node.dataset.ro = '1'
      const b = node.querySelector('button')
      if (b) { b.disabled = true; b.style.cursor = 'not-allowed'; b.title = '只读点位' }
    } else {
      node.classList.remove('scada-ro')
      if (node.dataset.ro) { node.removeAttribute('data-ro'); node.title = '' }
      const b = node.querySelector('button')
      if (b) { b.disabled = false; b.style.cursor = 'pointer'; b.title = '' }
    }
  }
}
