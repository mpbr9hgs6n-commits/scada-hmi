// 拖动参考线 + 吸附（P7）
//
// 手感取自 WinCC：阈值 5px。用 10px 太黏——画小图标时会一直吸到旁边的对象上。
// 只在拖动时出现，松手消失（由 canvas.js 负责清掉 DOM）。

export const SNAP_PX = 5

// 三个锚点：起边 / 中心 / 止边
function anchors(a, horiz) {
  const s = horiz ? a.x : a.y
  const len = horiz ? a.w : a.h
  return [s, s + len / 2, s + len]
}

/**
 * 计算吸附偏移与参考线。
 * mov    {x,y,w,h}  正在拖的选择包围盒（已含拖动位移）
 * others [{x,y,w,h,item}]  其它对象（不含被拖的、不含隐藏的）
 * 返回   { dx, dy, guides:[{ dir:'v'|'h', pos, from, to, label }] }
 *        dx/dy 是要补到鼠标位移上的吸附量（0 表示没吸上）
 */
export function computeGuides(mov, others, threshold = SNAP_PX) {
  if (!others || !others.length) return { dx: 0, dy: 0, guides: [] }

  const best = (horiz) => {
    const m = anchors(mov, horiz)
    let bestDelta = 0, bestDist = threshold + 1
    for (const o of others) {
      const oa = anchors(o, horiz)
      for (const mv of m) {
        for (const ov of oa) {
          const d = ov - mv
          const ad = Math.abs(d)
          if (ad <= threshold && ad < bestDist) { bestDist = ad; bestDelta = d }
        }
      }
    }
    return bestDist <= threshold ? { delta: bestDelta, dist: bestDist } : null
  }

  const bx = best(true)
  const by = best(false)
  const dx = bx ? bx.delta : 0
  const dy = by ? by.delta : 0

  // 吸附后的位置，用来算「两个对象之间的距离」并画线
  const snapped = { x: mov.x + dx, y: mov.y + dy, w: mov.w, h: mov.h }
  const guides = []
  const EPS = 0.6

  if (bx) {
    const targets = []
    for (const o of others) {
      for (const ov of anchors(o, true)) {
        for (const sv of anchors(snapped, true)) {
          if (Math.abs(ov - sv) <= EPS) targets.push({ pos: ov, o })
        }
      }
    }
    for (const g of dedupe(targets)) {
      // 距离标注：竖线是 x 方向对齐，两个对象的实际空隙在 y 方向（上下分开多少）
      const gap = snapped.y >= g.o.y + g.o.h ? snapped.y - (g.o.y + g.o.h)
        : (g.o.y >= snapped.y + snapped.h ? g.o.y - (snapped.y + snapped.h) : 0)
      guides.push({
        dir: 'v',
        pos: Math.round(g.pos),
        from: Math.round(Math.min(snapped.y, g.o.y)),
        to: Math.round(Math.max(snapped.y + snapped.h, g.o.y + g.o.h)),
        label: gap > 0.5 ? Math.round(gap) + 'px' : ''
      })
    }
  }

  if (by) {
    const targets = []
    for (const o of others) {
      for (const ov of anchors(o, false)) {
        for (const sv of anchors(snapped, false)) {
          if (Math.abs(ov - sv) <= EPS) targets.push({ pos: ov, o })
        }
      }
    }
    for (const g of dedupe(targets)) {
      // 横线是 y 方向对齐，空隙在 x 方向（左右分开多少）
      const gap = snapped.x >= g.o.x + g.o.w ? snapped.x - (g.o.x + g.o.w)
        : (g.o.x >= snapped.x + snapped.w ? g.o.x - (snapped.x + snapped.w) : 0)
      guides.push({
        dir: 'h',
        pos: Math.round(g.pos),
        from: Math.round(Math.min(snapped.x, g.o.x)),
        to: Math.round(Math.max(snapped.x + snapped.w, g.o.x + g.o.w)),
        label: gap > 0.5 ? Math.round(gap) + 'px' : ''
      })
    }
  }

  return { dx, dy, guides }
}

// 同一个位置可能被多个对象命中（左对齐到 3 个对象的左边），只留一条线
function dedupe(list) {
  const seen = new Map()
  for (const t of list) if (!seen.has(Math.round(t.pos))) seen.set(Math.round(t.pos), t)
  return [...seen.values()]
}
