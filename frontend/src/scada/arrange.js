// 对齐 / 分布 / 图层 / 组合的纯逻辑（P7）—— 不碰 DOM，方便单测与验收对账
//
// 坐标约定：本文件里的 x/y/w/h 一律是「画面绝对坐标」。
// 组合内的子对象存的是相对父组的坐标，进出本文件时由调用方换算（见 canvas.absOf / toLocal）。

export const MAX_LAYERS = 32          // 官方 4.5.13：图层最多 32 层
export const MAX_GROUP_DEPTH = 20     // 官方 4.8.11：组合最多嵌套 20 层

export function rectOf(item, parent) {
  const px = parent ? (parent.x || 0) : 0
  const py = parent ? (parent.y || 0) : 0
  return {
    item,
    x: px + (Number(item.x) || 0),
    y: py + (Number(item.y) || 0),
    w: Math.max(1, Number(item.w) || 1),
    h: Math.max(1, Number(item.h) || 1)
  }
}

export function bboxOf(rects) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  for (const r of rects) {
    x0 = Math.min(x0, r.x); y0 = Math.min(y0, r.y)
    x1 = Math.max(x1, r.x + r.w); y1 = Math.max(y1, r.y + r.h)
  }
  if (!isFinite(x0)) return { x: 0, y: 0, w: 0, h: 0 }
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 }
}

// 组合嵌套深度：普通对象 0，一层组 1，组里套组 2 …
export function groupDepth(item) {
  if (!item || item.type !== 'group' || !Array.isArray(item.items) || !item.items.length) return 0
  let d = 0
  for (const c of item.items) d = Math.max(d, groupDepth(c))
  return d + 1
}

// —— 单选：相对画布 ——
// 注意所有结果都取整：不取整的话 1600×900 除以 2 会出现 .5，对象对齐后看起来「跳」一下
const CANVAS_ALIGN = {
  'canvas-l': (r, page) => ({ x: 0, y: r.y }),
  'canvas-r': (r, page) => ({ x: Math.round(page.W - r.w), y: r.y }),
  'canvas-t': (r, page) => ({ x: r.x, y: 0 }),
  'canvas-b': (r, page) => ({ x: r.x, y: Math.round(page.H - r.h) }),
  'canvas-hc': (r, page) => ({ x: Math.round((page.W - r.w) / 2), y: r.y }),
  'canvas-vc': (r, page) => ({ x: r.x, y: Math.round((page.H - r.h) / 2) })
}

// —— 多选：相对基准 ——
// base 是基准矩形（默认「最后选中的对象」，也可切成「最外层包围盒」）
const MULTI_ALIGN = {
  l: (r, b) => ({ x: b.x, y: r.y }),
  r: (r, b) => ({ x: b.x + b.w - r.w, y: r.y }),
  hc: (r, b) => ({ x: Math.round(b.x + (b.w - r.w) / 2), y: r.y }),
  t: (r, b) => ({ x: r.x, y: b.y }),
  b: (r, b) => ({ x: r.x, y: b.y + b.h - r.h }),
  vc: (r, b) => ({ x: r.x, y: Math.round(b.y + (b.h - r.h) / 2) })
}

/**
 * 对齐。rects / base 都是绝对坐标矩形。
 * 返回 [{ item, x, y, w, h }]（只回有变化的项；宽高仅当 等宽/等高 时才带）
 */
export function alignRects(rects, mode, { base, page } = {}) {
  if (!rects || !rects.length) return []
  if (CANVAS_ALIGN[mode]) {
    if (rects.length !== 1) return []
    const r = rects[0]
    const to = CANVAS_ALIGN[mode](r, page || { W: 1600, H: 900 })
    return [{ item: r.item, x: Math.round(to.x), y: Math.round(to.y) }]
  }
  const fn = MULTI_ALIGN[mode]
  const eqW = mode === 'eqw'
  const eqH = mode === 'eqh'
  if (!fn && !eqW && !eqH) return []
  const b = base || bboxOf(rects)
  const out = []
  for (const r of rects) {
    if (eqW) { out.push({ item: r.item, x: r.x, y: r.y, w: Math.round(b.w) }); continue }
    if (eqH) { out.push({ item: r.item, x: r.x, y: r.y, h: Math.round(b.h) }); continue }
    const to = fn(r, b)
    out.push({ item: r.item, x: Math.round(to.x), y: Math.round(to.y) })
  }
  return out.filter(o => o.x !== Math.round(rects.find(r => r.item === o.item).x)
    || o.y !== Math.round(rects.find(r => r.item === o.item).y)
    || o.w !== undefined || o.h !== undefined)
}

/**
 * 等距分布：保持首尾不动，中间按相同间距摆开。
 * axis 'x' 水平（左→右），'y' 垂直（上→下）。
 * 少于 3 个没有意义（首尾就是全部），直接返回空。
 */
export function distributeRects(rects, axis) {
  if (!rects || rects.length < 3) return []
  const horiz = axis !== 'y'
  const sorted = rects.slice().sort((a, b) => (horiz ? a.x - b.x : a.y - b.y))
  const first = sorted[0], last = sorted[sorted.length - 1]
  const span = horiz ? (last.x + last.w - first.x) : (last.y + last.h - first.y)
  let used = 0
  for (const r of sorted) used += horiz ? r.w : r.h
  const gap = (span - used) / (sorted.length - 1)     // 可能是负数（对象总宽超过跨度），照样按等距排
  const out = []
  let cursor = horiz ? first.x : first.y
  for (let i = 0; i < sorted.length; i++) {
    const r = sorted[i]
    const pos = Math.round(cursor)
    if (i > 0 && i < sorted.length - 1) {
      out.push(horiz ? { item: r.item, x: pos, y: r.y } : { item: r.item, x: r.x, y: pos })
    }
    cursor += (horiz ? r.w : r.h) + gap
  }
  return out.filter(o => {
    const r = rects.find(q => q.item === o.item)
    return o.x !== Math.round(r.x) || o.y !== Math.round(r.y)
  })
}

// —— 组合 ——
// 子对象存相对坐标（进组时减掉组原点），组整体移动只改组自身 x/y，
// 这样拖 100 次也不会累积误差（绝对坐标每次加减会漂）。
export function makeGroup(children, name) {
  const bb = bboxOf(children.map(c => ({ x: c.x, y: c.y, w: c.w, h: c.h })))
  return {
    type: 'group',
    name,
    x: bb.x, y: bb.y, w: bb.w, h: bb.h,
    items: children.map(c => {
      const n = JSON.parse(JSON.stringify(c))
      n.x = (Number(c.x) || 0) - bb.x
      n.y = (Number(c.y) || 0) - bb.y
      return n
    })
  }
}

// 解组：子对象坐标还原成绝对坐标
export function flattenGroup(group) {
  return (group.items || []).map(c => {
    const n = JSON.parse(JSON.stringify(c))
    n.x = (Number(c.x) || 0) + (Number(group.x) || 0)
    n.y = (Number(c.y) || 0) + (Number(group.y) || 0)
    return n
  })
}

// —— 图层带 ——
export function defaultLayers() {
  return [{ id: 1, name: '第 1 层' }]
}

export function nextLayerId(layers) {
  let m = 0
  for (const l of layers || []) m = Math.max(m, Number(l.id) || 0)
  return m + 1
}
