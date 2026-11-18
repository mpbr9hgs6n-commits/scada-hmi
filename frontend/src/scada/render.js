// 组态画布共享渲染器 —— 编辑器与只读页 view 必须用同一个函数（硬约束 18）
// 用法：renderScada(containerEl, json, values, handlers)
//   values: { CODE: { val, ts, q } }
//   handlers: { onWrite(pointCode, value), onSelect(item, index, box) }
//
// 重要：结构不变时只做「数值更新」，不重建 DOM。
// 早期版本每次调用都 innerHTML='' 重建整棵树，导致每 1 秒新建一个 flv player 且从不销毁，
// 浏览器对单站点的 6 条 HTTP/1.1 连接被视频流占满，后续任何导航都拿不到 socket 而超时。
// 现在：结构签名没变 → 走 patch；变了才重建，重建前先销毁旧 player。

import { openNumericPad } from './numericPad'
import { defaultsOf } from './props'
import { tagOfVar } from './varbind'
import { controlDef } from './controls/registry'
import { symbolSvg } from './controls/symbols'
import { mountControl, updateControl, unmountControl } from './controls/host'
import { expandInstance, sizeOf } from './faceplate'
import { TK, MEDIUM, mediumOf, displayOf, demoFilter, DECK_DEBUG, fmtNum } from './deck'

const SIG_IGNORE = ['alarms'] // 报警列表属于运行数据，不算结构

function sigOf(data) {
  return JSON.stringify(data, (k, v) => (SIG_IGNORE.includes(k) ? undefined : v))
}

export function renderScada(container, json, values = {}, handlers = {}) {
  const data = typeof json === 'string' ? JSON.parse(json || '{}') : (json || {})
  if (!container) return null
  ensureScadaStyles()

  const prev = container.__scada
  if (prev && prev.sig === sigOf(data)) {
    // 结构没变：只同步外部缩放（编辑器 Ctrl+滚轮），不重建 DOM
    if (handlers.zoom != null && prev.setZoom) { try { prev.setZoom(handlers.zoom) } catch (e) { /* 忽略 */ } }
    try { prev.patch(values, data) } catch (e) { console.warn('[scada] 数值更新失败', e) }
    return prev.inner
  }

  destroyScada(container)

  faultHit = false      // ?fault=1 只打第一个设备，换画面重新来
  const stage = document.createElement('div')
  stage.className = 'scada-stage' + (DECK_DEBUG.fx === false ? ' sd-no-fx' : '')
  const W = data.width || 1600, H = data.height || 900
  stage.style.cssText = `position:relative;margin:0 auto;width:${W}px;height:${H}px;background:${data.bg || '#0b1622'};overflow:hidden;`
  const inner = document.createElement('div')
  inner.style.cssText = `position:absolute;left:0;top:0;transform-origin:top left;`
  inner.style.width = W + 'px'; inner.style.height = H + 'px'
  stage.appendChild(inner)
  container.appendChild(stage)

  // 适配：按容器宽高双向取小值缩放（画面完整不裁切），再按剩余高度垂直居中。
  // 用 ResizeObserver 而不是 window.resize —— 三栏拖宽、浏览器 125% 缩放都不会触发 resize。
  // zoom：编辑器视图缩放倍数（1 = 适应窗口），base 是适应窗口时的比例，两者相乘才是实际 scale。
  let zoom = Math.max(0.1, Math.min(8, Number(handlers.zoom) || 1))
  const fit = () => {
    const cw = container.clientWidth || W
    const ch = container.clientHeight || 0
    // 编辑器：画布尺寸 = 画面尺寸，1:1 不缩放（用户 2026-11-14 要求）。
    // 原来无条件按容器取小值缩放，设成 1600×900 也被缩到 912px 显示，
    // 用户看到的画布永远不是他设的那个尺寸。装不下由 .canvas-wrap 滚动。
    // 运行态（view / publish）仍按容器适应，大屏上要完整显示不裁切。
    const base = (handlers.mode === 'edit')
      ? 1
      : (ch ? Math.min(cw / W, ch / H, 1) : Math.min(cw / W, 1))
    const s = base * zoom
    stage.style.width = (W * s) + 'px'
    stage.style.height = (H * s) + 'px'
    stage.style.marginTop = ch ? Math.max(0, (ch - H * s) / 2) + 'px' : '0'
    inner.style.transform = `scale(${s})`
    if (handlers.onFit) { try { handlers.onFit(s, base) } catch (e) { /* 回调异常不影响渲染 */ } }
  }
  fit()
  const onResize = () => fit()
  let ro = null
  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(fit)
    ro.observe(container)
  } else {
    window.addEventListener('resize', onResize)
  }

  const patches = []   // [{ idx, fn(values, item) }]
  const pending = []   // 视频挂流：元素必须先进入文档
  const players = []   // 本轮创建的播放器，重建时统一销毁

  const items = data.items || []
  const styles = []   // [{ idx, node, R }] —— 属性面板就地改样式用
  const kidStyles = []  // P7 组合内的子对象（同样是就地改样式）
  const ctls = []     // P6 控件宿主节点，销毁时要逐个 unmount（否则定时器/SSE 泄漏）
  const paths = new Map()   // item 对象 → 节点路径（"3" 或 "3.i.0"），P7 图层/组合要用
  items.forEach((item, idx) => {
    const r = renderItem(item, values, handlers, String(idx), pending, players, paths)
    if (!r) return
    inner.appendChild(r.node)
    if (r.patch) patches.push({ idx, fn: r.patch })
    if (r.R && r.R.host) ctls.push(r.R.host)
    if (r.R) styles.push({ idx, node: r.node, R: r.R, item })
    if (r.kids) {
      for (const k of r.kids) {
        kidStyles.push(k)
        // 子对象也要进 st.items：动态化、事件、控件订阅都按这一个列表遍历。
        // 没有这一步，组件模板里的液位罐/指示灯就永远不动（P8 的核心，别删）。
        styles.push({ kid: true, idx: (k.item && k.item.name) || '', node: k.node, R: k.R, item: k.item })
      }
    }
    if (handlers.onSelect) {
      r.node.style.cursor = 'pointer'
      r.node.onclick = (e) => { e.stopPropagation(); handlers.onSelect(item, idx, r.node) }
    }
  })

  const st = {
    sig: sigOf(data),
    inner,
    players,
    ctls,
    paths,
    // 动态化层（dyn.js）要用：每个对象的节点、节点引用、原始 item
    items: styles,
    data,
    onResize,
    ro,
    // 视图缩放：只改 fit 的倍数，不动 items / 不重建 DOM
    setZoom(z) {
      const n = Math.max(0.1, Math.min(8, Number(z) || 1))
      if (n === zoom) return
      zoom = n
      fit()
    },
    getZoom() { return zoom },
    // 属性面板改属性时只调它：就地改样式，不重建 DOM。
    // 重建会把视频 player 销毁重连、把输入焦点冲掉，改个字号就闪一下，不能这么干。
    restyle() {
      const arr = data.items || []
      for (const s of styles) {
        if (s.kid) continue                       // 子对象统一走下面 kidStyles 那一遍
        const it = arr[s.idx]
        if (it) { try { applyItemStyle(s.node, it, s.R) } catch (e) { /* 单个对象异常不影响整页 */ } }
      }
      // 组合里的子对象：直接用它们的节点与 R 就地刷样式（不重建，不然组内视频会重连）
      for (const k of kidStyles) {
        try { applyItemStyle(k.node, k.item, k.R) } catch (e) { /* 同上 */ }
      }
      st.sig = sigOf(data)     // 样式已与数据一致，别让下次调用误判结构变了而整棵重建
    },
    patch(vals, d) {
      // ?freeze=1：首帧照常渲染，之后冻结数值刷新（稳定截图用——数字一直跳截不出一致的图）
      if (DECK_DEBUG.freeze && st.__froze) return
      const arr = d.items || []
      for (const p of patches) {
        const it = arr[p.idx]
        if (it) { try { p.fn(vals, it) } catch (e) { /* 单个组件出错不影响整页 */ } }
      }
      if (DECK_DEBUG.freeze) st.__froze = true
    }
  }
  container.__scada = st

  st.patch(values, data)          // 首帧数值
  pending.forEach(fn => { try { fn() } catch (e) { console.warn('[scada] 视频挂载失败', e) } })
  return inner
}

// 显式销毁（页面卸载时调用，或结构重建时内部调用）
export function destroyScada(container) {
  if (!container) return
  const st = container.__scada
  if (st) {
    for (const h of st.players) {
      try { if (h.player) { h.player.destroy() } } catch (e) { /* 已销毁 */ }
      h.player = null
      h.src = null
    }
    if (st.ro) { try { st.ro.disconnect() } catch (e) { /* 已断开 */ } }
    if (st.onResize) window.removeEventListener('resize', st.onResize)
    // 事件的 document 级兜底监听（瞬时按钮松手归零用），不摘会在换画面时越积越多
    if (st.__docUp) { document.removeEventListener('mouseup', st.__docUp); st.__docUp = null }
    if (st.__armedL) st.__armedL.clear()
    if (st.__armedR) st.__armedR.clear()
    for (const h of (st.ctls || [])) {
      try { unmountControl(h) } catch (e) { /* 单个控件卸载失败不影响整页销毁 */ }
    }
  }
  container.__scada = null
  container.__picOpened = false      // 下次重建/换画面时 picture.open 还要能再触发
  container.innerHTML = ''
}

function el(tag, css, text) {
  const e = document.createElement(tag)
  if (css) e.style.cssText = css
  if (text !== undefined) e.textContent = text
  return e
}

// 把「变量表达式」化成可写的具体点位：
//   '@CurrentSite + ".LEVEL"' → 'S001.LEVEL'；'S001.LEVEL' → 原样；'LEVEL' → 原样（运行时补站点）
// 复杂表达式（算术/三元）不猜，返回空串 —— 输入框会提示"没有可写目标"
function evalTagExpr(expr, site) {
  const e = String(expr || '').trim()
  if (!e) return ''
  const m = e.replace(/\s+/g, '').match(/^@CurrentSite\+['"]\.([A-Za-z0-9_$]+)['"]$/)
  if (m) return site ? site + '.' + m[1] : ''
  if (/^[A-Za-z0-9_$]+(\.[A-Za-z0-9_$]+)?$/.test(e)) return e
  return ''
}

// I/O 域写回目标：动态化 tag > 间接连接 > 旧格式 var
function ioTagOf(item, site) {
  // 提示词 10 4.3：变量以 { site, point } 对象为准；字符串格式不猜、不兼容
  const d = item.dyn && item.dyn.value
  if (d && d.mode === 'tag' && d.expr) return evalTagExpr(d.expr, site)
  if (d && d.mode === 'indirect' && d.nameExpr) return evalTagExpr(d.nameExpr, site)
  return tagOfVar(item.var)
}

// 取值：v 可以是 {site,point} 对象（提示词 10 4.3 正牌格式）或裸字符串（P1 老画面）
// 对象直接当键用会取到 values["[object Object]"]，运行态永远是 --（verify 只验格式验不出来）
function valOf(values, v) {
  if (!v) return null
  const key = (typeof v === 'object' && !Array.isArray(v)) ? tagOfVar(v) : v
  if (!key) return null
  const x = values[key]
  return x ? x.val : null
}

// —— 统一取值 + 质量码三态（提示词 11 §3.1：所有绑定组件共用这一个，禁止各写各的）——
// 返回 { found, val, state, display, dot }：
//   state: good / bad / stale / nodata；display: 非 good 一律 '--'，绝不显示 0
// item.var 三种来源：
//   {site,point} 对象（提示词 10 4.3 的正牌格式）→ handlers.readFull(tag)（跨站点可用）
//   裸字符串（P1 老画面）→ 当前站点 flat 表
//   没绑 → nodata
function readVar(vals, item, handlers) {
  const v = item && item.var
  let rec = null
  if (v && typeof v === 'object' && !Array.isArray(v)) {
    const tag = tagOfVar(v)
    if (tag) {
      let r = handlers && handlers.readFull ? handlers.readFull(tag) : null
      if (r && r.found) {
        // pollMs / obsMs 必须带下去：boundState 按「有效周期×3」判 stale
        // dtype 也必须带：数值显示按点位类型决定小数位（见 deck.js fmtNum）
        rec = { val: r.val, ts: r.ts, q: r.q, pollMs: r.pollMs, obsMs: r.obsMs,
                dtype: r.dtype }
      } else if (vals && v.point !== undefined) {
        rec = vals[v.point] || null      // 兜底：flat 表（编辑器没传 readFull 时）
      }
    }
  } else if (typeof v === 'string' && v) {
    rec = vals ? (vals[v] || null) : null
  }
  return displayOf(demoFilter(rec))
}

// 旧式 var 通道（P1 就有的 item.var）与 P4 动态化可能指向同一个属性。
// 一个属性只能有一个驱动源：dyn.js 每帧把「这个对象已被动态化接管的属性」记在这里，
// 下面 patch 就不再写它 —— 否则动态化求值失败（点位不存在）时，
// 旧通道会把属性写成 --，违反「求值失败时属性保持上一次的值」。
function dynOwns(box, key) {
  const s = box.__dynOwns
  return !!(s && s.has && s.has(key))
}

// 注意：旧 fmt(val,item) 已废弃 —— 它拿不到点位类型，无法区分 bool/int/float。
// 所有数值显示一律走 deck.js 的 fmtNum(val, rec, item)。

// 图元配色（与既有组件同一套，别另起色板）
const C = { stroke: '#2c4a6e', line: '#7cc4ff', accent: '#1ec8ff', text: '#9fc3e8', bg: '#0e1f33' }

// 提示词 11：这些矢量图元支持「绑变量 → 状态色 + 动画」
const DECK_DYN = new Set(['pump_v', 'pump_h', 'fan', 'valve', 'grill', 'conveyor', 'pipe_v', 'pipe_t', 'pipe_elbow'])
// ?fault=1 的「第一个故障设备」标记（renderScada 整树重建时重置）
let faultHit = false

// 线型：面板里存 solid/dash/dot/dashdot，CSS 要 dashed/dotted
const LS = { solid: 'solid', dash: 'dashed', dot: 'dotted', dashdot: 'dashed' }

function numOr(v, dflt) {
  const n = Number(v)
  return (v === undefined || v === null || v === '' || isNaN(n)) ? dflt : n
}

// 图元色板：只认「用户显式设置过」的属性，没设过就沿用原来的常量色。
// 这样老画面（模板那张）的观感跟 P1/P2 一模一样，不会被属性面板悄悄改色。
function palOf(item) {
  const d = defaultsOf(item.type)
  const solid = (item.fillMode || d.fillMode || 'solid') !== 'none'
  const fill = item.fill || ''
  return {
    stroke: item.stroke || C.stroke,
    line: item.stroke || C.line,
    accent: fill || C.accent,
    text: item.color || C.text,
    bg: fill || C.bg,
    fillSoft: !solid ? 'none' : (fill || 'rgba(30,200,255,.16)'),
    sw: numOr(item.strokeWidth, 2)
  }
}

// 字体：fontSize 缺省或 0 表示「自动」（按对象高度算）
function applyFont(node, item, autoSize, autoColor, autoAlign) {
  if (!node) return
  node.style.fontSize = (numOr(item.fontSize, 0) || autoSize) + 'px'
  node.style.color = item.color || autoColor
  node.style.fontFamily = item.fontFamily || ''
  node.style.fontWeight = item.bold ? '700' : ''
  node.style.fontStyle = item.italic ? 'italic' : ''
  node.style.textAlign = item.align || autoAlign || ''
}

// 把属性落到「已经建好的 DOM」上。
// 关键：只改样式、不重建节点 —— 所以改颜色/字号不会打断视频流、不会丢输入焦点。
// 面板每改一个字段就调它一次（P3 的「立刻反映到画布」）。
export function applyItemStyle(box, item, R) {
  const d = defaultsOf(item.type)
  const w = Math.max(1, numOr(item.w, 100))
  const h = Math.max(1, numOr(item.h, 40))
  box.style.left = numOr(item.x, 0) + 'px'
  box.style.top = numOr(item.y, 0) + 'px'
  box.style.width = w + 'px'
  box.style.height = h + 'px'

  const stroke = item.stroke || d.stroke || C.stroke
  const sw = numOr(item.strokeWidth, d.strokeWidth === undefined ? 1 : d.strokeWidth)
  const ls = LS[item.lineStyle || d.lineStyle || 'solid'] || 'solid'
  const radius = numOr(item.radius, d.radius || 0)
  const fill = item.fill || d.fill || '#0e1f33'
  const solid = (item.fillMode || d.fillMode || 'solid') !== 'none'
  const bd = sw > 0 ? `${sw}px ${ls} ${stroke}` : 'none'

  if (R.vec) {
    // 矢量图元：按新尺寸和新色板重画 svg（只换 innerHTML，不动别的节点）
    R.svg.setAttribute('viewBox', `0 0 ${w} ${h}`)
    R.svg.innerHTML = R.vec(w, h, item, palOf(item))
    if (R.label) applyFont(R.label, item, Math.max(9, Math.min(12, h * 0.22)), C.text, 'center')
  } else if (R.rebuild) {
    // 提示词 11 大屏组件（kpi/progress/ring/statusbadge/panel）：外观自带（scada-deck 风格），
    // 改尺寸/文字时重建内容即可，不吃通用边框填充
    R.rebuild()
  } else {
    switch (item.type) {
      case 'rect':
        box.style.background = solid ? fill : 'transparent'
        box.style.border = bd
        box.style.borderRadius = radius + 'px'
        break

      case 'circle':
        box.style.background = solid ? fill : 'transparent'
        box.style.border = bd
        box.style.borderRadius = '50%'
        break

      case 'text': {
        box.style.background = solid ? fill : 'transparent'
        box.style.border = bd
        box.style.borderRadius = radius + 'px'
        box.style.display = 'flex'
        box.style.alignItems = ({ top: 'flex-start', middle: 'center', bottom: 'flex-end' })[item.valign || 'top']
        box.style.justifyContent = ({ left: 'flex-start', center: 'center', right: 'flex-end' })[item.align || 'left']
        if (R.txt) {
          R.txt.textContent = item.text || item.label || ''
          applyFont(R.txt, item, 16, '#e2e8f0', 'left')
        }
        break
      }

      case 'tank': {
        const lc = item.liquidColor || d.liquidColor
        const up = (item.direction || d.direction) !== 'down'
        box.style.background = solid ? fill : 'transparent'
        box.style.border = bd
        box.style.borderRadius = radius + 'px'
        if (R.liquid) {
          R.liquid.style.background = `linear-gradient(${up ? '180deg' : '0deg'},${lc},${lc}88)`
          R.liquid.style.top = up ? 'auto' : '0'
          R.liquid.style.bottom = up ? '0' : 'auto'
        }
        applyFont(R.label, item, 13, '#9fc3e8', 'center')
        applyFont(R.val, item, 20, '#ffffff', 'center')
        break
      }

      case 'pump': {
        const m = Math.max(8, Math.min(w, h) - 20)
        if (R.circle) { R.circle.style.width = m + 'px'; R.circle.style.height = m + 'px' }
        if (R.paint) R.paint()
        applyFont(R.label, item, 12, '#9fc3e8', 'center')
        break
      }

      case 'pipe': {
        if (R.paint) R.paint()
        break
      }

      case 'value':
      case 'input': {
        box.style.background = solid ? fill : 'transparent'
        box.style.border = bd
        box.style.borderRadius = radius + 'px'
        box.style.alignItems = ({ top: 'flex-start', middle: 'center', bottom: 'flex-end' })[item.valign || 'middle']
        box.style.justifyContent = ({ left: 'flex-start', center: 'center', right: 'flex-end' })[item.align || 'center']
        applyFont(R.label, item, 13, '#9fc3e8', '')
        applyFont(R.num, item, Math.max(10, h * 0.55), '#e2e8f0', '')
        if (R.unit) R.unit.textContent = item.unit || ''
        break
      }

      case 'button': {
        if (R.btn) {
          R.btn.style.background = solid ? fill : 'transparent'
          R.btn.style.border = bd
          R.btn.style.borderRadius = radius + 'px'
          applyFont(R.btn, item, 14, '#ffffff', 'center')
        }
        break
      }

      case 'lamp': {
        if (R.dot) {
          const m = Math.min(w, h)
          R.dot.style.width = m + 'px'
          R.dot.style.height = m + 'px'
          if (R.paint) R.paint()
        }
        applyFont(R.label, item, 11, '#9fc3e8', 'center')
        break
      }

      case 'video': {
        box.style.border = bd
        box.style.borderRadius = radius + 'px'
        if (R.vid) R.vid.style.borderRadius = radius + 'px'
        applyFont(R.label, item, 12, '#9fc3e8', '')
        break
      }

      case 'control': {
        box.style.border = bd
        box.style.borderRadius = radius + 'px'
        box.style.background = solid ? fill : 'transparent'
        break
      }

      // P7 组合：组框只是容器，不画边框不画底（选中时由覆盖层画虚线框）
      case 'group': {
        box.style.background = 'transparent'
        box.style.border = 'none'
        break
      }

      // P8 组件模板实例：实例框同样只是容器（模板内部自己画），模板缺定义时保留红虚线
      case 'faceplate': {
        box.style.background = 'transparent'
        if (!R.missing) box.style.border = 'none'
        break
      }

      // P8 图片对象：图片地址改了要换 src（占位块随之隐藏/显示）
      case 'image': {
        box.style.border = bd
        box.style.borderRadius = radius + 'px'
        if (R.img && item.src !== undefined) {
          const s2 = String(item.src || '')
          if (s2 && R.img.getAttribute('src') !== s2) R.img.src = s2
          R.img.style.display = s2 ? '' : 'none'
          if (R.ph) R.ph.style.display = s2 ? 'none' : 'flex'
        }
        break
      }

      case 'alarm_list': {
        box.style.background = solid ? fill : 'transparent'
        box.style.border = bd
        box.style.borderRadius = radius + 'px'
        if (R.title) applyFont(R.title, item, 13, '#9fc3e8', '')
        break
      }

      default:
        // 未知类型：只加边框，避免整块塌掉
        box.style.border = bd
        box.style.borderRadius = radius + 'px'
    }
  }

  // 通用项放在最后，保证不被上面的 background 简写冲掉
  box.style.opacity = String(Math.max(0, Math.min(100, numOr(item.opacity, 100))) / 100)
  const rot = numOr(item.rot, 0)
  box.style.transform = rot ? `rotate(${rot}deg)` : ''
  box.style.transformOrigin = '50% 50%'
  if (item.bgImage) {
    box.style.backgroundImage = `url("${item.bgImage}")`
    box.style.backgroundSize = 'cover'
    box.style.backgroundPosition = 'center'
  } else if (box.style.backgroundImage) {
    box.style.backgroundImage = ''
  }
}


// 矢量图元：标准对象 / 工艺图元 / 控件占位。
// 这些形状目前是静态符号（P1 只要求"插入后看得见"），运行数据接入在 P4-P6 做。
const VECTOR = {
  // —— 标准对象 ——
  line: (w, h, it, p) => `<line x1="0" y1="${h / 2}" x2="${w}" y2="${h / 2}" stroke="${p.line}" stroke-width="${p.sw}"/>`,

  polyline: (w, h, it, p) => `<polyline points="0,${h * 0.78} ${w * 0.33},${h * 0.22} ${w * 0.66},${h * 0.78} ${w},${h * 0.3}"
    fill="none" stroke="${p.line}" stroke-width="${p.sw}"/>`,

  polygon: (w, h, it, p) => `<polygon points="${w / 2},1 ${w - 1},${h - 1} 1,${h - 1}"
    fill="${p.fillSoft}" stroke="${p.accent}" stroke-width="${p.sw}"/>`,

  ellipse: (w, h, it, p) => `<ellipse cx="${w / 2}" cy="${h / 2}" rx="${Math.max(1, w / 2 - 1)}" ry="${Math.max(1, h / 2 - 1)}"
    fill="${p.fillSoft}" stroke="${p.accent}" stroke-width="${p.sw}"/>`,

  arc: (w, h, it, p) => `<path d="M1,${h - 1} A ${Math.max(1, w / 2 - 1)},${Math.max(1, h - 2)} 0 0 1 ${w - 1},${h - 1}"
    fill="none" stroke="${p.accent}" stroke-width="${p.sw * 1.5}"/>`,

  // —— 工艺图元（提示词 11：按 scada-deck 视觉基准重画，支持状态色 st）——
  // st = { run: bool, fault: bool, open: bool, stale: bool }
  // 原则 4：设备本体中性色，状态靠描边/光圈/灯，不整体染色
  pump_v: (w, h, it, p, st) => {
    const cx = w / 2, r = Math.min(w, h) * 0.3
    const c = st && st.fault ? TK.warning : (st && st.run ? TK.success : TK.offline)
    const glow = st && st.run ? `drop-shadow(0 0 6px ${TK.success})` : 'none'
    return `<line x1="${cx}" y1="0" x2="${cx}" y2="${h / 2 - r}" stroke="${TK.pipeBase}" stroke-width="5"/>
      <line x1="${cx}" y1="${h / 2 + r}" x2="${cx}" y2="${h}" stroke="${TK.pipeBase}" stroke-width="5"/>
      <circle cx="${cx}" cy="${h / 2}" r="${r}" fill="#0e2638" stroke="${c}" stroke-width="${p.sw + 1}"
        style="filter:${glow}" class="${st && st.fault ? 'scada-blink' : ''}"/>
      <g class="${st && st.run ? 'sd-rot' : ''}" style="transform-origin:${cx}px ${h / 2}px">
        <path d="M${cx},${h / 2} m0,${-r * 0.75} a${r * 0.75},${r * 0.75} 0 0 1 ${r * 0.65},${r * 0.38}
          a${r * 0.5},${r * 0.5} 0 0 0 ${-r * 0.65},${r * 0.2} z" fill="${c}" opacity=".9"/>
      </g>
      <circle cx="${cx}" cy="${h / 2}" r="${Math.max(1.5, r * 0.18)}" fill="${TK.text2}"/>`
  },

  pump_h: (w, h, it, p, st) => {
    const cy = h / 2, r = Math.min(w, h) * 0.3
    const c = st && st.fault ? TK.warning : (st && st.run ? TK.success : TK.offline)
    const glow = st && st.run ? `drop-shadow(0 0 6px ${TK.success})` : 'none'
    return `<line x1="0" y1="${cy}" x2="${w / 2 - r}" y2="${cy}" stroke="${TK.pipeBase}" stroke-width="5"/>
      <line x1="${w / 2 + r}" y1="${cy}" x2="${w}" y2="${cy}" stroke="${TK.pipeBase}" stroke-width="5"/>
      <circle cx="${w / 2}" cy="${cy}" r="${r}" fill="#0e2638" stroke="${c}" stroke-width="${p.sw + 1}"
        style="filter:${glow}" class="${st && st.fault ? 'scada-blink' : ''}"/>
      <g class="${st && st.run ? 'sd-rot' : ''}" style="transform-origin:${w / 2}px ${cy}px">
        <path d="M${w / 2},${cy} m0,${-r * 0.75} a${r * 0.75},${r * 0.75} 0 0 1 ${r * 0.65},${r * 0.38}
          a${r * 0.5},${r * 0.5} 0 0 0 ${-r * 0.65},${r * 0.2} z" fill="${c}" opacity=".9"/>
      </g>
      <circle cx="${w / 2}" cy="${cy}" r="${Math.max(1.5, r * 0.18)}" fill="${TK.text2}"/>`
  },

  // 蝶阀（scada-deck valve-butterfly）：开=绿 描边+扳手横，关=红 描边+扳手竖
  valve: (w, h, it, p, st) => {
    const cx = w / 2, cy = h / 2, r = Math.min(w, h) / 2 - 1
    const open = !st || st.open
    const c = open ? TK.success : TK.danger
    const ang = open ? 0 : -45
    return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="#0d2334" stroke="${c}" stroke-width="${p.sw + 1}"/>
      <line x1="${cx - r * 0.7}" y1="${cy}" x2="${cx + r * 0.7}" y2="${cy}" stroke="${c}" stroke-width="2"
        transform="rotate(${ang} ${cx} ${cy})"/>
      <circle cx="${cx}" cy="${cy}" r="${Math.max(1.5, r * 0.16)}" fill="${c}"/>`
  },

  pipe_v: (w, h, it, p, st) => {
    const m = mediumOf(it), bw = w * 0.32
    const flow = st && st.run
    return `<rect x="${w / 2 - bw / 2}" y="0" width="${bw}" height="${h}" fill="${TK.pipeBase}" rx="${bw / 2}"/>
      <rect x="${w / 2 - bw * 0.28}" y="0" width="${bw * 0.56}" height="${h}"
        fill="${m.color}" opacity="${m.opacity}" rx="${bw * 0.28}"/>
      <line x1="${w / 2}" y1="0" x2="${w / 2}" y2="${h}" stroke="${flow ? m.color : 'none'}" stroke-width="${bw * 0.5}"
        stroke-dasharray="6 10" class="${flow ? 'sd-flowline-v' : ''}" opacity=".55"/>`
  },

  pipe_t: (w, h, it, p, st) => {
    const m = mediumOf(it), t = Math.max(6, h * 0.32)
    const flow = st && st.run
    return `<rect x="0" y="${h / 2 - t / 2}" width="${w}" height="${t}" fill="${TK.pipeBase}" rx="${t / 2}"/>
      <rect x="${w / 2 - t / 2}" y="${h / 2}" width="${t}" height="${h / 2}" fill="${TK.pipeBase}" rx="${t / 2}"/>
      <rect x="${t * 0.22}" y="${h / 2 - t * 0.28}" width="${w - t * 0.44}" height="${t * 0.56}"
        fill="${m.color}" opacity="${m.opacity}" rx="${t * 0.28}"/>
      <line x1="${t * 0.3}" y1="${h / 2}" x2="${w - t * 0.3}" y2="${h / 2}" stroke="${flow ? m.color : 'none'}"
        stroke-width="${t * 0.56}" stroke-dasharray="6 10" class="${flow ? 'sd-flowline-h' : ''}" opacity=".55"/>`
  },

  pipe_elbow: (w, h, it, p, st) => {
    const m = mediumOf(it)
    const t = Math.max(6, Math.min(w, h) * 0.4)
    const flow = st && st.run
    return `<path d="M${t / 2},0 L${t / 2},${h - t / 2} L${w},${h - t / 2}" fill="none"
      stroke="${TK.pipeBase}" stroke-width="${t}" stroke-linecap="round"/>
      <path d="M${t / 2},${t * 0.3} L${t / 2},${h - t / 2} L${w - t * 0.3},${h - t / 2}" fill="none"
      stroke="${m.color}" opacity="${m.opacity}" stroke-width="${t * 0.5}" stroke-linecap="round"/>
      <path d="M${t / 2},${t * 0.3} L${t / 2},${h - t / 2} L${w - t * 0.3},${h - t / 2}" fill="none"
      stroke="${flow ? m.color : 'none'}" stroke-width="${t * 0.5}" stroke-dasharray="6 10"
      class="${flow ? 'sd-flowline-elbow' : ''}" opacity=".55" stroke-linecap="round"/>`
  },

  // 风机（scada-deck fan-unit）：run=三叶轮旋转，stop=红叶轮静止，fault=琥珀闪
  fan: (w, h, it, p, st) => {
    const cx = w / 2, cy = h / 2, r = Math.min(w, h) / 2 - 1
    const c = st && st.fault ? TK.warning : (st && st.run ? TK.success : TK.danger)
    let blades = ''
    for (const a of [0, 120, 240]) {
      blades += `<path d="M${cx},${cy} Q ${cx + r * 0.95},${cy - r * 0.15} ${cx + r * 0.72},${cy - r * 0.72}
        Q ${cx + r * 0.2},${cy - r * 0.45} ${cx},${cy} Z"
        fill="${c}" opacity=".85" transform="rotate(${a} ${cx} ${cy})"/>`
    }
    return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="#0a1e2d" stroke="${c}" stroke-width="${p.sw + 1}"
      style="${st && st.run ? `filter:drop-shadow(0 0 6px ${TK.success})` : ''}" class="${st && st.fault ? 'scada-blink' : ''}"/>
      <g class="${st && st.run ? 'sd-rot' : ''}" style="transform-origin:${cx}px ${cy}px">${blades}</g>
      <circle cx="${cx}" cy="${cy}" r="${Math.max(1.5, r * 0.14)}" fill="${TK.text2}"/>`
  },

  // 格栅机（scada-deck screen-mesh）：倾斜耙网 + 运行时耙齿往复（横向投影，不 360° 转）
  grill: (w, h, it, p, st) => {
    const n = Math.max(3, Math.round(w / 14))
    const gap = w / n
    const c = st && st.fault ? TK.warning : (st && st.run ? TK.accent : TK.lineLight)
    let s = `<rect x="1" y="1" width="${w - 2}" height="${h - 2}" fill="none" stroke="${c}" stroke-width="${p.sw}" rx="2"
      transform="skewX(-8)" class="${st && st.fault ? 'scada-blink' : ''}"/>`
    for (let i = 1; i < n; i++) {
      s += `<line x1="${i * gap}" y1="1" x2="${i * gap}" y2="${h - 1}" stroke="${c}" stroke-width="${Math.max(1, h * 0.05)}"
        transform="skewX(-8)"/>`
    }
    // 耙齿小车：运行时上下往复
    s += `<rect x="${w * 0.2}" y="${h * 0.5 - 4}" width="${w * 0.6}" height="8" rx="2" fill="${TK.text2}" opacity=".8"
      class="${st && st.run ? 'sd-rake' : ''}"/>`
    return s
  },

  // 螺旋输送机（scada-deck conveyor）：U 形槽 + 螺旋纹滚动（stale/停止时纹路停）
  conveyor: (w, h, it, p, st) => {
    const r = Math.min(h * 0.28, w * 0.08)
    const c = st && st.fault ? TK.warning : (st && st.run ? TK.success : TK.offline)
    let screw = ''
    const n = Math.max(4, Math.round(w / 16))
    for (let i = 0; i < n; i++) {
      screw += `<line x1="${(w - 2 * r) * (i / n) + r}" y1="${h / 2 - h * 0.16}" x2="${(w - 2 * r) * ((i + 0.5) / n) + r}"
        y2="${h / 2 + h * 0.16}" stroke="${TK.text2}" stroke-width="2" opacity=".8"/>`
    }
    return `<path d="M${r},${h / 2 - h * 0.22} L${w - r},${h / 2 - h * 0.22} A ${r * 0.7},${h * 0.24} 0 0 1 ${w - r},${h / 2 + h * 0.22}
      L${r},${h / 2 + h * 0.22} A ${r * 0.7},${h * 0.24} 0 0 1 ${r},${h / 2 - h * 0.22} Z"
      fill="#0a1e2d" stroke="${c}" stroke-width="${p.sw}" class="${st && st.fault ? 'scada-blink' : ''}"/>
      <g class="${st && st.run ? 'sd-screw' : ''}">${screw}</g>
      <circle cx="${r + 1}" cy="${h / 2}" r="${r * 0.5}" fill="#0e2638" stroke="${c}" stroke-width="2"
        class="${st && st.run ? 'sd-rot' : ''}" style="transform-origin:${r + 1}px ${h / 2}px"/>
      <circle cx="${w - r - 1}" cy="${h / 2}" r="${r * 0.5}" fill="#0e2638" stroke="${c}" stroke-width="2"
        class="${st && st.run ? 'sd-rot' : ''}" style="transform-origin:${w - r - 1}px ${h / 2}px"/>`
  },

  // —— 控件占位（P6 换成真控件，P1 先给可辨认的外形）——
  gauge: (w, h, it, p) => {
    const cx = w / 2, cy = h * 0.78, r = Math.min(w / 2, h * 0.72) - 2
    let ticks = ''
    for (let i = 0; i <= 10; i++) {
      const a = Math.PI + (Math.PI * i) / 10
      const x1 = cx + Math.cos(a) * r, y1 = cy + Math.sin(a) * r
      const x2 = cx + Math.cos(a) * (r - r * 0.12), y2 = cy + Math.sin(a) * (r - r * 0.12)
      ticks += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${p.text}" stroke-width="1.5"/>`
    }
    const na = Math.PI + Math.PI * 0.62
    return `<path d="M${cx - r},${cy} A ${r},${r} 0 0 1 ${cx + r},${cy}" fill="none" stroke="${p.stroke}" stroke-width="${p.sw}"/>
      ${ticks}
      <line x1="${cx}" y1="${cy}" x2="${cx + Math.cos(na) * r * 0.8}" y2="${cy + Math.sin(na) * r * 0.8}"
        stroke="${p.accent}" stroke-width="2.5"/>`
  },

  clock: (w, h, it, p) => {
    const cx = w / 2, cy = h / 2, r = Math.min(w, h) / 2 - 1
    return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${p.bg}" stroke="${p.accent}" stroke-width="${p.sw}"/>
      <line x1="${cx}" y1="${cy}" x2="${cx}" y2="${cy - r * 0.55}" stroke="${p.text}" stroke-width="${p.sw}"/>
      <line x1="${cx}" y1="${cy}" x2="${cx + r * 0.45}" y2="${cy + r * 0.2}" stroke="${p.text}" stroke-width="${p.sw}"/>
      <circle cx="${cx}" cy="${cy}" r="1.5" fill="${p.accent}"/>`
  },

  table: (w, h, it, p) => {
    const rows = 5, rh = h / rows
    let s = `<rect x="1" y="1" width="${w - 2}" height="${h - 2}" fill="${p.bg}" stroke="${p.stroke}" stroke-width="1.5"/>
      <rect x="1" y="1" width="${w - 2}" height="${rh}" fill="rgba(30,200,255,.12)"/>`
    for (let i = 1; i < rows; i++) s += `<line x1="1" y1="${i * rh}" x2="${w - 1}" y2="${i * rh}" stroke="${p.stroke}" stroke-width="1"/>`
    for (const x of [w * 0.34, w * 0.67]) s += `<line x1="${x}" y1="1" x2="${x}" y2="${h - 1}" stroke="${p.stroke}" stroke-width="1"/>`
    return s
  },

  trend: (w, h, it, p) => {
    let s = `<rect x="1" y="1" width="${w - 2}" height="${h - 2}" fill="${p.bg}" stroke="${p.stroke}" stroke-width="1.5"/>`
    for (let i = 1; i < 4; i++) s += `<line x1="1" y1="${(h * i) / 4}" x2="${w - 1}" y2="${(h * i) / 4}" stroke="${p.stroke}" stroke-width="1" stroke-dasharray="3 5"/>`
    for (let i = 1; i < 6; i++) s += `<line x1="${(w * i) / 6}" y1="1" x2="${(w * i) / 6}" y2="${h - 1}" stroke="${p.stroke}" stroke-width="1" stroke-dasharray="3 5"/>`
    s += `<polyline points="0,${h * 0.7} ${w * 0.2},${h * 0.45} ${w * 0.4},${h * 0.6} ${w * 0.6},${h * 0.25} ${w * 0.8},${h * 0.4} ${w},${h * 0.18}"
      fill="none" stroke="${p.accent}" stroke-width="${p.sw}"/>`
    return s
  },

  xy: (w, h, it, p) => `<line x1="2" y1="${h - 2}" x2="${w - 2}" y2="${h - 2}" stroke="${p.stroke}" stroke-width="1.5"/>
    <line x1="2" y1="2" x2="2" y2="${h - 2}" stroke="${p.stroke}" stroke-width="1.5"/>
    <path d="M4,${h - 8} Q ${w * 0.35},${h * 0.15} ${w - 4},${h * 0.55}" fill="none" stroke="${p.accent}" stroke-width="${p.sw}"/>`,

  image: (w, h, it, p) => `<rect x="1" y="1" width="${w - 2}" height="${h - 2}" fill="${p.bg}" stroke="${p.stroke}" stroke-width="1.5"/>
    <circle cx="${w * 0.72}" cy="${h * 0.28}" r="${Math.min(w, h) * 0.08}" fill="${p.text}" opacity=".7"/>
    <path d="M4,${h - 4} L${w * 0.35},${h * 0.42} L${w * 0.55},${h * 0.7} L${w * 0.72},${h * 0.5} L${w - 4},${h - 4} Z"
      fill="${p.stroke}" opacity=".8"/>`,

  input: (w, h, it, p) => `<rect x="1" y="1" width="${w - 2}" height="${h - 2}" fill="${p.bg}" stroke="${p.stroke}" stroke-width="1.5"/>
    <rect x="${w - Math.min(w * 0.22, 26)}" y="1" width="${Math.min(w * 0.22, 26) - 1}" height="${h - 2}" fill="${p.stroke}"/>
    <line x1="6" y1="${h / 2}" x2="${w * 0.45}" y2="${h / 2}" stroke="${p.text}" stroke-width="${p.sw}" opacity=".6"/>`,

  // 符号库图元（P6）：14 个工艺符号，按 item.symbol 选形状
  symbol: (w, h, it, p) => symbolSvg((it && it.symbol) || 'pump_v', w, h, p)
}

function renderItem(item, values, handlers, path, pending, players, paths) {
  if (item.hidden) return null        // P7：隐藏的对象不渲染，但数据留在 json 里
  if (paths) paths.set(item, path)
  const { type, x = 0, y = 0, w = 100, h = 40, var: v, label } = item
  const box = el('div', `position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px;`)
  box.dataset.idx = path
  // 便于调试与验收定位（也方便用户在看 DOM 时认出对象名）
  if (item.name) box.dataset.name = item.name
  // P7：锁定的对象画布上不可选中、不可拖动，但仍然可见（官方语义）
  if (item.locked) box.style.pointerEvents = 'none'
  let patch = null
  const R = { kind: type }      // 属性套用需要的节点引用（applyStyle 用）

  // —— P7 组合：{ type:'group', items:[…] }，子对象存相对坐标 ——
  // 组框本身只是一层容器；子节点带 data-gpath，由 canvas.js 决定「点它算选组还是选子对象」
  if (type === 'group') {
    box.style.overflow = 'visible'
    if (item.name) box.dataset.group = '1'
    const inner = el('div', 'position:absolute;left:0;top:0;width:100%;height:100%;')
    box.appendChild(inner)
    const kids = []
    const kidPatches = []
    ;(item.items || []).forEach((c, i) => {
      const rr = renderItem(c, values, handlers, path + '.i.' + i, pending, players, paths)
      if (!rr) return
      rr.node.dataset.gpath = path
      inner.appendChild(rr.node)
      if (rr.patch) kidPatches.push({ fn: rr.patch, item: c })
      if (rr.R) kids.push({ item: c, node: rr.node, R: rr.R })
      if (rr.kids) for (const k of rr.kids) kids.push(k)
    })
    R.inner = inner
    R.kids = kids
    patch = (vals) => {
      for (const f of kidPatches) { try { f.fn(vals, f.item) } catch (e) { /* 单个子对象异常不影响整组 */ } }
    }
    applyItemStyle(box, item, R)
    return { node: box, patch, R, kids }
  }

  // —— P8 组件模板实例：{ type:'faceplate', fptId, bindings:{PV:'S001.LEVEL'} } ——
  // 实例**不存模板 json**：每次渲染都从 handlers.fpt（运行时缓存的模板表）里取最新定义，
  // 所以「改模板里液位罐的颜色 → 所有实例同时变」是自然结果，不需要同步逻辑。
  // 子对象和组合一样带 data-gpath：点它算选中整个实例（组内编辑那一套不适用于模板）。
  if (type === 'faceplate') {
    box.style.overflow = 'hidden'
    const def = handlers.fpt && handlers.fpt.get ? handlers.fpt.get(item.fptId) : null
    if (!def) {
      box.style.cssText += 'border:1px dashed #ef4444;box-sizing:border-box;'
      box.appendChild(el('div',
        'position:absolute;left:0;top:0;width:100%;height:100%;display:flex;align-items:center;'
        + 'justify-content:center;color:#ef4444;font:12px/1.4 system-ui,sans-serif;text-align:center;padding:4px;',
        '组件模板 #' + item.fptId + ' 不存在'))
      return { node: box, patch: null, R }
    }
    const ts = sizeOf(def)
    const inner = el('div', `position:absolute;left:0;top:0;width:${ts.w}px;height:${ts.h}px;`
      + `transform:scale(${w / ts.w},${h / ts.h});transform-origin:top left;`)
    box.appendChild(inner)
    const kids = []
    const kidPatches = []
    // 每次渲染都重新展开（@PV → S001.LEVEL），不缓存
    const exp = expandInstance(item, def)
    exp.forEach((c, i) => {
      const rr = renderItem(c, values, handlers, path + '.i.' + i, pending, players, paths)
      if (!rr) return
      rr.node.dataset.gpath = path
      inner.appendChild(rr.node)
      // patch 要拿「子对象自己」，不能拿实例（min/max/unit 都在子对象上）
      if (rr.patch) kidPatches.push({ fn: rr.patch, item: c })
      if (rr.R) kids.push({ item: c, node: rr.node, R: rr.R })
      if (rr.kids) for (const k of rr.kids) kids.push(k)
    })
    R.inner = inner
    R.kids = kids
    patch = (vals) => {
      for (const f of kidPatches) { try { f.fn(vals, f.item) } catch (e) { /* 单个子对象异常不影响整个实例 */ } }
    }
    applyItemStyle(box, item, R)
    return { node: box, patch, R, kids }
  }

  // —— P6 控件：真正的 Vue 组件，编辑态与只读页同一份代码，只差 env.mode ——
  if (type === 'control') {
    box.style.cssText += 'overflow:hidden;'
    // 符号库：编辑态是可拖拽的图层面板，运行态不显示
    if (item.control === 'symbolLib' && handlers.mode !== 'edit') box.style.display = 'none'
    const host = el('div', 'position:absolute;left:0;top:0;width:100%;height:100%;')
    box.appendChild(host)
    R.host = host
    if (handlers.mode === 'edit' && item.control !== 'symbolLib') {
      const tag = el('div',
        'position:absolute;left:0;top:0;z-index:5;pointer-events:none;font:10px/1.6 system-ui,sans-serif;'
        + 'color:#04121e;background:#1ec8ff;padding:0 5px;border-bottom-right-radius:3px;opacity:.92;',
        controlDef(item.control).name)
      tag.className = 'scada-ctl-tag'
      box.appendChild(tag)
      R.tag = tag
    }
    const env = handlers.ctrlEnv
    if (env) {
      // 元素必须先进入文档（视频要 isConnected、趋势要 offsetWidth），所以放 pending
      pending.push(() => mountControl(host, item, env))
      patch = (vals, it) => updateControl(host, it, env)
    } else {
      host.textContent = '（缺少控件运行环境）'
    }
    if (handlers.mode === 'edit' && handlers.onControlDblClick) {
      box.ondblclick = (e) => {
        e.stopPropagation()
        // 这里以前传的是 idx，但 idx 属于外层 items.forEach 的作用域，
        // renderItem 里只有 path（字符串下标）。裸用 idx 会抛 ReferenceError，
        // 结果就是「双击控件毫无反应、配置对话框永远打不开」。
        handlers.onControlDblClick(item)
      }
    }
    applyItemStyle(box, item, R)
    return { node: box, patch, R }
  }

  // —— P8 图片对象：真正的 <img>，图形列表换 src 才有意义（原来只画了个占位方块）——
  if (type === 'image') {
    box.style.overflow = 'hidden'
    const ph = el('div', 'position:absolute;left:0;top:0;width:100%;height:100%;display:flex;'
      + 'align-items:center;justify-content:center;color:#64748b;font:11px system-ui,sans-serif;'
      + 'border:1px dashed #334155;box-sizing:border-box;', '图片')
    const img = document.createElement('img')
    img.style.cssText = 'width:100%;height:100%;object-fit:contain;display:block;'
    img.alt = item.name || ''
    if (item.src) { img.src = item.src; ph.style.display = 'none' } else { img.style.display = 'none' }
    // 加载失败：退回占位，不留裂图（图形列表里配错地址时看得见）
    img.onerror = () => { img.style.display = 'none'; ph.style.display = 'flex' }
    img.onload = () => { if (img.getAttribute('src')) { img.style.display = ''; ph.style.display = 'none' } }
    box.appendChild(ph)
    box.appendChild(img)
    R.img = img
    R.ph = ph
    applyItemStyle(box, item, R)
    return { node: box, patch: null, R }
  }

  // 矢量图元（标准对象、工艺图元、控件占位）——静态形状，不含运行数据。
  // 用内联 svg 是为了让线/弧/多边形这些形状在 DOM 画布里也能画准；只读页同样适用。
  const vec = VECTOR[type]
  if (vec) {
    box.style.overflow = 'hidden'
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    svg.setAttribute('width', '100%')
    svg.setAttribute('height', '100%')
    svg.setAttribute('viewBox', `0 0 ${w} ${h}`)
    svg.setAttribute('preserveAspectRatio', 'none')
    svg.innerHTML = vec(w, h, item, palOf(item))   // 只含代码生成的图形，不含用户输入
    box.appendChild(svg)
    R.vec = vec
    R.svg = svg
    // —— 标准对象的数值显示层（提示词 17）——
    // line/polyline/polygon/ellipse/arc 走的是这条 VECTOR 分支（提前 return），
    // 和走 switch 的 rect/circle/text 是两条路，所以这里必须单独加一次。
    // svg 之后 append + absolute 定位，数值会盖在图形上面。
    if (STD_NUM_TYPES.indexOf(type) >= 0 && item.dyn && item.dyn.value) {
      const num = el('div',
        'position:absolute;left:0;top:0;width:100%;height:100%;display:flex;'
        + 'align-items:center;justify-content:center;pointer-events:none;'
        + 'box-sizing:border-box;padding:2px 4px;overflow:hidden;', '--')
      box.appendChild(num)
      R.num = num
    }
    // 底部文字只认 item.text（用户显式填的）；不再回退到 label（拖入时的面板名）
    if (item.text) {
      const lb = el('div', 'position:absolute;left:0;bottom:1px;width:100%;text-align:center;pointer-events:none;', item.text)
      box.appendChild(lb)
      R.label = lb
    }
    // —— 提示词 11：工艺图元动态化 ——
    // 绑了变量（或动态化接管了 running）的泵/风机/阀/格栅/输送机/管件，按值重画状态：
    //   泵/风机：runValue(默认 1)=运行  faultValue(默认 2)=故障  其余=停止
    //   阀：openValue(默认 1)=开，其余=关
    //   格栅/输送机/管件：非 0=流动/运转
    // 坏质量/超时（stale）一律停动画 —— 站点离线后整站自然冻结，不需要单独判离线。
    if (DECK_DYN.has(type) && (item.var || item.dyn)) {
      const isPump = type === 'pump_v' || type === 'pump_h' || type === 'fan'
      const isValve = type === 'valve'
      const stOf = (vals) => {
        const r = readVar(vals, item, handlers)
        const dead = r.state !== 'good'
        let st
        if (isPump) {
          const runV = numOr(item.runValue, 1), faultV = numOr(item.faultValue, 2)
          st = { run: !dead && r.val === runV, fault: !dead && r.val === faultV, stale: dead }
        } else if (isValve) {
          const openV = numOr(item.openValue, 1)
          st = { open: !dead && r.val === openV, stale: dead }
        } else {
          st = { run: !dead && !!r.val, stale: dead }
        }
        // 调试参数 ?fault=1：第一个可故障设备置故障（验收红闪态）；每次整树重建时重置
        if (DECK_DEBUG.fault && isPump && !faultHit) { faultHit = true; st = { run: false, fault: true, stale: false } }
        return st
      }
      const paint = (st) => { svg.innerHTML = vec(w, h, item, palOf(item), st) }
      paint(stOf(values))            // 首帧就带状态，别等第一轮 patch
      patch = (vals, it) => {
        if (dynOwns(box, 'running')) return
        paint(stOf(vals))
      }
      applyItemStyle(box, item, R)
      return { node: box, patch, R }
    }
    applyItemStyle(box, item, R)
    return { node: box, patch: null, R }
  }

  switch (type) {
    case 'tank': {
      const min = item.min ?? 0, max = item.max ?? 100
      box.style.cssText += 'overflow:hidden;'
      const liquid = el('div', 'position:absolute;left:0;bottom:0;width:100%;height:0%;transition:height .8s;')
      box.appendChild(liquid)
      const lb = el('div', 'position:absolute;top:4px;left:0;width:100%;text-align:center;', item.text || '')
      box.appendChild(lb)
      const vt = el('div', 'position:absolute;top:22px;left:0;width:100%;text-align:center;font-weight:600;')
      box.appendChild(vt)
      // 提示词 11：介质色（原则 3——进水浑浊、出水清澈，不许全画成一种蓝）+ 标尺
      let ruler = null
      if (item.showScale) {
        ruler = el('div', 'position:absolute;right:3px;top:8%;bottom:8%;width:2px;background:#365b78;')
        for (let i = 0; i <= 4; i++) {
          const tk = el('div', `position:absolute;left:0;top:${(100 - i * 25)}%;width:6px;height:1px;background:#365b78;`)
          ruler.appendChild(tk)
        }
        box.appendChild(ruler)
      }
      const paintLiquid = (on, pct) => {
        const m = mediumOf(item)
        const lc = item.medium ? m.color : (item.liquidColor || defaultsOf('tank').liquidColor)
        liquid.style.background = on
          ? `linear-gradient(180deg,${lc},${lc}88)`
          : 'linear-gradient(180deg,#3a4652,#2a343d)'
        liquid.style.height = (on ? pct * 100 : 0) + '%'
        liquid.style.opacity = on ? String(mediumOf(item).opacity + 0.15) : '.7'
      }
      R.liquid = liquid
      R.label = lb
      R.val = vt
      patch = (vals) => {
        // 统一三态：good 才有液位和数值；bad/stale/nodata 液位归零变灰、数值 --（不是 0）
        const r = readVar(vals, item, handlers)
        const good = r.state === 'good'
        if (!dynOwns(box, 'height')) {
          const pct = good ? Math.max(0, Math.min(1, (r.val - min) / (max - min || 1))) : 0
          paintLiquid(good, pct)
        }
        if (!dynOwns(box, 'value')) {
          vt.textContent = r.display === '--' ? '--' : (fmtNum(r.val, r, item) + (item.unit ? ' ' + item.unit : ''))
          vt.style.color = good ? '#ffffff' : '#64748b'
        }
      }
      break
    }
    case 'pump': {
      box.style.cssText += 'display:flex;flex-direction:column;align-items:center;justify-content:flex-start;'
      const circle = el('div', 'border-radius:50%;display:flex;align-items:center;justify-content:center;')
      const rotor = el('div', 'width:60%;height:60%;border-radius:50%;')
      circle.appendChild(rotor)
      box.appendChild(circle)
      const lb = el('div', 'margin-top:2px;')
      lb.textContent = label || ''
      box.appendChild(lb)
      R.circle = circle
      R.rotor = rotor
      R.label = lb
      R.running = false
      R.fault = false
      R.paint = () => {
        const d = defaultsOf('pump')
        // 三态：故障=琥珀闪（优先），运行=绿+光圈+旋转，停止=中性
        const on = R.running, fault = R.fault
        const c = fault ? TK.warning : (on ? (item.colorRun || d.colorRun) : (item.colorIdle || d.colorIdle))
        const spin = item.spin === undefined ? d.spin : !!item.spin
        circle.style.border = `3px solid ${on || fault ? c : (item.stroke || d.stroke)}`
        circle.style.background = '#132a44'
        circle.style.boxShadow = on ? `0 0 12px ${TK.success}55` : 'none'
        rotor.style.background = `conic-gradient(${c} 0 25%, transparent 0 50%, ${c} 0 75%, transparent 0)`
        rotor.style.animation = (on && spin && !fault) ? 'scada-spin 1.2s linear infinite' : 'none'
        circle.classList.toggle('scada-blink', !!fault)
      }
      patch = (vals) => {
        if (dynOwns(box, 'running')) return
        const r = readVar(vals, item, handlers)
        if (r.state !== 'good') { R.running = false; R.fault = false; R.paint(); return }
        R.running = r.val === numOr(item.runValue, 1)
        R.fault = r.val === numOr(item.faultValue, 2)
        R.paint()
      }
      break
    }
    case 'pipe': {
      R.running = false
      R.paint = () => {
        const d = defaultsOf('pipe')
        const m = mediumOf(item)
        // 介质色（原则 3）：配了 medium 就用介质色，没配沿用用户填的 fill
        const base = item.medium ? m.color : (item.fill || d.fill)
        const flow = item.flow === undefined ? d.flow : !!item.flow
        const on = R.running && flow
        box.style.background = on
          ? `repeating-linear-gradient(90deg,${base} 0 14px,${TK.pipeBase} 14px 28px)`
          : base
        box.style.backgroundSize = on ? '28px 100%' : ''
        box.style.animation = on ? 'scada-flow 1s linear infinite' : 'none'
        box.style.opacity = R.dead ? '.45' : '1'
        box.style.borderRadius = (Math.max(2, Math.min(numOr(item.h, h), 60)) / 2) + 'px'
      }
      patch = (vals) => {
        if (dynOwns(box, 'running')) return
        const r = readVar(vals, item, handlers)
        R.dead = r.state !== 'good'
        R.running = !!r.val && !R.dead
        R.paint()
      }
      break
    }
    case 'value':
    case 'input': {   // 'input' 是 P1 老画面的类型名，创建分支原先漏了它，会被当成未知类型画成图标占位
      // 修复 09：I/O 域三模式（WinCC Input/Output）
      //   output      只显示（老行为，一个 span）
      //   input       可键入，初始为空/默认值
      //   inputoutput 显示实时值，可改成新值
      // 提示词 10 4.1：预览/运行态（view / kiosk / 发布）只显示数值 + 单位——
      // 不输出标签、不渲染 <input>（DOM 里连 readonly 输入框都不留，Tab 也落不进去）。
      const preview = handlers.mode !== 'edit'
      const mode = item.mode || (type === 'input' ? 'inputoutput' : 'output')
      // 2026-11-13 用户要求：预览态也要能输入（原设计「预览只显示」已作废）。
      // 只挡两类：①viewer 只读角色 ②显式传 kiosk=true 的纯展示端。
      // 注意：/publish 页面 embedded=true 但 kiosk=false —— 用户 2026-11-14 明确要求
      // 发布页的 I/O 域必须能输入（原来 kiosk 跟着 embedded 走是我自己加的限制，已作废）。
      // canWrite 缺省视为 true —— 老调用方没传时不至于把编辑器弄坏。
      // kiosk 不再参与可写判定：用户 2026-11-14 要求 /publish 也能输入。
      // kiosk 只剩外观语义 —— 见下面 inp 的 scada-io-flat。
      const wantEdit = (mode === 'input' || mode === 'inputoutput')
      const canWrite = handlers.canWrite !== false
      const editable = wantEdit && canWrite
      box.style.cssText += 'display:flex;gap:6px;padding:0 8px;align-items:center;'
      const lb = el('span', '', item.text || '')   // 不显示面板名/变量名，要文字请用文字标签
      if (!preview) box.appendChild(lb)
      const un = el('span', 'font-size:12px;color:#64748b;', item.unit || '')
      R.label = lb
      R.unit = un

      if (!editable) {
        const num = el('span', 'font-family:Consolas,monospace;font-weight:600;')
        box.appendChild(num)
        box.appendChild(un)
        R.num = num
        patch = (vals) => {
          if (dynOwns(box, 'value')) return
          // 统一三态（提示词 11）：good 显示数值，bad/stale/nodata 一律 -- 灰（不是 0）
          const r = readVar(vals, item, handlers)
          const good = r.state === 'good'
          num.textContent = good ? fmtNum(r.val, r, item) : '--'
          num.style.color = good
            ? (item.alarmColor && r.val > (item.max ?? Infinity) ? '#f87171' : (item.color || '#e2e8f0'))
            : '#64748b'
          num.style.fontFamily = TK.numFont          // 数字等宽，防跳动
        }
        break
      }

      // —— 输入态 ——
      // 写回目标：优先动态化的 tag，其次旧格式 var（裸名由 runtime 补当前站点）
      // handlers 在结构不变时不会换新（renderScada 走 patch 分支），站点要取"当前值"而不是闭包快照
      const curSite = typeof handlers.site === 'function' ? handlers.site() : handlers.site
      const tag = ioTagOf(item, curSite)
      const numOrNull = (x) => (x === undefined || x === null || x === '' ? null : Number(x))
      const lo = numOrNull(item.inputMin), hi = numOrNull(item.inputMax)

      const inp = document.createElement('input')
      inp.type = 'text'                 // 不用 type=number：浏览器对空值/小数/滚轮行为不一致
      inp.inputMode = 'decimal'
      inp.className = 'scada-io-inp'
      // 运行态（/view 与 /publish 都是 handlers.mode==='runtime'）：输入框要长得和
      // 只读文本一模一样 —— 无边框/无底色/无内边距、靠左、宽度随内容，
      // 操作员看到的还是"一串数字"，点进去才能编辑。用户 2026-11-14 要求
      // 组态画面页面也这样做。编辑器（mode==='edit'）保持标准输入框外观，
      // 因为画布上要能看出"这块是可编辑区域"的真实排版。
      if (handlers.mode === 'runtime') {
        box.classList.add('scada-io-flat')
        // 字体四项要和只读分支的 span.num 完全同源，否则"外观不变"只是边框对了、
        // 字号/颜色/字体还是输入框的样子。只读那边是 render.js:400 的
        // applyFont(R.num, item, Math.max(10, h * 0.55), '#e2e8f0', '')
        // + patch 里的 TK.numFont。
        inp.style.fontFamily = TK.numFont
        inp.style.fontSize = Math.max(10, h * 0.55) + 'px'
        inp.style.color = item.color || '#e2e8f0'
        // 注意不能用 '600'：只读分支内联写了 font-weight:600，但 applyFont 会把它
        // 用 item.bold ? '700' : '' 清成空，实际渲染是 400。这里必须跟 applyFont 同源。
        inp.style.fontWeight = item.bold ? '700' : '400'
      }
      inp.style.flex = '1 1 auto'
      inp.style.minWidth = '0'
      inp.autocomplete = 'off'
      box.appendChild(inp)
      if (item.showUnit !== false) box.appendChild(un)
      box.style.overflow = 'visible'

      // el(tag, style, text) 第二参是内联样式，class 要单独赋
      const tip = el('div')
      tip.className = 'scada-io-tip'
      box.appendChild(tip)
      const showTip = (t) => { tip.textContent = t || ''; tip.style.display = t ? 'block' : 'none' }

      // 只读点位：rw=0 → 禁用 + 悬停提示（后端 /api/write 也会再拦一道）
      const ro = handlers.rwOf ? Number(handlers.rwOf(tag)) === 0 : false
      if (ro) {
        inp.readOnly = true
        inp.style.cursor = 'not-allowed'
        inp.title = '该点位为只读点位（rw=0），不能写入'
        box.title = inp.title
        box.dataset.ro = '1'
      }
      // 编辑态禁交互：要能看见"长什么样"，但不能在画布上打字（否则点对象就进输入框）
      const inert = handlers.mode === 'edit'
      if (inert) { inp.readOnly = true; inp.title = '编辑态：切到运行态才能输入' }

      // 带 rec（含 dtype）的取值：输入框回显要按类型决定小数位
      const readLiveRec = () => {
        // 必须优先走 readVar：它从 rt.read() 拿完整记录，带 dtype / ts / pollMs。
        // 之前优先走 handlers.readValue，那条只返回 {val}：
        //   · dtype 丢了 → fmtNum 拿不到类型，整数（uint32/int16/byte…）
        //     也按 toFixed(decimals ?? 2) 显示成 2587962.00；
        //   · ts 丢了 → boundState 里 ts=0 直接判 stale，显示 '--'。
        // readValue 只作为 readVar 取不到时的兜底。
        const r = readVar(values, item, handlers)
        if (r && r.found) return r
        if (handlers.readValue && tag) {
          const x = handlers.readValue(tag)
          return x === undefined ? null : { val: x }
        }
        return null
      }
      const readLive = () => {
        const rec = readLiveRec()
        return rec ? rec.val : null
      }
      // force=true 用于"写入失败回滚"：此刻输入框通常还是焦点状态，
      // 不能因为"正在输入"就跳过，否则操作员看到的还是那个没写成功的数字
      const renderVal = (val, force) => {
        if (!force && document.activeElement === inp) return   // 正在输入：绝不用实时值冲掉
        if (val == null) { inp.value = mode === 'input' ? (item.default ?? '') : ''; inp.placeholder = '--'; return }
        // 按类型格式化（bool/int 不带小数）：'--' 不能填进输入框
        const shown = fmtNum(val, readLiveRec(), item)
        inp.value = (shown === '--') ? '' : shown
      }
      // 「该显示什么」：仅输入模式永远是空/默认值，另两种是实时值
      const shownVal = () => (mode === 'input' ? null : readLive())
      // mode=input 是「仅输入」：只认默认值 / 用户键入，**绝不拿实时值去冲它**。
      // 否则每 250ms 一次实时刷新就把"空输入框"填成过程值，这个模式形同 inputoutput。
      patch = () => { if (mode !== 'input') renderVal(readLive()) }
      renderVal(shownVal())

      // 用户 2026-11 要求：I/O 域不再原地输入，改为弹窗输入。
      // 弹窗里只有数字和小数点（+退格），可鼠标点也可键盘打，带「确认」「取消」：
      //   确认 → 校验 → 写入 → 关闭；取消 → 不写入直接关闭。
      // 原地输入彻底关掉（readOnly），避免和弹窗两套入口并存。
      inp.readOnly = true
      inp.style.cursor = (inert || ro) ? 'not-allowed' : 'pointer'
      inp.addEventListener('click', () => {
        if (inert || ro) return
        // 不再原地输入了，聚焦只会让输入框留一圈聚焦框（弹窗打开后背后那个虚线框很难看）
        inp.blur()
        // 表达式解不出单个点位（如 @CurrentSite + '.LEVEL' * 2）就不猜写回目标
        if (!tag) {
          inp.classList.add('bad')
          showTip('该对象没有可写回的点位（算术表达式不支持写回）')
          return
        }
        if (!handlers.onWrite) { showTip('没有写回通道'); return }
        openNumericPad({
          title: (item.name || item.code || '输入') + ' → ' + tag,
          unit: item.unit || '',
          initial: shownVal(),
          min: lo,
          max: hi,
          decimals: Number.isFinite(Number(item.decimals)) ? Number(item.decimals) : 6,
          confirmBeforeWrite: !!item.confirmWrite,
          onSubmit: async (n) => {
            await handlers.onWrite(tag, n)
            inp.classList.add('ok')
            setTimeout(() => inp.classList.remove('ok'), 700)
            showTip('')
          },
        })
      })
      break
    }
    case 'text': {
      const tx = el('div', '', item.text || '')
      box.appendChild(tx)
      R.txt = tx
      break
    }
    case 'lamp': {
      box.style.cssText += 'display:flex;flex-direction:column;align-items:center;'
      const dot = el('div', 'border-radius:50%;')
      box.appendChild(dot)
      const lb = el('div', 'margin-top:2px;')
      lb.textContent = label || ''
      box.appendChild(lb)
      R.dot = dot
      R.label = lb
      R.running = false
      R.paint = () => {
        const d = defaultsOf('lamp')
        const on = R.running
        const c = on ? (item.colorRun || d.colorRun) : (item.colorIdle || d.colorIdle)
        dot.style.background = c
        dot.style.border = `2px solid ${item.stroke || '#1e3a5f'}`
        dot.style.boxShadow = on ? `0 0 12px ${c}` : 'none'
      }
      patch = (vals) => {
        if (dynOwns(box, 'running')) return
        // 统一三态：bad/stale/nodata 一律灰点（不亮、不闪），good 才按 onValue 判亮
        const r = readVar(vals, item, handlers)
        if (r.state !== 'good') {
          dot.style.background = TK.offline
          dot.style.boxShadow = 'none'
          dot.style.border = '2px solid #1e3a5f'
          return
        }
        R.running = r.val === numOr(item.onValue, 1) || (item.onValue === undefined && !!r.val)
        R.paint()
      }
      break
    }
    // ================= 提示词 11：scada-deck 风格大屏组件 =================
    case 'kpi': {
      // KPI 卡（ids-kpi）：左侧色条 + 标签 + 大号数值（tabular-nums 等宽防跳动）
      box.style.cssText += `overflow:hidden;background:linear-gradient(145deg,${TK.surface3},${TK.surface1});
        border:1px solid ${TK.line};border-radius:8px;padding:10px 14px;
        box-shadow:inset 0 1px rgba(255,255,255,.03),0 12px 30px rgba(0,0,0,.18);
        display:flex;flex-direction:column;justify-content:center;gap:4px;box-sizing:border-box;`
      const bar = el('div', `position:absolute;left:0;top:0;bottom:0;width:3px;background:${TK.accent};`)
      const lb = el('div', `font-size:12px;color:${TK.text2};`)
      lb.textContent = item.text || ''
      const row = el('div', 'display:flex;align-items:baseline;gap:4px;')
      const num = el('div', `font-weight:700;font-size:${Math.max(18, Math.round(h * 0.34))}px;
        font-family:${TK.numFont};font-variant-numeric:tabular-nums;color:${TK.text1};line-height:1;`)
      num.textContent = '--'
      const un = el('div', `font-size:12px;color:${TK.text3};`)
      un.textContent = item.unit || ''
      row.appendChild(num); row.appendChild(un)
      const sub = el('div', `font-size:11px;color:${TK.text3};`)
      box.appendChild(bar); box.appendChild(lb); box.appendChild(row); box.appendChild(sub)
      R.rebuild = () => {
        lb.textContent = item.text || ''
        un.textContent = item.unit || ''
        bar.style.background = item.accentColor || TK.accent
        num.style.fontSize = Math.max(18, Math.round(h * 0.34)) + 'px'
        sub.textContent = ''
      }
      R.rebuild()
      R.kpiNum = num
      R.kpiBar = bar
      patch = (vals) => {
        if (dynOwns(box, 'value')) return
        const r = readVar(vals, item, handlers)
        const good = r.state === 'good'
        num.textContent = good ? fmtNum(r.val, r, item) : '--'
        num.style.color = good ? (item.color || TK.text1) : '#64748b'
        // 左侧色条兼作质量点（原则 4）：绿/琥珀/灰，不给颜色第二含义
        bar.style.background = good ? (item.accentColor || TK.accent) : r.dot
      }
      break
    }
    case 'progress': {
      // 进度条：底槽 + 填充 + 数值（scada-deck metric 风格）
      const min = item.min ?? 0, max = item.max ?? 100
      box.style.cssText += 'display:flex;flex-direction:column;justify-content:center;gap:4px;box-sizing:border-box;padding:2px 4px;'
      const lb = el('div', `font-size:11px;color:${TK.text2};display:flex;justify-content:space-between;`)
      const ltxt = el('span', '', item.text || '')
      const num = el('span', `font-weight:700;font-size:13px;font-family:${TK.numFont};
        font-variant-numeric:tabular-nums;color:${TK.text1};`, '--')
      lb.appendChild(ltxt); lb.appendChild(num)
      const track = el('div', `position:relative;height:8px;background:${TK.surface3};border-radius:4px;overflow:hidden;
        border:1px solid ${TK.line};`)
      const fill = el('div', `position:absolute;left:0;top:0;bottom:0;width:0%;background:${TK.accent};
        border-radius:4px;transition:width .3s;`)
      track.appendChild(fill)
      box.appendChild(lb); box.appendChild(track)
      R.rebuild = () => { ltxt.textContent = item.text || '' }
      R.rebuild()
      R.progFill = fill
      R.progNum = num
      patch = (vals) => {
        if (dynOwns(box, 'value')) return
        const r = readVar(vals, item, handlers)
        const good = r.state === 'good'
        const pct = good ? Math.max(0, Math.min(1, (r.val - min) / (max - min || 1))) : 0
        fill.style.width = (pct * 100) + '%'
        fill.style.background = good ? (item.accentColor || TK.accent) : TK.offline
        num.textContent = good ? fmtNum(r.val, r, item) + (item.unit ? ' ' + item.unit : '') : '--'
        num.style.color = good ? TK.text1 : '#64748b'
      }
      break
    }
    case 'ring': {
      // 环形进度：SVG 圆环 + 中心数值
      const min = item.min ?? 0, max = item.max ?? 100
      box.style.cssText += 'overflow:hidden;'
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
      svg.setAttribute('width', '100%'); svg.setAttribute('height', '100%')
      svg.setAttribute('viewBox', '0 0 100 100')
      const cen = el('div', `position:absolute;left:0;top:0;width:100%;height:100%;display:flex;flex-direction:column;
        align-items:center;justify-content:center;pointer-events:none;`)
      const num = el('div', `font-weight:700;font-size:${Math.max(14, Math.round(h * 0.22))}px;
        font-family:${TK.numFont};font-variant-numeric:tabular-nums;color:${TK.text1};line-height:1;`, '--')
      const un = el('div', `font-size:10px;color:${TK.text3};margin-top:2px;`, item.unit || '')
      cen.appendChild(num); cen.appendChild(un)
      const paint = (pct, dead) => {
        const r = 42, cx = 50, cy = 50
        const circ = 2 * Math.PI * r
        svg.innerHTML = `
          <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${TK.surface3}" stroke-width="9"/>
          <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${dead ? TK.offline : (item.accentColor || TK.accent)}"
            stroke-width="9" stroke-linecap="round" stroke-dasharray="${circ}"
            stroke-dashoffset="${circ * (1 - pct)}" transform="rotate(-90 ${cx} ${cy})"
            style="transition:stroke-dashoffset .3s"/>`
      }
      paint(0, true)
      box.appendChild(svg); box.appendChild(cen)
      R.ringSvg = svg
      R.rebuild = () => { un.textContent = item.unit || ''; num.style.fontSize = Math.max(14, Math.round(h * 0.22)) + 'px' }
      R.rebuild()
      R.ringNum = num
      patch = (vals) => {
        if (dynOwns(box, 'value')) return
        const r = readVar(vals, item, handlers)
        const good = r.state === 'good'
        paint(good ? Math.max(0, Math.min(1, (r.val - min) / (max - min || 1))) : 0, !good)
        num.textContent = good ? fmtNum(r.val, r, item) : '--'
        num.style.color = good ? TK.text1 : '#64748b'
      }
      break
    }
    case 'statusbadge': {
      // 状态徽章（ids-status + leg-item）：8px 色点 + 文字；三态色固定语义，文本可配
      box.style.cssText += `display:flex;align-items:center;gap:8px;padding:0 12px;box-sizing:border-box;
        background:rgba(10,23,34,.85);border:1px solid ${TK.line};border-radius:6px;`
      const dot = el('div', `width:8px;height:8px;border-radius:50%;background:${TK.offline};flex:0 0 8px;`)
      const name = el('div', `font-size:12px;color:${TK.text2};`)
      name.textContent = item.text || ''
      const stx = el('div', `margin-left:8px;color:${TK.text1};font-weight:600;font-size:12px;`, '--')
      box.appendChild(dot); box.appendChild(name); box.appendChild(stx)
      R.rebuild = () => { name.textContent = item.text || '' }
      R.rebuild()
      R.badgeDot = dot
      R.badgeTx = stx
      patch = (vals) => {
        const r = readVar(vals, item, handlers)
        dot.style.background = r.dot
        dot.style.boxShadow = r.state === 'good' ? `0 0 8px ${r.dot}` : 'none'
        stx.textContent = r.state === 'good'
          ? (item.goodText || (fmtNum(r.val, r, item) + (item.unit || '')))
          : (item.badText || '--')
      }
      break
    }
    case 'panel': {
      // 面板卡（ids-panel）：低对比边框 + 圆角 + 轻内高光，禁止霓虹外发光（§2.1）
      box.style.cssText += `overflow:hidden;box-sizing:border-box;
        border:1px solid ${TK.line};border-radius:8px;
        background:linear-gradient(145deg,${TK.surface2},${TK.surface1});
        box-shadow:inset 0 1px rgba(255,255,255,.03),0 12px 30px rgba(0,0,0,.18);`
      const hd = el('div', `height:26px;display:flex;align-items:center;padding:0 10px;box-sizing:border-box;
        border-bottom:1px solid ${TK.line};font-size:12px;font-weight:700;color:${TK.text2};letter-spacing:.5px;`)
      hd.textContent = item.text || ''
      box.appendChild(hd)
      R.rebuild = () => { hd.textContent = item.text || '' }
      R.rebuild()
      break
    }
    case 'button': {
      const btn = el('button', 'width:100%;height:100%;border:none;cursor:pointer;')
      // 文字优先取 item.text（属性面板「字体」页签写的是 text），
      // label 是历史字段，v 是点位值，最后兜底「下发」
      btn.textContent = item.text || label || v || '下发'
      // 悬停用 filter 而不是改 background：否则会把属性面板设的填充色冲掉
      btn.onmouseenter = () => { btn.style.filter = 'brightness(1.15)' }
      btn.onmouseleave = () => { btn.style.filter = '' }
      // 配了事件的对象由事件系统接管（P5）；没配事件的老板画面仍走 var 通道
      btn.onclick = () => {
        // 14 号：配了「跳转画面」就只跳转，不再走写 PLC / 事件（二者互斥，跳转优先）
        if (item.targetPage) {
          handlers.onNavigate && handlers.onNavigate(item.targetPage)
          return
        }
        const evs = item.events || {}
        if (Object.keys(evs).some(k => evs[k] && evs[k].action)) return
        handlers.onWrite && handlers.onWrite(v, item.value ?? 1)
      }
      box.appendChild(btn)
      R.btn = btn
      break
    }
    case 'video': {
      const vid = el('video', 'width:100%;height:100%;background:#000;object-fit:contain;')
      vid.muted = true
      vid.autoplay = true
      vid.setAttribute('playsinline', '')
      box.appendChild(vid)
      const lb = el('div', 'position:absolute;top:4px;left:8px;z-index:2;pointer-events:none;', item.text || '')
      box.appendChild(lb)
      R.vid = vid
      R.label = lb
      const holder = { player: null, src: null }
      players.push(holder)

      const attach = (src) => {
        if (!src) { holder.src = null; return }
        if (holder.src === src) return
        holder.src = src
        import('flv.js').then(({ default: flvjs }) => {
          if (!flvjs.isSupported()) return
          // 期间画布可能已被重建或卸载，节点不在文档里就不要再建流
          if (!vid.isConnected) return
          if (holder.player) { try { holder.player.destroy() } catch (e) {} }
          const p = flvjs.createPlayer(
            { type: 'flv', url: src, isLive: true, hasAudio: false },
            { enableStashBuffer: false, stashInitialSize: 128, autoCleanupSourceBuffer: true, lazyLoad: false }
          )
          holder.player = p
          p.attachMediaElement(vid)
          // 03 整改：token 5 分钟过期，断流时让页面重签一次（5 秒节流，避免刷接口）
          p.on(flvjs.Events.ERROR, (type) => {
            if (type !== 'NetworkError' || !handlers.onVideoError) return
            const t = Date.now()
            if (holder.lastErr && t - holder.lastErr < 5000) return
            holder.lastErr = t
            handlers.onVideoError(item.stream || '')
          })
          p.load()
          const pr = vid.play()
          if (pr && pr.catch) pr.catch(() => {})
        }).catch(() => {})
      }

      // 元素进入文档后再挂流
      pending.push(() => attach(item.src))
      patch = (vals, it) => { if (it && it.src !== holder.src) attach(it.src) }
      break
    }
    case 'alarm_list': {
      box.style.cssText += 'overflow:hidden;padding:6px;'
      const ti = el('div', 'margin-bottom:4px;', label || '实时报警')
      box.appendChild(ti)
      const list = el('div', 'overflow:hidden;height:calc(100% - 24px);')
      box.appendChild(list)
      R.title = ti
      let lastKey = null
      patch = (vals, it) => {
        const alarms = (it && it.alarms) || []
        const shown = alarms.slice(0, 6)
        const key = shown.join('\u0001')
        if (key === lastKey) return
        lastKey = key
        list.innerHTML = ''
        if (!shown.length) {
          list.appendChild(el('div', 'color:#475569;font-size:12px;', '当前无报警'))
        } else {
          shown.forEach(a => list.appendChild(el('div', 'color:#f87171;font-size:12px;line-height:22px;', a)))
        }
      }
      break
    }
    case 'rect': {
      // 填充/边框/圆角全部由 applyStyle 按属性表来，这里只保留默认外观
      box.style.overflow = 'hidden'
      break
    }
    case 'circle': {
      box.style.borderRadius = '50%'
      break
    }
    default: {
      box.appendChild(el('div', 'color:#f59e0b;font-size:12px;', `未知组件: ${type}`))
    }
  }
  applyItemStyle(box, item, R)

  // —— 标准对象的数值显示层（提示词 17）——
  // 矩形/圆/椭圆/多边形/线/折线/圆弧/文本 原来只能把变量映射成颜色，看不到具体数值；
  // 智能对象（液位罐/I/O 域）早就有 R.num 了，这里给标准对象补齐。
  //
  // 只需要把节点建出来：dyn.js 的 case 'value' 会写 R.num（那是全组态统一的动态化入口），
  // 自己再写一遍 patch 会和它抢，反而互相覆盖。
  //
  // 约束：没配「显示数值」就不建节点，老画面外观完全不变。
  if (STD_NUM_TYPES.indexOf(type) >= 0 && item.dyn && item.dyn.value) {
    const num = el('div',
      'position:absolute;left:0;top:0;width:100%;height:100%;display:flex;'
      + 'align-items:center;justify-content:center;pointer-events:none;'
      + 'box-sizing:border-box;padding:2px 4px;overflow:hidden;', '--')
    box.appendChild(num)
    R.num = num
    // 文本对象：数值优先于静态文字（和 I/O 域"数值优先"的既有约定一致）
    if (type === 'text' && R.txt) R.txt.style.display = 'none'
  }

  return { node: box, patch, R }
}

const STD_NUM_TYPES = ['rect', 'circle', 'ellipse', 'polygon', 'polyline', 'arc', 'line', 'text']

// 动画 keyframes（编辑器和只读页都要注入一次）
export function ensureScadaStyles() {
  if (document.getElementById('scada-styles')) return
  const st = document.createElement('style')
  st.id = 'scada-styles'
  st.textContent = `
@keyframes scada-spin { from { transform: rotate(0deg);} to { transform: rotate(360deg);} }
@keyframes scada-flow { from { background-position-x: 0;} to { background-position-x: 28px;} }
@keyframes scada-blink { 0%,100% { opacity: 1;} 50% { opacity: .35;} }
.scada-blink { animation: scada-blink .8s ease-in-out infinite; }
/* 动态化绑定失败：属性保持上一次的值，只把对象标黄，绝不显示 0 */
.scada-dyn-bad { outline: 1px dashed #f59e0b !important; outline-offset: 1px; }
/* 事件动作要写的点位 rw=0：按钮禁用，悬停提示「只读点位」 */
.scada-ro { opacity: .55; cursor: not-allowed !important; }
.scada-ro::after {
  content: '只读'; position: absolute; right: 2px; top: 1px; font-size: 9px;
  color: #f59e0b; background: rgba(12,26,43,.85); border-radius: 2px; padding: 0 3px;
  pointer-events: none;
}
/* I/O 域输入态（修复 09）：等宽 + 右对齐 + 比普通 value 深一点的底 */
.scada-io-inp {
  font-family: Consolas, monospace; font-weight: 600; text-align: right;
  background: rgba(0, 0, 0, .28); color: #e2e8f0; border: 1px solid #24405c;
  border-radius: 3px; padding: 0 5px; height: 78%; outline: none; transition: border-color .15s;
}
.scada-io-inp:focus { border-color: #1ec8ff; box-shadow: 0 0 0 1px rgba(30, 200, 255, .35); }
.scada-io-inp.bad { border-color: #ef4444 !important; box-shadow: 0 0 0 1px rgba(239, 68, 68, .35); }
.scada-io-inp.ok { border-color: #22c55e !important; background: rgba(34, 197, 94, .16); }
.scada-io-inp.busy { opacity: .6; }
/* 发布端的 I/O 域：外观与只读文本一致（无边框/无底色/无内边距，靠左，
   宽度随内容），但仍然可编辑。field-sizing:content 让 input 像 span 一样宽。 */
.scada-io-flat .scada-io-inp {
  background: transparent !important; border: none !important;
  border-radius: 0 !important; padding: 0 !important;
  text-align: start !important;   /* 基础类写的是 right，只读 span 是 start */
  flex: 0 0 auto !important;
  height: auto !important; box-shadow: none !important;
  field-sizing: content; min-width: 3ch;
}
.scada-io-flat .scada-io-inp.bad { background: transparent !important; border: none !important; color: #f87171 !important; }
.scada-io-flat .scada-io-inp.ok  { background: transparent !important; border: none !important; }
/* 运行态 I/O 域改成点击弹窗输入，不再原地编辑：
   聚焦无意义，去掉虚线框；只靠 cursor:pointer 提示可点。 */
.scada-io-flat .scada-io-inp:focus { box-shadow: none !important; outline: none !important; }
.scada-io-tip {
  display: none; position: absolute; left: 0; top: 100%; margin-top: 2px; z-index: 9;
  font-size: 11px; color: #f87171; background: rgba(12, 26, 43, .95);
  border: 1px solid #7f1d1d; border-radius: 3px; padding: 1px 5px; white-space: nowrap;
}
/* 事件探测命中态：运行态下让操作员看得出这块能点 */
.scada-live { cursor: pointer; }
/* ================= 提示词 11：scada-deck 动效（§2.1：管道 1.8~3.2s 循环、竖轴件横向投影） ================= */
@keyframes sd-spin-kf { to { transform: rotate(360deg); } }
@keyframes sd-dash-h { to { stroke-dashoffset: -64; } }
@keyframes sd-dash-v { to { stroke-dashoffset: -64; } }
@keyframes sd-rake-kf { 0%,100% { transform: translateY(0); } 50% { transform: translateY(26%); } }
@keyframes sd-screw-kf { to { transform: translateX(16px); } }
/* 旋转件：transform-box 让 SVG 内 g 以自身几何中心转（不然绕画布原点飞） */
.sd-rot { animation: sd-spin-kf 1.2s linear infinite; transform-box: fill-box; transform-origin: center; }
/* 管道流光：dashoffset 无限滚动（垂直/T 形/弯头各有方向，速度照 scada-deck 1.8~3.2s 档取 2s） */
.sd-flowline-h { animation: sd-dash-h 2s linear infinite; }
.sd-flowline-v { animation: sd-dash-v 2s linear infinite; }
.sd-flowline-elbow { animation: sd-dash-h 2.4s linear infinite; }
/* 格栅耙齿往复（横向投影模拟，不做平面 360° 旋转） */
.sd-rake { animation: sd-rake-kf 2.6s ease-in-out infinite; }
/* 螺旋输送：纹路横移（配合槽体两端的旋转端盖） */
.sd-screw { animation: sd-screw-kf 1.8s linear infinite; }
/* ?fx=0 / 系统减少动效：所有动画全停（§2.1 规则 + 可访问性） */
.sd-no-fx .sd-rot, .sd-no-fx .sd-flowline-h, .sd-no-fx .sd-flowline-v, .sd-no-fx .sd-flowline-elbow,
.sd-no-fx .sd-rake, .sd-no-fx .sd-screw, .sd-no-fx .scada-blink { animation: none !important; }
@media (prefers-reduced-motion: reduce) {
  .sd-rot, .sd-flowline-h, .sd-flowline-v, .sd-flowline-elbow, .sd-rake, .sd-screw, .scada-blink { animation: none !important; }
}
`
  document.head.appendChild(st)
}
