// 动态化（P4）—— 把「变量值」变成「画布上的变化」
//
// 官方五种动态化机制，术语照抄，不自创：
//   ① 直接变量连接 tag       "dyn": { "mode":"tag", "expr":"S001.LEVEL" }
//   ② 间接变量连接 indirect  "dyn": { "mode":"indirect", "nameExpr":"@CurrentSite + '.LEVEL'" }
//   ③ 动态对话框   dialog    trigger / formula / dataType / ranges / other / evalTagStatus / evalQuality
//   ④ 动画         animation trigger + tracks（一个变量驱动多属性，只支持单对象）
//   ⑤ 直接连接     （挂在事件上，P5 实现，这里只保留数据结构）
//
// 数据模型两种写法都认：
//   单属性：item.dyn = { mode:'tag', expr:'S001.LEVEL' }        ← 目标属性按类型取默认
//   多属性：item.dyn = { height:{mode:'tag',...}, fillColor:{...} }
// 面板一律写第二种（能一个对象挂多条），读的时候兼容第一种（手写 json / 早期数据）。
//
// 三条硬规矩：
// 1) 求值失败（点位不存在 / 数值转换失败）→ 属性保持上一次的值，只把对象标黄，绝不显示 0
// 2) 应用动态化只改样式、不重建 DOM（否则视频重连、拖拽被打断）
// 3) 闪烁用 Web Animations（改 opacity），不用 CSS animation 属性 ——
//    否则会把管道流动动画的 animation 属性冲掉，两者不能共存

import { evaluateCached } from './expr'
import { applyItemStyle } from './render'
import { familyOf } from './props'
// 4.3 起 tag 模式的 expr 存的是 {site, point} 对象，要转成 "S001.LEVEL" 才能读
import { tagOfVar } from './varbind'

// —— 可动态化属性目录（按类型族）——
const A = (key, label, kind, extra) => Object.assign({ key, label, kind }, extra || {})

const ATTRS = {
  tank: [
    A('height', '液位高度', 'pct', { hint: '按对象量程换算成百分比' }),
    A('fillColor', '液体颜色', 'color'),
    A('fontColor', '文字颜色', 'color'),
    A('value', '显示数值', 'num'),
    A('visible', '可见', 'bool'),
    A('blink', '闪烁', 'blink')
  ],
  value: [
    A('value', '显示数值', 'num'),
    A('text', '显示文字（文本列表）', 'text'),
    A('fillColor', '背景色', 'color'),
    A('fontColor', '文字颜色', 'color'),
    A('visible', '可见', 'bool'),
    A('blink', '闪烁', 'blink')
  ],
  lamp: [
    A('running', '亮/灭', 'bool'),
    A('fillColor', '灯颜色', 'color'),
    A('visible', '可见', 'bool'),
    A('blink', '闪烁', 'blink')
  ],
  pump: [
    A('running', '运行/停止', 'bool'),
    A('fillColor', '运行色', 'color'),
    A('visible', '可见', 'bool'),
    A('blink', '闪烁', 'blink')
  ],
  pipe: [
    A('running', '流动/静止', 'bool'),
    A('fillColor', '管线颜色', 'color'),
    A('visible', '可见', 'bool'),
    A('blink', '闪烁', 'blink')
  ],
  fill: [
    A('value', '显示数值', 'num'),
    A('fillColor', '填充色', 'color'),
    A('strokeColor', '边框色', 'color'),
    A('visible', '可见', 'bool'),
    A('blink', '闪烁', 'blink'),
    A('opacity', '不透明度', 'num', { min: 0, max: 100, unit: '%' })
  ],
  stroke: [
    A('value', '显示数值', 'num'),
    A('strokeColor', '线条颜色', 'color'),
    A('visible', '可见', 'bool'),
    A('blink', '闪烁', 'blink')
  ],
  text: [
    A('text', '文字内容', 'text'),
    A('value', '显示数值', 'num'),
    A('fillColor', '背景色', 'color'),
    A('fontColor', '文字颜色', 'color'),
    A('visible', '可见', 'bool'),
    A('blink', '闪烁', 'blink')
  ],
  button: [
    A('visible', '可见', 'bool'),
    A('text', '按钮文字', 'text'),
    A('fillColor', '背景色', 'color'),
    A('fontColor', '文字颜色', 'color')
  ],
  datalist: [A('visible', '可见', 'bool'), A('blink', '闪烁', 'blink'), A('opacity', '不透明度', 'num', { min: 0, max: 100, unit: '%' })],
  chart: [A('visible', '可见', 'bool'), A('blink', '闪烁', 'blink'), A('opacity', '不透明度', 'num', { min: 0, max: 100, unit: '%' })],
  video: [A('visible', '可见', 'bool'), A('opacity', '不透明度', 'num', { min: 0, max: 100, unit: '%' })],
  symbol: [A('fillColor', '填充色', 'color'), A('visible', '可见', 'bool'), A('blink', '闪烁', 'blink')],
  // P8 图片对象：图形列表绑的就是这个属性
  imgx: [A('image', '图片（图形列表）', 'img'), A('visible', '可见', 'bool'), A('opacity', '不透明度', 'num', { min: 0, max: 100, unit: '%' })]
}

export function dynAttrsOf(type) {
  return ATTRS[familyOf(type)] || ATTRS.symbol
}

export function dynAttrLabel(type, key) {
  const f = dynAttrsOf(type).find(a => a.key === key)
  return f ? f.label : key
}

// 单属性写法时，目标属性按类型定
export function defaultDynAttr(type) {
  const fam = familyOf(type)
  if (fam === 'tank') return 'height'
  if (fam === 'value') return 'value'
  if (fam === 'text') return 'text'
  if (fam === 'imgx') return 'image'
  if (fam === 'lamp' || fam === 'pump' || fam === 'pipe') return 'running'
  return 'fillColor'
}

export const DYN_MODES = [
  { v: '', t: '无' },
  { v: 'tag', t: '直接变量连接' },
  { v: 'indirect', t: '间接变量连接' },
  { v: 'dialog', t: '动态对话框' },
  { v: 'animation', t: '动画' },
  // P8 官方 4.7：把数值映射成文字 / 图片
  { v: 'textlist', t: '文本列表' },
  { v: 'graphlist', t: '图形列表' }
]

export const DATA_TYPES = [
  { v: 'Analog', t: 'Analog（数值区间）' },
  { v: 'Bool', t: 'Bool（0/1）' },
  { v: 'Bit', t: 'Bit（取第 N 位）' },
  { v: 'Direct', t: 'Direct（值直接赋给属性）' }
]

export const EVENT_NAMES = [
  { v: 'tag', t: '变量变化时' },
  { v: '250ms', t: '固定周期 250ms' },
  { v: '1s', t: '固定周期 1s' },
  { v: '5s', t: '固定周期 5s' },
  { v: 'screen', t: '画面周期' },
  { v: 'window', t: '窗口周期' }
]

// —— dyn 归一化：两种写法 → 统一成 { attr: binding } ——
export function normDyn(item) {
  const d = item && item.dyn
  if (!d || typeof d !== 'object') return {}
  if (d.mode) {
    // 单属性写法
    const attr = d.attr || defaultDynAttr(item.type)
    return { [attr]: d }
  }
  const out = {}
  for (const k of Object.keys(d)) {
    const v = d[k]
    if (v && typeof v === 'object' && v.mode) out[k] = v
  }
  return out
}

export function hasDyn(item) {
  return Object.keys(normDyn(item)).length > 0
}

export function dynCount(items) {
  return (items || []).filter(hasDyn).length
}

// —— 值域映射（动态对话框 / 动画共用）——
// to = null 表示「以上全部」；other 是没匹配到时的默认值（官方强制要求，不能省）
export function mapRange(ranges, v, other, bitIndex) {
  let x = Number(v)
  if (!isFinite(x)) return { value: other, matched: false }
  if (bitIndex !== undefined && bitIndex !== null && bitIndex >= 0) {
    x = (Math.floor(x) >> bitIndex) & 1
  }
  const list = Array.isArray(ranges) ? ranges : []
  for (const r of list) {
    const from = Number(r.from)
    const to = (r.to === null || r.to === undefined || r.to === '') ? Infinity : Number(r.to)
    if (!isFinite(from)) continue
    if (x >= from && x < to) {
      return { value: pickVal(r.value, x, from, to), matched: true, blink: r.blink || 0, row: r }
    }
  }
  return { value: other, matched: false }
}

// 「其他」默认值在面板上只有一个输入框，实际填的是颜色。高度 / 不透明度 / 数值
// 这类属性要是也套上一个颜色串，液位罐会直接掉成 0%（一超量程就空罐、数值位变空白）。
// 所以这几类属性在区间外一律夹到端点的档位值，不拿 other。
const NUMERIC_ATTRS = new Set(['height', 'opacity', 'value', 'blink', 'angle'])

// 取区间外的边界值：小于第一档起点 → 第一档的起点值；大于最后一档终点 → 终点值
function edgeValue(ranges, x) {
  const rs = (ranges || []).filter(r => isFinite(Number(r.from)))
  if (!rs.length) return undefined
  rs.sort((a, b) => Number(a.from) - Number(b.from))
  const pick = (spec, i) => (Array.isArray(spec) ? spec[i] : spec)
  const first = rs[0]
  const last = rs[rs.length - 1]
  if (Number(x) < Number(first.from)) return pick(first.value, 0)
  const to = (last.to === null || last.to === undefined || last.to === '') ? Infinity : Number(last.to)
  if (Number(x) >= to) return pick(last.value, 1)
  return undefined
}

// 未命中区间时，数值类属性用边界值兜底（颜色类照旧用 other）
function numericFix(attr, m, ranges, x) {
  if (!m || m.matched) return m
  if (!NUMERIC_ATTRS.has(attr)) return m
  if (m.value !== null && m.value !== undefined && m.value !== '' && !isNaN(parseFloat(m.value))) return m
  const ev = edgeValue(ranges, x)
  if (ev === undefined) return m
  return Object.assign({}, m, { value: ev })
}

// 值可以是标量，也可以是 [起, 止] 做线性插值（动画里的高度就是这么配的）
function pickVal(spec, x, from, to) {  if (!Array.isArray(spec)) return spec
  const a = spec[0]
  const b = spec[1]
  const na = parseFloat(a)
  const nb = parseFloat(b)
  const ua = String(a).replace(/^[-0-9.]+/, '')
  const ub = String(b).replace(/^[-0-9.]+/, '')
  if (!isFinite(na) || !isFinite(nb) || !isFinite(from) || !isFinite(to) || to <= from) return a
  const t = Math.max(0, Math.min(1, (x - from) / (to - from)))
  const n = na + (nb - na) * t
  return Math.round(n * 100) / 100 + (ua || ub || '')
}

// 一个绑定算出来的值 → 目标属性的取值
function mapByType(binding, raw) {
  const dt = binding.dataType || 'Analog'
  if (dt === 'Direct') return { value: raw, matched: true }
  if (dt === 'Bool') return mapRange(binding.ranges, raw ? 1 : 0, binding.other)
  if (dt === 'Bit') return mapRange(binding.ranges, raw, binding.other, Number(binding.bit || 0))
  return mapRange(binding.ranges, raw, binding.other)
}

// —— 解析一个对象的所有绑定 ——
// 返回 { attrs: {attr: {ok, value, blink, quality}}, issues: [{attr, reason, msg}] }
export function resolveItem(item, rt) {
  const nb = normDyn(item)
  const attrs = {}
  const issues = []
  for (const attr of Object.keys(nb)) {
    const b = nb[attr]
    const r = resolveOne(attr, b, item, rt)
    if (r.ok) attrs[attr] = r
    else issues.push(r)
  }
  return { attrs, issues }
}

export function resolveOne(attr, b, item, rt) {
  if (!rt || !rt.evalCtx) return { ok: false, attr, reason: 'no_rt', msg: '没有运行时' }
  const ctx = rt.evalCtx()
  const bad = (reason, msg, extra) => Object.assign({ ok: false, attr, reason, msg }, extra || {})

  try {
    if (b.mode === 'tag') {
      if (!b.expr) return bad('empty', '表达式为空')
      // expr 有两种存法，必须区分：
      //   ① {site:'S001', point:'V300OUT'}   —— 4.3 起的新格式（属性面板下拉选出来的）
      //   ② "S001.LEVEL" / 老表达式字符串     —— 兼容旧画面
      // 早期这里无脑丢给 evaluateCached，它会先 String(expr)，
      // 对象变成 "[object Object]" → lex 语法错 → 所有新格式绑定全部报"求值失败"。
      let rawVal
      let quality = 'good'
      let rawTag = ''
      let tagDtype = ''          // 点位数据类型，case 'value' 用它决定小数位
      if (typeof b.expr === 'object') {
        rawTag = tagOfVar(b.expr)
        if (!rawTag) return bad('bad_var', '变量必须是 {site, point} 两个非空字符串')
        const v = ctx.read(rawTag)
        if (!v || !v.found) return bad('tag_not_found', '点位不存在：' + rawTag, { tag: rawTag })
        rawVal = v.val
        quality = (v.q === 1) ? 'bad' : 'good'
        // dtype 必须带出去：case 'value' 要按点位类型决定小数位
        // （uint32/int16/byte/bool 不带小数）。丢掉的话整数会显示成 2587962.00
        tagDtype = v.dtype || ''
      } else {
        const r = evaluateCached(b.expr, ctx)
        if (!r.ok) return bad(r.reason, r.msg || '求值失败', { tag: r.tag })
        rawVal = r.value
        quality = r.quality
        rawTag = r.tag || ''
      }
      // 配了 ranges 就做映射（1=红 0=绿 这类）；没配则值直给属性
      if (Array.isArray(b.ranges) && b.ranges.length) {
        const m = numericFix(attr, mapByType(b, rawVal), b.ranges, rawVal)
        if (m.value === undefined || m.value === null) {
          return bad('no_other', '没有匹配到值，且没配「其他」默认值', { raw: rawVal, tag: rawTag })
        }
        return { ok: true, attr, value: m.value, blink: m.blink, quality,
                 raw: rawVal, matched: m.matched, tag: rawTag, mode: 'tag', dtype: tagDtype }
      }
      return { ok: true, attr, value: rawVal, quality, tag: rawTag, mode: 'tag', dtype: tagDtype }
    }

    if (b.mode === 'indirect') {
      if (!b.nameExpr) return bad('empty', '名称表达式为空')
      const n = evaluateCached(b.nameExpr, ctx)
      if (!n.ok) return bad('unknown', n.msg || '名称表达式求值失败')
      const tag = String(n.value)
      const v = ctx.read(tag)
      if (!v || !v.found) return bad('tag_not_found', '点位不存在：' + tag, { tag })
      if (v.val === null || v.val === undefined) return bad('bad_number', '点位还没有值：' + tag, { tag })
      // 和 tag 模式一样：配了 ranges 就要做映射，否则数值会被当成属性值
      // （fillColor=0 → 非法颜色 → 渲染回退/透明）
      if (Array.isArray(b.ranges) && b.ranges.length) {
        const m = numericFix(attr, mapByType(b, v.val), b.ranges, v.val)
        if (m.value === undefined || m.value === null) {
          return bad('no_other', '没有匹配到值，且没配「其他」默认值', { raw: v.val, tag })
        }
        return { ok: true, attr, value: m.value, blink: m.blink,
                 quality: v.q === 1 ? 'bad' : 'good', raw: v.val,
                 matched: m.matched, tag, mode: 'indirect', dtype: v.dtype || '' }
      }
      return { ok: true, attr, value: v.val, quality: v.q === 1 ? 'bad' : 'good',
               tag, mode: 'indirect', dtype: v.dtype || '' }
    }

    if (b.mode === 'textlist' || b.mode === 'graphlist') {
      // P8 官方 4.7：变量值 → 文本 / 图片。值不在列表里要报出来（不能静默显示空白）
      if (!b.expr) return bad('empty', '表达式为空')
      // 同 tag/indirect/animation：expr 可能是 {site,point} 对象，
      // 直接 evaluateCached 会 String 成 "[object Object]"，报「不认识的字符 [」
      const r = effectiveExpr(b, b.expr, rt)
      if (!r.ok) return bad(r.reason, r.msg || '求值失败', { tag: r.tag })
      const L = rt.list ? rt.list(b.listId) : null
      if (!L) return bad('no_list', '值列表不存在：' + (b.listId || '(未选)'))
      if (L.kind !== (b.mode === 'textlist' ? 'text' : 'graph')) {
        return bad('list_kind', '「' + b.listId + '」不是' + (b.mode === 'textlist' ? '文本' : '图形') + '列表')
      }
      const hit = (L.items || []).find(x => Number(x.value) === Number(r.value))
      if (!hit) return bad('no_match', '值 ' + r.value + ' 不在列表「' + b.listId + '」里', { raw: r.value })
      const val = b.mode === 'textlist' ? (hit.text === undefined ? '' : hit.text) : hit.image
      return { ok: true, attr, value: val, quality: r.quality, raw: r.value, mode: b.mode }
    }

    if (b.mode === 'dialog') {
      // 触发事件为「变量变化」时，表达式通常就是那个变量；周期触发时表达式自己读点位
      const formula = b.formula || (b.trigger && b.trigger.tag) || ''
      if (!formula) return bad('empty', '表达式为空')
      const r = evaluateCached(formula, ctx)
      if (!r.ok) return bad(r.reason, r.msg || '求值失败', { tag: r.tag })
      if (b.evalQuality && r.quality === 'bad') {
        // 质量坏：值照给，但标记质量差（显示 ⚠ / 置灰由渲染层决定）
        const m0 = numericFix(attr, mapByType(b, r.value), b.ranges, r.value)
        return { ok: true, attr, value: m0.value, blink: m0.blink, quality: 'bad', raw: r.value, matched: m0.matched, mode: 'dialog' }
      }
      const m = numericFix(attr, mapByType(b, r.value), b.ranges, r.value)
      if (m.value === undefined || m.value === null) {
        return bad('no_other', '没有匹配到值，且没配「其他」默认值', { raw: r.value })
      }
      return { ok: true, attr, value: m.value, blink: m.blink, quality: r.quality, raw: r.value, matched: m.matched, mode: 'dialog' }
    }

    if (b.mode === 'animation') {
      // 动画：一个 trigger 驱动多条 track，这里每个 attr 被拆成独立 binding（见 splitAnimation）
      const src = b.expr || (b.trigger && (b.trigger.tag || b.trigger.expr)) || ''
      const r = effectiveExpr(b, src, rt)
      if (!r.ok) return bad(r.reason, r.msg || '求值失败', { tag: r.tag })
      const m = numericFix(attr, mapRange(b.ranges, r.value, b.other,
        b.dataType === 'Bit' ? Number(b.bit || 0) : undefined), b.ranges, r.value)
      if (m.value === undefined || m.value === null) {
        return bad('no_other', '动画区间没有匹配到值', { raw: r.value })
      }
      return { ok: true, attr, value: m.value, blink: m.blink, quality: r.quality, raw: r.value, matched: m.matched, mode: 'animation' }
    }
  } catch (e) {
    return bad('error', (e && e.message) || '求值异常')
  }
  return bad('unknown_mode', '不认识的动态化模式：' + b.mode)
}

function effectiveExpr(b, src, rt) {
  const runtime = rt || b.__rt
  const ctx = runtime ? runtime.evalCtx() : null
  if (!ctx) return { ok: false, reason: 'no_rt', msg: '没有运行时' }
  // 和 tag/indirect 一处根因：expr 可能是 {site, point} 对象（4.3 起），
  // 直接丢给 evaluateCached 会被 String 成 "[object Object]" → 语法错 → 动画永久 bad。
  if (src && typeof src === 'object') {
    const tag = tagOfVar(src)
    if (!tag) return { ok: false, reason: 'bad_var', msg: '变量必须是 {site, point} 两个非空字符串' }
    const v = ctx.read(tag)
    if (!v || !v.found) return { ok: false, reason: 'tag_not_found', msg: '点位不存在：' + tag, tag }
    if (v.val === null || v.val === undefined) {
      return { ok: false, reason: 'bad_number', msg: '点位还没有值：' + tag, tag }
    }
    return { ok: true, value: v.val, quality: v.q === 1 ? 'bad' : 'good', tag }
  }
  return evaluateCached(src, ctx)
}

// 动画（面板里是一条 trigger + N 条 track）→ 展开成每个属性一条 binding，
// 这样运行时只认一种形状，不用为动画单独写一套应用逻辑。
export function splitAnimation(item, rt) {
  const d = item && item.dyn
  if (!d || d.mode !== 'animation' || !Array.isArray(d.tracks)) return {}
  const out = {}
  for (const tr of d.tracks) {
    if (!tr || !tr.attr) continue
    out[tr.attr] = {
      mode: 'animation',
      expr: d.expr || (d.trigger && d.trigger.tag) || '',
      dataType: tr.dataType || d.dataType || 'Analog',
      ranges: tr.ranges || [],
      other: tr.other !== undefined ? tr.other : d.other,
      bit: tr.bit,
      __rt: rt
    }
  }
  return out
}

// —— 应用到 DOM ——
// 「保持上一次的值」：求值失败时属性要停在上一次成功的结果上，不显示 0、不显示 --。
// 光靠「不写 DOM」不够——画面重建（改结构、切站重绘）会换掉节点，上一次的值就丢了。
// 所以按对象名 + 属性记住上一次成功求值的结果，失败时拿它重放一遍。
// 缓存挂在画布容器上（不是模块级），不同画面之间不会串值。
function lastGoodOf(container) {
  if (!container.__dynLast) container.__dynLast = new Map()
  return container.__dynLast
}

function memoKey(rec, item, attr) {
  return (item.name || ('#' + rec.idx)) + '|' + attr
}

// 切站点时把「上一次的值」清掉：不清的话换站后如果新站点缺点位，
// 画面上会留着上个站点的数值，看着像"切站没生效"。
export function clearDynLast(container) {
  if (container && container.__dynLast) container.__dynLast.clear()
}

export function applyDynToCanvas(container, rt) {
  const st = container && container.__scada
  if (!st || !st.items) return { applied: 0, issues: [] }
  const memo = lastGoodOf(container)
  const allIssues = []
  let applied = 0
  for (const rec of st.items) {
    const item = rec.item
    const anim = splitAnimation(item, rt)
    const isAnim = Object.keys(anim).length > 0
    let nb = isAnim ? anim : normDyn(item)
    // 只把「真正配了变量」的绑定算作接管。
    // 属性面板里点过「动态化 → 显示数值」但没选变量时，会存成
    // {value:{mode:'tag', expr:''}} —— 这种空绑定既解析不出值（resolveOne 报
    // 表达式为空），又把 render.js 的 item.var 通道顶掉（dynOwns 命中 → patch 直接
    // return），两条路都不写 DOM，只读 I/O 域就永久卡在首帧值不动。
    nb = Object.fromEntries(Object.entries(nb).filter(([, b]) => {
      if (!b || typeof b !== 'object') return false
      if (b.mode === 'tag' || b.mode === 'textlist' || b.mode === 'graphlist') {
        const e = b.expr
        if (e == null) return false
        if (typeof e === 'string') return !!e.trim()
        if (typeof e === 'object') return !!tagOfVar(e)
        return false
      }
      return true
    }))
    const keys = Object.keys(nb)
    // 告诉旧式 var 通道（render.js 的 patch）这些属性已归动态化管：别再每帧写 --
    if (rec.node) rec.node.__dynOwns = new Set(keys)
    // 条件规则表（item.rules）：无常规动态化的对象在这里跑完就 continue。
    // 有 dyn 的对象要留到 applyAttrValues 之后再跑 —— dyn 的 fillColor/strokeColor
    // 走 applyItemStyle 整体重算样式，会把规则设的 border-color 直接冲掉。
    if (!keys.length) {
      setBad(rec.node, false)
      try {
        const rr = applyRules(rec, item, rt)
        allIssues.push(...rr.issues)
        if (rr.matched) applied++
      } catch (e) { /* 规则异常不影响渲染 */ }
      continue
    }

    const attrs = {}
    const issues = []
    for (const attr of keys) {
      const r = resolveOne(attr, nb[attr], item, rt)
      const k = memoKey(rec, item, attr)
      if (r.ok) {
        attrs[attr] = r
        if (r.value !== undefined && r.value !== null) memo.set(k, r)
      } else {
        issues.push(r)
        allIssues.push(Object.assign({ item }, r))
        const last = memo.get(k)
        if (last) attrs[attr] = Object.assign({}, last, { stale: true })
      }
    }
    applyAttrValues(rec, item, attrs)
    // 规则在 dyn 之后跑：规则优先级更高。dyn 的 fillColor/strokeColor 会经
    // applyItemStyle 整体重算样式（连 border 一起写），先跑规则就会被冲掉 ——
    // 表现就是"配了 strokeColor 规则，边框颜色纹丝不动"。
    try {
      const rr = applyRules(rec, item, rt)
      allIssues.push(...rr.issues)
      if (rr.matched) applied++
    } catch (e) { /* 规则异常不影响渲染 */ }
    setBad(rec.node, issues.length > 0)
    if (Object.keys(attrs).length) applied++
  }
  return { applied, issues: allIssues }
}

function setBad(node, on) {
  if (!node) return
  if (on) node.classList.add('scada-dyn-bad')
  else node.classList.remove('scada-dyn-bad')
}

function fmtNum(v, item, dec) {
  const n = Number(v)
  if (!isFinite(n)) return String(v)
  // 显式给了 dec 就按 dec（调用方明确要几位就几位）
  if (dec !== undefined) return n.toFixed(Math.max(0, Math.min(6, Number(dec) || 0)))
  // 否则按点位类型：bool / 整数不带小数，浮点用 item.decimals
  const dt = String((item && item.dtype) || '').toLowerCase()
  if (dt === 'bool') return n ? '1' : '0'
  if (['byte', 'int16', 'uint16', 'int32', 'uint32', 'int64', 'uint64'].includes(dt)) {
    return String(Math.round(n))
  }
  const d = (item && item.decimals !== undefined && item.decimals !== null)
    ? Number(item.decimals) : 2
  return n.toFixed(Math.max(0, Math.min(6, isFinite(d) ? d : 2)))
}

function pctFromValue(item, v) {
  const s = String(v)
  const m = s.match(/^(-?[\d.]+)\s*%$/)
  if (m) return Math.max(0, Math.min(100, Number(m[1])))
  const min = Number(item.min === undefined ? 0 : item.min)
  const max = Number(item.max === undefined ? 100 : item.max)
  const x = Number(v)
  if (!isFinite(x) || max === min) return 0
  return Math.max(0, Math.min(100, ((x - min) / (max - min)) * 100))
}

// 把一组 {属性: {value, blink}} 施到 DOM 上。动态化与 P5 事件动作共用一份，
// 免得「同样的属性」在两个地方各写一遍、行为还不一致。
// ===================== 条件规则表（2026-11-14 新增，不动原 dyn）=====================
// 用户要的语义：「当前值 = x 则执行动作」，一个图元可以挂多条。
// 数据存在 item.rules（全新字段，dyn 结构一个字都没动）：
//   [{ tag:{site,point}, op:'eq'|'ne'|'gt'|'ge'|'lt'|'le',
//      value:'74', action:'fillColor'|'strokeColor'|'fontColor'|'text'|'visible'|'blink',
//      actionValue:'#f00' }]
// 命中后的动作直接复用 applyAttrValues —— 它能处理 fillColor/strokeColor/
// fontColor/text/visible/blink，不需要另写一套 DOM 写入。

const RULE_OPS = ['eq', 'ne', 'gt', 'ge', 'lt', 'le']
const RULE_ACTIONS = ['fillColor', 'strokeColor', 'fontColor', 'text', 'visible', 'blink']

/** 单条条件判定。数字能比就按数字比，否则按字符串精确比（'运行' == '运行'）。 */
export function evalCond(op, actual, expect) {
  if (actual === null || actual === undefined) return false
  const a = Number(actual)
  const e = Number(expect)
  const numeric = isFinite(a) && isFinite(e) && String(expect).trim() !== ''
  switch (op) {
    case 'eq': return numeric ? a === e : String(actual) === String(expect)
    case 'ne': return numeric ? a !== e : String(actual) !== String(expect)
    case 'gt': return numeric ? a > e : false
    case 'ge': return numeric ? a >= e : false
    case 'lt': return numeric ? a < e : false
    case 'le': return numeric ? a <= e : false
    default: return false
  }
}

/** 规范化 item.rules：丢掉不完整的行（没绑点位 / 没选动作）。 */
export function normRules(item) {
  const rs = item && item.rules
  if (!Array.isArray(rs)) return []
  // 只要求「选了动作」。tag 可能为空（历史坏数据：点过"+ 添加规则"但上方的
  // 直接变量连接还没选），这种情况交给 applyRules 回落到 item.var / item.dyn，
  // 不要在这里就丢掉 —— 丢掉的话界面上看得见规则、运行时却完全不执行。
  return rs.filter(r => r && r.action)
}

/** 规则用哪个点位：规则自带 > item.var（旧式）> item.dyn 里第一个有 expr 的绑定 */
function ruleTagOf(r, item) {
  let t = (typeof r.tag === 'string') ? r.tag.trim() : (r.tag ? tagOfVar(r.tag) : '')
  if (t) return t
  const iv = item && item.var
  if (iv) {
    t = (typeof iv === 'string') ? iv.trim() : tagOfVar(iv)
    if (t) return t
  }
  const dyn = (item && item.dyn) || {}
  for (const k of Object.keys(dyn)) {
    const b = dyn[k]
    if (b && b.expr) {
      t = (typeof b.expr === 'string') ? b.expr.trim() : tagOfVar(b.expr)
      if (t) return t
    }
  }
  return ''
}

/**
 * 把规则表算成一次 applyAttrValues 的 attrs。
 * 多条规则命中同一属性时，后面的覆盖前面的（表格里排在下面的优先级高）。
 */
/**
 * 把一条规则的动作直接写到 DOM。
 * 不复用 applyAttrValues：那套依赖 R.num / R.val 这类只有 I/O 域、液位罐才有的
 * 节点，标准图元（矩形/圆/多边形/线）和工艺图元根本没有，规则会命中但看不见效果。
 */
function applyRuleAction(rec, item, action, value) {
  const box = rec && rec.node
  if (!box) return
  const R = rec.R || {}
  const on = (v) => String(v) === '1' || String(v) === 'true' || v === true
  switch (action) {
    case 'fillColor':
      box.style.setProperty('background-color', value, 'important')
      // 矢量图元（line/polyline/polygon/ellipse/arc）画在内联 svg 里，改 fill
      box.querySelectorAll('svg [fill]').forEach(e => e.setAttribute('fill', value))
      box.querySelectorAll('svg path,svg polygon,svg rect,svg ellipse,svg circle')
         .forEach(e => { if (getComputedStyle(e).fill !== 'none') e.setAttribute('fill', value) })
      break
    case 'strokeColor':
      box.style.setProperty('border-color', value, 'important')
      box.querySelectorAll('svg [stroke]').forEach(e => e.setAttribute('stroke', value))
      break
    case 'fontColor': {
      for (const k of ['num', 'val', 'txt', 'label', 'btn', 'unit']) {
        if (R[k]) R[k].style.setProperty('color', value, 'important')
      }
      // 叶子文本节点。注意必须带 input/textarea：I/O 域可输入态的文字在 <input> 里，
      // 只扫 span/div 会漏掉它（枚举 210 组合时发现的）。
      box.querySelectorAll('span,div,input,textarea,select').forEach(e => {
        const isField = /^(INPUT|TEXTAREA|SELECT)$/.test(e.tagName)
        if (isField || (!e.children.length && e.textContent.trim())) {
          e.style.setProperty('color', value, 'important')
        }
      })
      // SVG 里的 <text>（工艺图元的标注）
      box.querySelectorAll('svg text').forEach(e => e.setAttribute('fill', value))
      // 规则自己盖上去的文本层
      const ov = box.querySelector('.scada-rule-text')
      if (ov) ov.style.setProperty('color', value, 'important')
      break
    }
    case 'text': {
      const t = R.txt || R.val || R.num
      if (t) { t.textContent = String(value ?? ''); t.style.display = '' ; break }
      // 没有现成文本节点：盖一层文本上去
      let ov = box.querySelector('.scada-rule-text')
      if (!ov) {
        ov = document.createElement('div')
        ov.className = 'scada-rule-text'
        ov.style.cssText = 'position:absolute;inset:0;display:flex;align-items:center;justify-content:center;' +
          'pointer-events:none;font-weight:600;color:#e2e8f0;font-size:14px;box-sizing:border-box;padding:2px 4px;'
        box.appendChild(ov)
      }
      ov.textContent = String(value ?? '')
      break
    }
    case 'visible':
      box.style.display = on(value) ? '' : 'none'
      break
    case 'blink':
      box.style.animation = on(value) ? 'scada-rule-blink 1s steps(2,end) infinite' : ''
      break
    default: break
  }
}

/** 闪烁 keyframes 只注入一次 */
let _blinkCssDone = false
function ensureBlinkCss() {
  if (_blinkCssDone || typeof document === 'undefined') return
  _blinkCssDone = true
  const st = document.createElement('style')
  st.id = 'scada-rule-style'
  st.textContent = '@keyframes scada-rule-blink{0%,100%{opacity:1}50%{opacity:.25}}'
  document.head.appendChild(st)
}

export function applyRules(rec, item, rt) {
  const rs = normRules(item)
  if (!rs.length) return { matched: 0, issues: [] }
  if (!rec || !rec.node) return { matched: 0, issues: [] }
  const attrs = {}
  const issues = []
  let matched = 0
  for (const r of rs) {
    const tag = ruleTagOf(r, item)
    if (!tag) { issues.push({ item, attr: r.action, reason: 'bad_var', msg: '规则没绑点位，且对象也没有变量可回落' }); continue }
    let v = null
    try { v = rt.read(tag) } catch (e) { v = null }
    if (!v || !v.found) { issues.push({ item, attr: r.action, reason: 'tag_not_found', tag, msg: '点位不存在：' + tag }); continue }
    if (v.val === null || v.val === undefined) continue
    const op = RULE_OPS.includes(r.op) ? r.op : 'eq'
    if (!evalCond(op, v.val, r.value)) continue
    matched++
    attrs[r.action] = { ok: true, attr: r.action, value: r.actionValue,
                        quality: v.q === 1 ? 'bad' : 'good', tag, fromRule: true }
  }
  if (matched) { try { ensureBlinkCss() } catch (e) {} }
  for (const action of Object.keys(attrs)) {
    try { applyRuleAction(rec, item, action, attrs[action].value) } catch (e) { /* 单条异常不影响其它 */ }
  }
  return { matched, issues }
}
// ===================== 条件规则表 END =====================

export function applyAttrValues(rec, item, attrs) {
  const node = rec.node
  const R = rec.R || {}
  if (!node) return
  const fam = familyOf(item.type)
  let blinkMs = 0

  // 先处理会影响布局的（w/h/x/y 走 applyItemStyle 整体重算），其余直接改
  for (const key of Object.keys(attrs)) {
    const a = attrs[key]
    const v = a.value

    switch (key) {
      case 'height': {
        if (R.liquid) {
          const p = pctFromValue(item, v)
          R.liquid.style.height = p + '%'
        }
        break
      }

      case 'value': {
        // dtype 优先取动态化解析结果（a.dtype），组态对象本身没有 dtype 字段。
        // 不这么做的话标准对象的 value 绑 uint32/uint16/byte 会补成 2587962.00。
        const txt = fmtNum(v, { dtype: (a && a.dtype) || item.dtype, decimals: item.decimals })
        // 单位对所有节点都要拼：I/O 域和标准对象都用 R.num，
        // 原来只有液位罐(R.val)拼了单位，标准对象配了单位显示不出来。
        const withUnit = txt + (item.unit ? ' ' + item.unit : '')
        if (R.num) R.num.textContent = withUnit        // I/O 域 / 标准对象
        else if (R.val) R.val.textContent = withUnit   // 液位罐
        break
      }

      case 'text': {
        // 文本列表（P8）也会走到这里。目标节点按对象形态取：
        //   I/O 域 / 液位罐 → 文字写进「数值」位置（R.num / R.val），对象名(lb)不能被顶掉；
        //   文字对象、按钮 → 顶上的文字就是内容本身。
        const t = R.txt || R.num || R.val || R.btn || R.label
        if (t) t.textContent = String(v)
        break
      }

      case 'image': {
        // 图形列表（P8）：换图片地址。加载失败保留上一张，不显示裂图
        const src = String(v || '')
        if (R.img && src && R.img.getAttribute('src') !== src) {
          R.img.style.display = ''
          R.img.src = src
          if (R.ph) R.ph.style.display = 'none'
        }
        break
      }

      case 'fillColor': {
        if (fam === 'tank') {
          applyItemStyle(node, Object.assign({}, item, { liquidColor: String(v) }), R)
        } else if (fam === 'lamp') {
          if (R.dot) {
            R.dot.style.background = String(v)
            R.dot.style.boxShadow = '0 0 12px ' + v
          }
        } else if (fam === 'pipe') {
          node.style.background = String(v)
        } else if (fam === 'pump') {
          applyItemStyle(node, Object.assign({}, item, { colorRun: String(v) }), R)
          if (R.paint) { R.running = true; R.paint() }
        } else {
          applyItemStyle(node, Object.assign({}, item, { fill: String(v) }), R)
        }
        break
      }

      case 'strokeColor':
        applyItemStyle(node, Object.assign({}, item, { stroke: String(v) }), R)
        break

      case 'fontColor':
        applyItemStyle(node, Object.assign({}, item, { color: String(v) }), R)
        break

      case 'opacity':
        node.style.opacity = String(Math.max(0, Math.min(100, Number(v))) / 100)
        break

      case 'visible': {
        const on = typeof v === 'string' ? (v !== '' && v !== '0' && v.toLowerCase() !== 'false') : !!Number(v) || v === true
        node.style.display = on ? '' : 'none'
        break
      }

      case 'running': {
        const on = typeof v === 'string' ? (v !== '' && v !== '0' && v.toLowerCase() !== 'false') : !!Number(v) || v === true
        if (R.paint) { R.running = on; R.paint() }
        break
      }

      case 'blink': {
        const ms = Number(v)
        if (ms > 0) blinkMs = ms
        break
      }

      case 'x': case 'y': case 'w': case 'h': case 'rot':
        applyItemStyle(node, Object.assign({}, item, { [key]: Number(v) }), R)
        break

      default:
        break
    }

    // 值域行里带 blink（如「≥3.5 变红且闪烁」）
    if (a.blink) blinkMs = Number(a.blink) || 0
  }
  // 一轮算完再统一设闪烁：不然「颜色」那条会把「闪烁」刚设的动画取消掉
  setBlink(node, blinkMs)
}

// 闪烁：Web Animations 改 opacity，不占用 CSS animation 属性（管道流动还在用）
function setBlink(node, ms) {
  if (!node) return
  if (!ms) {
    if (node.__blinkAnim) { try { node.__blinkAnim.cancel() } catch (e) { /* 已取消 */ } node.__blinkAnim = null }
    node.classList.remove('scada-blink-on')
    return
  }
  if (node.__blinkAnim && node.__blinkMs === ms) return
  if (node.__blinkAnim) { try { node.__blinkAnim.cancel() } catch (e) { /* 已取消 */ } }
  node.__blinkMs = ms
  node.classList.add('scada-blink-on')
  try {
    node.__blinkAnim = node.animate(
      [{ opacity: 1 }, { opacity: 0.25 }, { opacity: 1 }],
      { duration: Math.max(200, ms), iterations: Infinity }
    )
  } catch (e) {
    node.__blinkAnim = null
  }
}

// 编辑态：把某个对象的动态化一次性清掉（切换模式到「无」时用）
export function clearDyn(item) {
  if (!item) return
  delete item.dyn
}
