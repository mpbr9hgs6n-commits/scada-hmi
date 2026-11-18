// 组态画布交互层（P2）：选中 / 拖拽 / 缩放对象 / 框选 / 键盘 / 视图缩放 / 命令式撤销
//
// 三条硬约定（照 02_P2 任务书）：
// 1) 鼠标坐标一律 getBoundingClientRect 反算 —— 禁止 offsetX/offsetY，禁止假设 scale=1。
//    缩放过一次用 offsetX 就会偏，这是本阶段第一陷阱。
// 2) 拖动过程只改 DOM style，不碰响应式数据；松手才写回 json 并入撤销栈。
// 3) 选中框与控制点画在「未缩放」的容器坐标系（wrap）里，所以控制点恒为 7px，
//    不随画布 transform:scale 变形。控制点用百分比定位在选中框四角/四边中点。

export const GRID_SIZE = 20
const HANDLE_SIZE = 7
const MIN_SIZE = 10
const MAX_HISTORY = 100

// P7：对齐/分布/组合/参考线
import {
  alignRects, distributeRects, bboxOf, makeGroup, flattenGroup,
  groupDepth, MAX_GROUP_DEPTH
} from './arrange'
import { computeGuides } from './guides'

const DIRS = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']
const CURSORS = {
  nw: 'nwse-resize', n: 'ns-resize', ne: 'nesw-resize', e: 'ew-resize',
  se: 'nwse-resize', s: 'ns-resize', sw: 'nesw-resize', w: 'ew-resize'
}
const POS = {
  nw: [0, 0], n: [50, 0], ne: [100, 0], e: [100, 50],
  se: [100, 100], s: [50, 100], sw: [0, 100], w: [0, 50]
}

// 管道类约束（任务书三）：水平管道只能改宽、垂直管道只能改高、T 形管/弯头尺寸锁死
const RESIZE_AXIS = { pipe: 'x', pipe_v: 'y', pipe_t: 'none', pipe_elbow: 'none' }

const clone = (o) => JSON.parse(JSON.stringify(o))

// 对齐/分布模式的提示语
const ALIGN_CN = {
  l: '左对齐', r: '右对齐', hc: '水平居中', t: '顶对齐', b: '底对齐', vc: '垂直居中',
  eqw: '等宽', eqh: '等高',
  'canvas-l': '贴左边', 'canvas-r': '贴右边', 'canvas-hc': '水平居中',
  'canvas-t': '贴上边', 'canvas-b': '贴下边', 'canvas-vc': '垂直居中'
}

// —— 撤销栈：存「命令 + 差异」，不存整份 json 快照 ——
// 200 个对象时快照式撤销会把内存吃光，所以每条命令只记受影响对象的 from/to。
export class History {
  constructor(limit = MAX_HISTORY) {
    this.limit = Math.max(50, limit)
    this.undoStack = []
    this.redoStack = []
  }
  get canUndo() { return this.undoStack.length > 0 }
  get canRedo() { return this.redoStack.length > 0 }
  push(cmd) {
    this.undoStack.push(cmd)
    if (this.undoStack.length > this.limit) this.undoStack.shift()
    this.redoStack.length = 0      // 新操作后重做链失效（与 WinCC 一致）
  }
  undo() {
    const c = this.undoStack.pop()
    if (!c) return false
    c.apply('from')
    this.redoStack.push(c)
    return true
  }
  redo() {
    const c = this.redoStack.pop()
    if (!c) return false
    c.apply('to')
    this.undoStack.push(c)
    return true
  }
  clear() { this.undoStack.length = 0; this.redoStack.length = 0 }
}

export function cmdMove(entries) {
  return {
    type: 'move',
    apply(k) {
      for (const e of entries) { e.item.x = e[k].x; e.item.y = e[k].y }
    }
  }
}

export function cmdResize(entries) {
  return {
    type: 'resize',
    apply(k) {
      for (const e of entries) {
        const s = e[k]
        e.item.x = s.x; e.item.y = s.y; e.item.w = s.w; e.item.h = s.h
      }
    }
  }
}

// 新增/粘贴：index 记为插入时在数组里的位置，撤销时按引用删除，重做时按 index 插回
export function cmdAdd(items, entries) {
  return {
    type: 'add',
    apply(k) {
      if (k === 'to') {
        for (const e of entries.slice().sort((a, b) => a.index - b.index)) {
          items.splice(Math.min(e.index, items.length), 0, e.item)
        }
      } else {
        for (const e of entries) {
          const i = items.indexOf(e.item)
          if (i >= 0) items.splice(i, 1)
        }
      }
    }
  }
}

export function cmdDelete(items, entries) {
  return {
    type: 'delete',
    apply(k) {
      if (k === 'to') {
        for (const e of entries.slice().sort((a, b) => b.index - a.index)) {
          const i = items.indexOf(e.item)
          if (i >= 0) items.splice(i, 1)
        }
      } else {
        for (const e of entries.slice().sort((a, b) => a.index - b.index)) {
          items.splice(Math.min(e.index, items.length), 0, e.item)
        }
      }
    }
  }
}

// 属性修改：一条命令记一批 {item,key,from,to}，撤销时整批回退
export function cmdProps(entries) {
  return {
    type: 'props',
    apply(k) {
      for (const e of entries) e.item[e.key] = e[k]
    }
  }
}

// 组合缩放（P7）：组框与子对象要一起回到同一状态，不能只撤组框
function cmdGroupResize(g, before, after) {
  return {
    type: 'gresize',
    apply(k) {
      const s = k === 'to' ? after : before
      g.x = s.g.x; g.y = s.g.y; g.w = s.g.w; g.h = s.g.h
      ;(g.items || []).forEach((c, i) => {
        const t = s.kids[i]
        if (t) { c.x = t.x; c.y = t.y; c.w = t.w; c.h = t.h }
      })
    }
  }
}

// 整表重排（P7）：图层排序/组合/解组会改动 items 数组本身。
// before/after 存的是「对象引用数组」，不是深拷贝 —— 撤销栈里放引用既省内存又不会丢对象身份。
export function cmdArray(items, before, after) {
  return {
    type: 'array',
    apply(k) {
      const src = k === 'to' ? after : before
      items.length = 0
      for (const it of src) items.push(it)
    }
  }
}

export class CanvasInteract {
  constructor(o) {
    this.wrap = o.wrap
    this.getStage = o.getStage
    this.getItems = o.getItems
    this.getSize = o.getSize
    this.gridOn = o.gridOn || (() => false)
    this.isLocked = o.isLocked || (() => false)
    this.onDirty = o.onDirty || (() => {})
    this.onSelection = o.onSelection || (() => {})
    this.onRebuild = o.onRebuild || (() => {})
    this.onZoom = o.onZoom || (() => {})
    this.onHistory = o.onHistory || (() => {})
    this.onMessage = o.onMessage || (() => {})
    this.onReadout = o.onReadout || (() => {})
    this.onRestyle = o.onRestyle || (() => {})
    this.onPropsChanged = o.onPropsChanged || null
    this.onLayers = o.onLayers || (() => {})      // P7：图层/组合变化后通知左栏刷新
    this.onEditGroup = o.onEditGroup || (() => {}) // P7：进出组时通知编辑器（画提示条）

    this.history = new History(MAX_HISTORY)
    this.sel = []
    this.handles = []
    this.zoom = 1
    this.effScale = 1
    this.baseScale = 1
    this.placing = false
    this.drag = null
    this.marquee = null
    this.rafId = 0
    this.pendingEvt = null
    this.clipboard = []
    this._minis = []
    // P7
    this.parent = new Map()      // 子对象 → 所属组（absOf 用它换算绝对坐标）
    this.editPath = null         // 正在组内编辑时 = 该组的路径（"3"）
    this.editGroupItem = null
    this.alignBase = 'last'      // 'last' 最后选中的对象 / 'bbox' 最外层包围盒
    this.guideEls = []
    this._bindFns()
  }

  _bindFns() {
    this._dbl = this._onDbl.bind(this)
    this._down = this._onDown.bind(this)
    this._move = this._onMove.bind(this)
    this._up = this._onUp.bind(this)
    this._key = this._onKey.bind(this)
    this._wheel = this._onWheel.bind(this)
    this._frame = this._frame.bind(this)
  }

  attach() {
    this._buildOverlay()
    this.wrap.addEventListener('mousedown', this._down)
    this.wrap.addEventListener('dblclick', this._dbl)
    window.addEventListener('mousemove', this._move)
    window.addEventListener('mouseup', this._up)
    window.addEventListener('keydown', this._key)
    this.wrap.addEventListener('wheel', this._wheel, { passive: false })
  }

  detach() {
    if (!this.wrap) return
    this.wrap.removeEventListener('mousedown', this._down)
    this.wrap.removeEventListener('dblclick', this._dbl)
    window.removeEventListener('mousemove', this._move)
    window.removeEventListener('mouseup', this._up)
    window.removeEventListener('keydown', this._key)
    this.wrap.removeEventListener('wheel', this._wheel)
    if (this.rafId) { cancelAnimationFrame(this.rafId); this.rafId = 0 }
    if (this._loopId) { cancelAnimationFrame(this._loopId); this._loopId = 0 }
    if (this.overlay && this.overlay.parentNode) this.overlay.parentNode.removeChild(this.overlay)
    if (this.marqueeEl && this.marqueeEl.parentNode) this.marqueeEl.parentNode.removeChild(this.marqueeEl)
    document.body.style.userSelect = ''
  }

  // —— 覆盖层 ——
  _buildOverlay() {
    const ov = document.createElement('div')
    ov.className = 'scada-overlay'
    ov.style.cssText = 'position:absolute;left:0;top:0;right:0;bottom:0;pointer-events:none;z-index:7;overflow:hidden;'
    this.overlay = ov

    const box = document.createElement('div')
    box.className = 'sel-box'
    box.style.cssText = `position:absolute;display:none;box-sizing:border-box;pointer-events:none;
      border:1px solid #1ec8ff;box-shadow:0 0 0 1px rgba(30,200,255,.25);`
    ov.appendChild(box)
    this.boxEl = box

    for (const d of DIRS) {
      const h = document.createElement('div')
      h.className = 'resize-handle'
      h.dataset.dir = d
      h.style.cssText = `position:absolute;display:none;width:${HANDLE_SIZE}px;height:${HANDLE_SIZE}px;
        margin:0;padding:0;background:#ffffff;border:1px solid #1ec8ff;box-sizing:border-box;
        pointer-events:auto;cursor:${CURSORS[d]};left:${POS[d][0]}%;top:${POS[d][1]}%;
        transform:translate(-50%,-50%);`
      box.appendChild(h)
      this.handles.push(h)
    }
    this.wrap.appendChild(ov)
  }

  // —— 坐标换算（唯一入口）——
  // rect.width 就是「画面宽 × 实际缩放」，所以 rect.width / W 就是当前 scale，
  // 视图缩放、浏览器缩放、三栏拖宽都自动适配，不需要另外记录 scale。
  coord(e) {
    const st = this.getStage()
    if (!st) return null
    const rect = st.getBoundingClientRect()
    const W = this.getSize().W || 1600
    const scale = rect.width / W
    if (!scale) return null
    return {
      x: (e.clientX - rect.left) / scale,
      y: (e.clientY - rect.top) / scale,
      scale,
      rect
    }
  }

  // —— 路径与坐标（P7：组合内对象用相对坐标，这里统一换算）——
  // 路径形如 "3"（顶层第 4 个）或 "3.i.0"（第 4 个组的第 1 个子对象）
  _scada() {
    const st = this.getStage()
    return st && st.parentNode ? st.parentNode.__scada : null
  }

  pathOf(item) {
    const sc = this._scada()
    return sc && sc.paths ? sc.paths.get(item) : null
  }

  nodeOf(item) {
    const p = this.pathOf(item)
    const st = this.getStage()
    if (p == null || !st) return null
    return st.querySelector(`[data-idx="${p}"]`)
  }

  // 路径形如 "3" / "3.i.0" / "3.i.1.i.0"（i 只是分隔符，不参与取下标）
  itemAt(path) {
    const segs = String(path || '').split('.')
    let arr = this.getItems()
    let cur = null
    for (const s of segs) {
      if (s === 'i') continue
      cur = arr && arr[Number(s)]
      arr = cur && Array.isArray(cur.items) ? cur.items : null
    }
    return cur || null
  }

  // 子对象 → 父组 的索引（每次布局/拖动前刷新，避免画布重建后指向旧对象）
  _reindex() {
    this.parent = new Map()
    const walk = (arr, p) => {
      for (const it of arr || []) {
        if (p) this.parent.set(it, p)
        if (it.type === 'group' && Array.isArray(it.items)) walk(it.items, it)
      }
    }
    walk(this.getItems(), null)
  }

  // 绝对坐标：组合内子对象存的是相对组的坐标
  absOf(it) {
    const p = this.parent.get(it)
    return {
      x: (p ? p.x : 0) + (Number(it.x) || 0),
      y: (p ? p.y : 0) + (Number(it.y) || 0),
      w: Number(it.w) || 1,
      h: Number(it.h) || 1
    }
  }

  // 绝对坐标 → 写回 item 的本地坐标
  localOf(it, ax, ay) {
    const p = this.parent.get(it)
    return { x: Math.round(ax - (p ? p.x : 0)), y: Math.round(ay - (p ? p.y : 0)) }
  }

  absRect(it) { const a = this.absOf(it); return { item: it, ...a } }

  // 命中的节点属于哪个对象：默认选最外层的组，正在组内编辑时才允许选子对象
  _resolveNode(node) {
    let n = node
    while (n && n.dataset && n.dataset.gpath && n.dataset.gpath !== this.editPath) {
      const up = this.getStage().querySelector(`[data-idx="${n.dataset.gpath}"]`)
      if (!up) break
      n = up
    }
    return n
  }

  setSel(arr) {
    const seen = []
    for (const it of arr) if (it && !seen.includes(it)) seen.push(it)
    this.sel = seen
    this.onSelection(seen.slice())
    this.layoutSelection()
  }

  clearSel() { this.setSel([]) }

  // —— 选中框 + 控制点定位 ——
  layoutSelection() {
    if (!this.overlay) return
    const st = this.getStage()
    if (!st) { if (this.boxEl) this.boxEl.style.display = 'none'; return }
    const wrapR = this.wrap.getBoundingClientRect()
    const sr = st.getBoundingClientRect()
    const W = this.getSize().W || 1600
    const s = sr.width / W
    const ox = sr.left - wrapR.left
    const oy = sr.top - wrapR.top
    this._s = s; this._ox = ox; this._oy = oy

    this._reindex()
    const items = this.getItems()
    // 选中项可以是顶层对象，也可以是「正在组内编辑」的子对象
    this.sel = this.sel.filter(it => items.includes(it) || this.parent.has(it))
    if (!this.sel.length) {
      this.boxEl.style.display = 'none'
      this._clearMinis()
      return
    }
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
    for (const it of this.sel) {
      const a = this.absOf(it)
      x0 = Math.min(x0, a.x); y0 = Math.min(y0, a.y)
      x1 = Math.max(x1, a.x + a.w); y1 = Math.max(y1, a.y + a.h)
    }
    const b = this.boxEl
    b.style.display = 'block'
    b.style.left = (ox + x0 * s) + 'px'
    b.style.top = (oy + y0 * s) + 'px'
    b.style.width = Math.max(1, (x1 - x0) * s) + 'px'
    b.style.height = Math.max(1, (y1 - y0) * s) + 'px'
    const single = this.sel.length === 1
    b.classList.toggle('multi', !single)
    for (const h of this.handles) h.style.display = single ? 'block' : 'none'
    if (single) this._clearMinis()
    else this._drawMinis(ox, oy, s)
  }

  _drawMinis(ox, oy, s) {
    while (this._minis.length < this.sel.length) {
      const d = document.createElement('div')
      d.className = 'sel-mini'
      d.style.cssText = 'position:absolute;border:1px dashed rgba(30,200,255,.75);box-sizing:border-box;pointer-events:none;'
      this.overlay.appendChild(d)
      this._minis.push(d)
    }
    this._minis.forEach((d, i) => {
      const it = this.sel[i]
      if (!it) { d.style.display = 'none'; return }
      const a = this.absOf(it)
      d.style.display = 'block'
      d.style.left = (ox + a.x * s) + 'px'
      d.style.top = (oy + a.y * s) + 'px'
      d.style.width = Math.max(1, a.w * s) + 'px'
      d.style.height = Math.max(1, a.h * s) + 'px'
    })
  }

  _clearMinis() {
    for (const d of this._minis) d.style.display = 'none'
  }

  // —— 鼠标按下 ——
  _onDown(e) {
    if (e.button !== 0) return
    if (!this.getStage()) return
    if (this.placing) return            // 落位模式：交给编辑器的 click 处理
    if (this.isLocked()) { this.onMessage('画面已锁定，先解锁再编辑'); return }

    const t = e.target
    const hEl = t && t.closest ? t.closest('.resize-handle') : null
    if (hEl) { e.preventDefault(); e.stopPropagation(); this._startResize(e, hEl.dataset.dir); return }

    let node = t && t.closest ? t.closest('[data-idx]') : null
    if (node) {
      node = this._resolveNode(node)          // 组内子对象默认归到最外层的组
      const it = this.itemAt(node.dataset.idx)
      if (it && it.locked) { this.onMessage('对象已锁定，先在「图层」里解锁'); return }
      e.preventDefault()
      this._startDrag(e, node)
      return
    }

    this._startMarquee(e)
  }

  // 双击：组合 → 进入组内编辑（像 WinCC 那样）；已经在组内时不重复进
  _onDbl(e) {
    if (!this.getStage() || this.placing) return
    let node = e.target && e.target.closest ? e.target.closest('[data-idx]') : null
    if (!node) return
    node = this._resolveNode(node)
    const it = this.itemAt(node.dataset.idx)
    if (!it) return
    if (it.type === 'group') { this.enterGroup(it); return }
    // 已经是「组内子对象」且当前就在编辑这个组：交给编辑器（控件双击开配置）
  }

  _startDrag(e, node) {
    this._reindex()
    const item = this.itemAt(node.dataset.idx)
    if (!item) return

    if (e.shiftKey) {
      if (this.sel.includes(item)) { this.setSel(this.sel.filter(x => x !== item)); return }
      this.setSel([...this.sel, item])
    } else if (!this.sel.includes(item)) {
      this.setSel([item])
    }

    const c = this.coord(e)
    if (!c) return
    // 拖动一律在「绝对坐标」里算；子对象写回时减掉组原点（off）
    this.drag = {
      kind: 'move',
      sx: c.x, sy: c.y,
      sxScreen: e.clientX, syScreen: e.clientY,
      started: false,
      entries: this.sel.map(it => {
        const a = this.absOf(it)
        const p = this.parent.get(it)
        return {
          item: it,
          w: a.w, h: a.h,
          off: { x: p ? p.x : 0, y: p ? p.y : 0 },
          from: { x: a.x, y: a.y },
          to: { x: a.x, y: a.y },
          node: this.nodeOf(it)
        }
      }),
      t0: performance.now(), frames: 0, work: 0, maxWork: 0, lastFrame: performance.now()
    }
    this._beginInteract()
  }

  _startResize(e, dir) {
    const it = this.sel[0]
    if (!it) return
    const axis = RESIZE_AXIS[it.type] || 'free'
    if (axis === 'none') { this.onMessage('该图元尺寸固定，只能整体移动'); return }
    const c = this.coord(e)
    if (!c) return
    this.drag = {
      kind: 'resize',
      dir,
      item: it,
      node: this.nodeOf(it),
      sx: c.x, sy: c.y,
      sxScreen: e.clientX, syScreen: e.clientY,
      started: false,
      from: { x: it.x, y: it.y, w: it.w ?? 100, h: it.h ?? 40 },
      to: { x: it.x, y: it.y, w: it.w ?? 100, h: it.h ?? 40 },
      t0: performance.now(), frames: 0, work: 0, maxWork: 0, lastFrame: performance.now()
    }
    this._beginInteract()
  }

  _beginInteract() {
    this.wrap.classList.add('dragging')
    document.body.style.userSelect = 'none'
    // 拖拽期间跑常驻 rAF 循环（不是「来一个 mousemove 才请求一帧」）：
    // 这样帧间隔反映的是真实的渲染节奏，掉帧会被如实记下来，测出来的才是帧时间。
    this._loopLast = 0
    this._loopId = requestAnimationFrame(this._frame)
  }

  _startMarquee(e) {
    const c = this.coord(e)
    if (!c) return
    const base = e.shiftKey ? [...this.sel] : []
    if (!e.shiftKey) this.setSel([])
    this.marquee = { sx: c.x, sy: c.y, rect: null, base }

    if (!this.marqueeEl) {
      const d = document.createElement('div')
      d.className = 'scada-marquee'
      d.style.cssText = 'position:absolute;display:none;border:1px solid #1ec8ff;background:rgba(30,200,255,.10);pointer-events:none;z-index:8;'
      this.wrap.appendChild(d)
      this.marqueeEl = d
    }
    this.marqueeEl.style.display = 'block'
    this.marqueeEl.style.width = '0px'
    this.marqueeEl.style.height = '0px'
  }

  // —— 鼠标移动：只登记最新事件，真正的计算落在 rAF 帧里 ——
  _onMove(e) {
    if (this.drag) { this.pendingEvt = e; return }
    if (this.marquee) this._updateMarquee(e)
  }

  _frame(t) {
    const d = this.drag
    if (!d) { this._loopId = 0; return }
    this._loopId = requestAnimationFrame(this._frame)

    // 帧间隔统计（含掉帧）
    if (!this._loopLast) this._loopLast = t
    const gap = t - this._loopLast
    this._loopLast = t
    d.gapSum = (d.gapSum || 0) + gap
    d.gapN = (d.gapN || 0) + 1

    const e = this.pendingEvt
    if (!e) return
    this.pendingEvt = null
    this._applyEvent(d, e)
  }

  _applyEvent(d, e) {
    const c = this.coord(e)
    if (!c) return
    const dx = c.x - d.sx
    const dy = c.y - d.sy
    if (!d.started) {
      if (Math.abs(e.clientX - d.sxScreen) < 2 && Math.abs(e.clientY - d.syScreen) < 2) return
      d.started = true
    }

    const t0 = performance.now()
    if (d.kind === 'move') this._applyMove(d, dx, dy, e.altKey)
    else this._applyResize(d, dx, dy, e.shiftKey, e.altKey)
    this.layoutSelection()          // 选中框与控制点跟随
    const w = performance.now() - t0
    d.frames++
    d.work += w
    if (w > d.maxWork) d.maxWork = w
  }

  _applyMove(d, dx, dy, alt) {
    const { W, H } = this.getSize()
    const snap = this.gridOn() && !alt
    // 第一遍：网格吸附 + 贴边（绝对坐标）
    const base = []
    for (const en of d.entries) {
      let nx = en.from.x + dx
      let ny = en.from.y + dy
      if (snap) {
        nx = Math.round(nx / GRID_SIZE) * GRID_SIZE
        ny = Math.round(ny / GRID_SIZE) * GRID_SIZE
      } else {
        nx = Math.round(nx); ny = Math.round(ny)
      }
      nx = Math.max(0, Math.min((W || 1600) - en.w, nx))
      ny = Math.max(0, Math.min((H || 900) - en.h, ny))
      base.push({ en, x: nx, y: ny })
    }

    // 第二遍：参考线吸附（±5px）。按住 Alt 临时关闭，画小图标时不被黏住
    let gdx = 0, gdy = 0
    if (!alt) {
      const bb = bboxOf(base.map(b => ({ x: b.x, y: b.y, w: b.en.w, h: b.en.h })))
      const g = computeGuides(bb, this._guidePool())
      gdx = g.dx; gdy = g.dy
      this._drawGuides(g.guides)
    } else {
      this._clearGuides()
    }

    let readout = ''
    for (const b of base) {
      const en = b.en
      let nx = b.x + gdx
      let ny = b.y + gdy
      nx = Math.max(0, Math.min((W || 1600) - en.w, nx))
      ny = Math.max(0, Math.min((H || 900) - en.h, ny))
      en.to.x = Math.round(nx); en.to.y = Math.round(ny)
      if (en.node) {
        // 组内子对象写的是相对坐标（绝对 - 组原点）
        en.node.style.left = (en.to.x - en.off.x) + 'px'
        en.node.style.top = (en.to.y - en.off.y) + 'px'
      }
      if (!readout) readout = 'x ' + en.to.x + ' , y ' + en.to.y
    }
    this.onReadout(readout)
  }

  // 参考线的比对对象：同层的、没隐藏的、不在当前选中里的
  _guidePool() {
    const arr = this.editGroupItem ? (this.editGroupItem.items || []) : this.getItems()
    const out = []
    for (const it of arr) {
      if (it.hidden || this.sel.includes(it)) continue
      out.push(this.absRect(it))
    }
    return out
  }

  _drawGuides(guides) {
    if (!this.overlay) return
    const s = this._s || 1, ox = this._ox || 0, oy = this._oy || 0
    if (!this.guideEls.length) {
      for (let i = 0; i < 6; i++) {
        const line = document.createElement('div')
        line.className = 'guide-line'
        line.style.cssText = 'position:absolute;background:#ff3b30;pointer-events:none;z-index:9;display:none;'
        const lab = document.createElement('div')
        lab.className = 'guide-label'
        lab.style.cssText = 'position:absolute;color:#ff3b30;background:rgba(11,22,34,.9);'
          + 'font:10px/1.5 Consolas,monospace;padding:0 3px;border-radius:2px;pointer-events:none;z-index:10;display:none;'
        this.overlay.appendChild(line)
        this.overlay.appendChild(lab)
        this.guideEls.push({ line, lab })
      }
    }
    guides.forEach((g, i) => {
      const slot = this.guideEls[i]
      if (!slot) return
      const { line, lab } = slot
      line.style.display = 'block'
      if (g.dir === 'v') {
        line.style.left = (ox + g.pos * s) + 'px'
        line.style.top = (oy + g.from * s) + 'px'
        line.style.width = '1px'
        line.style.height = Math.max(1, (g.to - g.from) * s) + 'px'
      } else {
        line.style.top = (oy + g.pos * s) + 'px'
        line.style.left = (ox + g.from * s) + 'px'
        line.style.height = '1px'
        line.style.width = Math.max(1, (g.to - g.from) * s) + 'px'
      }
      if (g.label) {
        lab.style.display = 'block'
        lab.textContent = g.label
        const midX = g.dir === 'v' ? ox + g.pos * s + 4 : ox + (g.from + g.to) / 2 * s
        const midY = g.dir === 'v' ? oy + (g.from + g.to) / 2 * s : oy + g.pos * s - 14
        lab.style.left = midX + 'px'
        lab.style.top = midY + 'px'
      } else {
        lab.style.display = 'none'
      }
    })
    for (let i = guides.length; i < this.guideEls.length; i++) {
      this.guideEls[i].line.style.display = 'none'
      this.guideEls[i].lab.style.display = 'none'
    }
  }

  _clearGuides() {
    for (const g of this.guideEls) { g.line.style.display = 'none'; g.lab.style.display = 'none' }
  }

  _applyResize(d, dx, dy, shift, alt) {
    const { W, H } = this.getSize()
    const f = d.from
    const axis = RESIZE_AXIS[d.item.type] || 'free'
    const canW = axis !== 'y'
    const canH = axis !== 'x'
    const dir = d.dir
    const useW = dir.includes('w'), useE = dir.includes('e')
    const useN = dir.includes('n'), useS = dir.includes('s')

    let x = f.x, y = f.y, w = f.w, h = f.h
    const changeW = canW && (useW || useE)
    const changeH = canH && (useN || useS)
    if (!changeW && !changeH) return

    if (changeW) {
      w = useE ? f.w + dx : f.w - dx
      x = useE ? f.x : f.x + dx
    }
    if (changeH) {
      h = useS ? f.h + dy : f.h - dy
      y = useS ? f.y : f.y + dy
    }

    // Shift 锁比例：按变化更大的那一维回算另一维
    if (shift && changeW && changeH && f.w > 0 && f.h > 0) {
      const ratio = f.w / f.h
      if (Math.abs(w - f.w) >= Math.abs(h - f.h)) {
        const nh = Math.round(w / ratio)
        if (useN) y = f.y + f.h - nh
        h = nh
      } else {
        const nw = Math.round(h * ratio)
        if (useW) x = f.x + f.w - nw
        w = nw
      }
    }

    // 最小 10px，且不允许负值（往回拉过头时按边界钉住）
    if (w < MIN_SIZE) { if (useW) x = f.x + f.w - MIN_SIZE; w = MIN_SIZE }
    if (h < MIN_SIZE) { if (useN) y = f.y + f.h - MIN_SIZE; h = MIN_SIZE }
    x = Math.max(0, Math.round(x)); y = Math.max(0, Math.round(y))
    w = Math.round(w); h = Math.round(h)
    if (x + w > (W || 1600)) w = (W || 1600) - x
    if (y + h > (H || 900)) h = (H || 900) - y
    if (w < MIN_SIZE) { w = MIN_SIZE; x = Math.max(0, (W || 1600) - MIN_SIZE) }
    if (h < MIN_SIZE) { h = MIN_SIZE; y = Math.max(0, (H || 900) - MIN_SIZE) }

    d.to = { x, y, w, h }
    if (d.node) {
      d.node.style.left = x + 'px'
      d.node.style.top = y + 'px'
      d.node.style.width = w + 'px'
      d.node.style.height = h + 'px'
    }
    // 组合：子对象按比例跟着缩，否则拖大组框里面纹丝不动
    if (d.item.type === 'group' && Array.isArray(d.item.items) && d.node) {
      const sx = w / (f.w || 1), sy = h / (f.h || 1)
      const inner = d.node.firstElementChild
      if (inner) {
        Array.from(inner.children).forEach((cn, i) => {
          const c = d.item.items[i]
          if (!c) return
          cn.style.left = ((Number(c.x) || 0) * sx) + 'px'
          cn.style.top = ((Number(c.y) || 0) * sy) + 'px'
          cn.style.width = Math.max(1, (Number(c.w) || 1) * sx) + 'px'
          cn.style.height = Math.max(1, (Number(c.h) || 1) * sy) + 'px'
        })
      }
    }
    this.onReadout(`${w} × ${h}  @ ${x}, ${y}`)
  }

  _updateMarquee(e) {
    const c = this.coord(e)
    const st = this.getStage()
    if (!c || !st || !this.marquee) return
    const wrapR = this.wrap.getBoundingClientRect()
    const sr = st.getBoundingClientRect()
    const s = sr.width / (this.getSize().W || 1600)
    const ox = sr.left - wrapR.left
    const oy = sr.top - wrapR.top
    const x1 = Math.min(this.marquee.sx, c.x), x2 = Math.max(this.marquee.sx, c.x)
    const y1 = Math.min(this.marquee.sy, c.y), y2 = Math.max(this.marquee.sy, c.y)
    this.marquee.rect = { x1, y1, x2, y2 }
    this.marqueeEl.style.left = (ox + x1 * s) + 'px'
    this.marqueeEl.style.top = (oy + y1 * s) + 'px'
    this.marqueeEl.style.width = Math.max(1, (x2 - x1) * s) + 'px'
    this.marqueeEl.style.height = Math.max(1, (y2 - y1) * s) + 'px'
  }

  // —— 鼠标松开：这一刻才写回数据 + 入撤销栈 ——
  _onUp(e) {
    if (this._loopId) { cancelAnimationFrame(this._loopId); this._loopId = 0 }
    this.rafId = 0
    const d = this.drag
    // 松手前把还没算的最后一个坐标补上，避免落点差一帧
    if (d && this.pendingEvt) {
      try { this._applyEvent(d, this.pendingEvt) } catch (err) { /* 收尾失败不影响提交 */ }
    }
    this.pendingEvt = null

    if (d) {
      this.drag = null
      this.wrap.classList.remove('dragging')
      document.body.style.userSelect = ''
      this.onReadout('')

      if (d.started) {
        this._clearGuides()
        if (d.kind === 'move') {
          // 提交时才换算回本地坐标：组原点在这次拖动里没变，from/to 同时减去它即可
          const entries = d.entries
            .filter(en => en.from.x !== en.to.x || en.from.y !== en.to.y)
            .map(en => ({
              item: en.item,
              from: { x: en.from.x - en.off.x, y: en.from.y - en.off.y },
              to: { x: en.to.x - en.off.x, y: en.to.y - en.off.y }
            }))
          if (entries.length) {
            for (const en of entries) { en.item.x = en.to.x; en.item.y = en.to.y }
            this.history.push(cmdMove(entries))
            this.onDirty()
            this.onHistory()
          }
          window.__scadaDragPerf = this._perf(d)
          this.layoutSelection()
        } else {
          const changed = ['x', 'y', 'w', 'h'].some(k => d.from[k] !== d.to[k])
          if (changed) {
            const isGrp = d.item.type === 'group' && Array.isArray(d.item.items)
            if (isGrp) {
              const snap = (from, to) => ({
                g: { ...to },
                kids: d.item.items.map(c => ({ x: c.x, y: c.y, w: c.w, h: c.h }))
              })
              const before = snap(null, d.from)
              Object.assign(d.item, d.to)
              const sx = d.to.w / (d.from.w || 1), sy = d.to.h / (d.from.h || 1)
              for (const c of d.item.items) {
                c.x = Math.round((Number(c.x) || 0) * sx)
                c.y = Math.round((Number(c.y) || 0) * sy)
                c.w = Math.max(1, Math.round((Number(c.w) || 1) * sx))
                c.h = Math.max(1, Math.round((Number(c.h) || 1) * sy))
              }
              this.history.push(cmdGroupResize(d.item, before, snap(null, d.to)))
            } else {
              const entry = { item: d.item, from: { ...d.from }, to: { ...d.to } }
              Object.assign(d.item, d.to)
              this.history.push(cmdResize([entry]))
            }
            this.onDirty()
            this.onHistory()
            this.onRebuild()        // 矢量图元按新尺寸重画，避免拉伸变形
            return
          }
          window.__scadaDragPerf = this._perf(d)
          this.layoutSelection()
        }
      } else {
        this.layoutSelection()
      }
    }

    if (this.marquee) {
      const r = this.marquee.rect
      const base = this.marquee.base
      this.marquee = null
      if (this.marqueeEl) this.marqueeEl.style.display = 'none'
      if (r) {
        // P7：隐藏与锁定的对象不参与框选（锁定的仍可见，但选不中）
        const hit = this.getItems()
          .filter(it => !it.hidden && !it.locked)
          .map(it => this.absRect(it))
          .filter(a => !(a.x + a.w < r.x1 || a.x > r.x2 || a.y + a.h < r.y1 || a.y > r.y2))
          .map(a => a.item)
        this.setSel(base.concat(hit))
      }
    }
  }

  _perf(d) {
    const ms = performance.now() - d.t0
    const frames = d.frames || 0
    const avgApply = frames ? d.work / frames : 0
    const avgGap = d.gapN ? d.gapSum / d.gapN : 0
    const r2 = (v) => Math.round(v * 100) / 100
    return {
      objects: this.getItems().length,
      frames,
      ms: Math.round(ms),
      avgFrameMs: r2(avgGap),          // 相邻帧间隔（贴合屏幕刷新率说明没掉帧）
      avgApplyMs: r2(avgApply),        // 每帧真正花在坐标计算 + 写 style 上的时间
      maxApplyMs: r2(d.maxWork)
    }
  }

  // —— 键盘 ——
  _onKey(e) {
    const t = e.target
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
    const key = (e.key || '').toLowerCase()
    const ctrl = e.ctrlKey || e.metaKey

    if (ctrl && key === 's') return                   // 保存由编辑器接管
    if (ctrl && key === 'z') { e.preventDefault(); e.shiftKey ? this.redo() : this.undo(); return }
    if (ctrl && key === 'y') { e.preventDefault(); this.redo(); return }
    if (ctrl && key === 'a') { e.preventDefault(); this.setSel(this.getItems().slice()); return }
    if (ctrl && key === 'c') {
      if (!this.sel.length) return
      e.preventDefault()
      this.clipboard = this.sel.map(clone)
      this.onMessage(`已复制 ${this.clipboard.length} 个对象`)
      return
    }
    // P7：以下几条都带 shift，必须排在单键判断之前
    if (ctrl && e.shiftKey && key === 'v') { e.preventDefault(); this.paste(0); return }
    if (ctrl && e.shiftKey && key === 'g') { e.preventDefault(); this.ungroup(); return }
    if (ctrl && e.shiftKey && ['l', 'r', 't', 'b'].includes(key)) {
      e.preventDefault()
      this.align(this.sel.length > 1 ? key : 'canvas-' + key)
      return
    }
    if (ctrl && key === 'g') { e.preventDefault(); this.group(); return }
    if (ctrl && (key === ']' || key === '}')) { e.preventDefault(); this.zOrder('up'); return }
    if (ctrl && (key === '[' || key === '{')) { e.preventDefault(); this.zOrder('down'); return }
    if (ctrl && key === 'v') { e.preventDefault(); this.paste(GRID_SIZE); return }
    if (ctrl && key === 'd') { e.preventDefault(); this.duplicate(); return }

    if (key === 'delete' || key === 'backspace') {
      if (!this.sel.length) return
      e.preventDefault()
      this.deleteSel()
      return
    }
    if (key === 'escape') {
      if (this.editPath) { this.exitGroup(); return }
      this.clearSel()
      return
    }

    const step = e.shiftKey ? 10 : 1
    const nudge = { arrowleft: [-step, 0], arrowright: [step, 0], arrowup: [0, -step], arrowdown: [0, step] }[key]
    if (nudge) {
      if (!this.sel.length) return
      e.preventDefault()
      this.nudge(nudge[0], nudge[1])
    }
  }

  _onWheel(e) {
    if (!e.ctrlKey) return
    e.preventDefault()
    const step = e.deltaY < 0 ? 1.2 : 1 / 1.2
    this.setZoom(this.zoom * step)
  }

  // —— 对外动作 ——
  setZoom(z) {
    const base = this.baseScale || 1
    this.zoom = Math.max(0.1, Math.min(8, z))
    this.onZoom(this.zoom, base)
    this.layoutSelection()
  }

  // 以「实际像素比例」设置缩放：pct=50 表示画面按 50% 显示
  setScalePct(pct) {
    const base = this.baseScale || 1
    this.setZoom((pct / 100) / base)
  }

  fitWindow() { this.setZoom(1) }

  undo() { if (!this.history.undo()) return false; this._afterHistory(); return true }

  redo() { if (!this.history.redo()) return false; this._afterHistory(); return true }

  _afterHistory() {
    const items = this.getItems()
    this.sel = this.sel.filter(it => items.includes(it))
    this.onSelection(this.sel.slice())
    this.onDirty()
    this.onHistory()
    this.onRebuild()
  }

  nudge(dx, dy) {
    const { W, H } = this.getSize()
    this._reindex()
    const entries = this.sel.map(it => {
      const a = this.absOf(it)
      const p = this.parent.get(it)
      const off = { x: p ? p.x : 0, y: p ? p.y : 0 }
      return {
        item: it,
        off,
        from: { x: a.x, y: a.y },
        to: {
          x: Math.max(0, Math.min((W || 1600) - a.w, a.x + dx)),
          y: Math.max(0, Math.min((H || 900) - a.h, a.y + dy))
        },
        node: this.nodeOf(it)
      }
    })
    for (const en of entries) {
      en.item.x = en.to.x - en.off.x; en.item.y = en.to.y - en.off.y
      if (en.node) { en.node.style.left = en.item.x + 'px'; en.node.style.top = en.item.y + 'px' }
    }
    this.history.push(cmdMove(entries.map(en => ({
      item: en.item,
      from: { x: en.from.x - en.off.x, y: en.from.y - en.off.y },
      to: { x: en.to.x - en.off.x, y: en.to.y - en.off.y }
    }))))
    this.onDirty()
    this.onHistory()
    this.layoutSelection()
  }

  deleteSel() {
    if (!this.sel.length) return 0
    const items = this.getItems()
    const entries = this.sel
      .map(it => ({ item: it, index: items.indexOf(it) }))
      .filter(x => x.index >= 0)
      .sort((a, b) => a.index - b.index)
    if (!entries.length) return 0
    for (const e of entries.slice().sort((a, b) => b.index - a.index)) items.splice(e.index, 1)
    this.history.push(cmdDelete(items, entries))
    this.setSel([])
    this.onDirty()
    this.onHistory()
    this.onRebuild()
    return entries.length
  }

  paste(offset = GRID_SIZE) {
    if (!this.clipboard.length) return 0
    const { W, H } = this.getSize()
    const items = this.getItems()
    const made = []
    for (const src of this.clipboard) {
      const it = clone(src)
      const w = it.w ?? 100, h = it.h ?? 40
      it.x = Math.max(0, Math.min((W || 1600) - w, (it.x || 0) + offset))
      it.y = Math.max(0, Math.min((H || 900) - h, (it.y || 0) + offset))
      made.push({ item: it, index: items.length })
      items.push(it)
    }
    this.history.push(cmdAdd(items, made))
    this.setSel(made.map(m => m.item))
    this.onDirty()
    this.onHistory()
    this.onRebuild()
    return made.length
  }

  // Ctrl+D：复制「当前选中」，位置不变（原地复制）。
  // 不能复用 paste()——paste 取的是剪贴板内容，Ctrl+D 不经过剪贴板。
  duplicate() {
    if (!this.sel.length) return 0
    const { W, H } = this.getSize()
    const items = this.getItems()
    const made = []
    for (const src of this.sel) {
      const it = clone(src)
      const w = it.w ?? 100, h = it.h ?? 40
      it.x = Math.max(0, Math.min((W || 1600) - w, it.x || 0))
      it.y = Math.max(0, Math.min((H || 900) - h, it.y || 0))
      made.push({ item: it, index: items.length })
      items.push(it)
    }
    this.history.push(cmdAdd(items, made))
    this.setSel(made.map(m => m.item))
    this.onDirty()
    this.onHistory()
    this.onRebuild()
    return made.length
  }

  add(list) {
    if (!list || !list.length) return
    const items = this.getItems()
    const entries = []
    for (const it of list) {
      items.push(it)
      entries.push({ item: it, index: items.length - 1 })
    }
    this.history.push(cmdAdd(items, entries))
    this.setSel(list)
    this.onDirty()
    this.onHistory()
    this.onRebuild()
  }

  // —— P7 对齐 / 分布 ——
  // 单选：相对画布（canvas-l/r/t/b/hc/vc）；多选：相对基准（l/r/t/b/hc/vc/eqw/eqh）
  // 基准默认「最后选中的对象」；alignBase='bbox' 时用最外层包围盒
  align(mode) {
    const rects = this.sel.map(it => this.absRect(it))
    if (!rects.length) { this.onMessage('先选中对象再对齐'); return 0 }
    let base = null
    if (rects.length > 1) base = this.alignBase === 'bbox' ? bboxOf(rects) : rects[rects.length - 1]
    const { W, H } = this.getSize()
    const list = alignRects(rects, mode, { base, page: { W: W || 1600, H: H || 900 } })
    const n = this._applyGeom(list)
    if (n) this.onMessage(`已${ALIGN_CN[mode] || '对齐'}（${rects.length} 个对象，基准：${base && this.alignBase === 'bbox' ? '包围盒' : (rects.length > 1 ? '最后选中' : '画布')}）`)
    else this.onMessage('已经对齐，无需调整')
    return n
  }

  distribute(axis) {
    const rects = this.sel.map(it => this.absRect(it))
    if (rects.length < 3) { this.onMessage('等距分布至少要选 3 个对象'); return 0 }
    const list = distributeRects(rects, axis)
    const n = this._applyGeom(list)
    this.onMessage(n ? `已${axis === 'y' ? '垂直' : '水平'}等距（${rects.length} 个对象）` : '间距已经相等')
    return n
  }

  // 把「绝对坐标的目标值」写回对象（组合内自动转相对坐标），一次进撤销栈
  _applyGeom(list) {
    this._reindex()
    const entries = []
    for (const g of list) {
      const p = this.parent.get(g.item)
      const off = { x: p ? p.x : 0, y: p ? p.y : 0 }
      const cur = this.absOf(g.item)
      const want = {
        x: g.x === undefined ? Number(g.item.x) || 0 : Math.round(g.x) - off.x,
        y: g.y === undefined ? Number(g.item.y) || 0 : Math.round(g.y) - off.y,
        w: g.w === undefined ? cur.w : Math.round(g.w),
        h: g.h === undefined ? cur.h : Math.round(g.h)
      }
      const now = { x: Number(g.item.x) || 0, y: Number(g.item.y) || 0, w: cur.w, h: cur.h }
      for (const k of ['x', 'y', 'w', 'h']) {
        if (want[k] !== now[k]) entries.push({ item: g.item, key: k, from: now[k], to: want[k] })
      }
    }
    if (!entries.length) return 0
    for (const e of entries) e.item[e.key] = e.to
    this.history.push(cmdProps(entries))
    this.onDirty()
    this.onHistory()
    this.onRestyle()
    this.layoutSelection()
    this.onSelection(this.sel.slice())
    return entries.length
  }

  // —— P7 图层层级 ——
  _commitArray(before) {
    this.history.push(cmdArray(this.getItems(), before, this.getItems().slice()))
    this.onDirty()
    this.onHistory()
    this.onRebuild()
    this.onLayers()
  }

  // kind: front / back / up / down（up=上移一层=往数组后面走，后画的在上）
  zOrder(kind) {
    const items = this.getItems()
    const sel = this.sel.filter(it => items.includes(it))
    if (!sel.length) return 0
    const before = items.slice()
    if (kind === 'front' || kind === 'back') {
      const keep = items.filter(it => !sel.includes(it))
      const moved = items.filter(it => sel.includes(it))
      items.length = 0
      for (const it of (kind === 'front' ? keep.concat(moved) : moved.concat(keep))) items.push(it)
    } else {
      const step = kind === 'up' ? 1 : -1
      const order = sel
        .map(it => items.indexOf(it))
        .sort((a, b) => (kind === 'up' ? b - a : a - b))
      for (const k of order) {
        const to = k + step
        if (to < 0 || to >= items.length) continue
        if (sel.includes(items[to])) continue          // 相邻两个都选中时不互换
        const t = items[k]; items[k] = items[to]; items[to] = t
      }
    }
    this._commitArray(before)
    return sel.length
  }

  // 图层列表拖拽排序：直接改 items 数组顺序（items 顺序就是 z-index）
  reorderByIndex(from, to) {
    const items = this.getItems()
    if (from === to || from < 0 || to < 0 || from >= items.length || to >= items.length) return false
    const before = items.slice()
    const [it] = items.splice(from, 1)
    items.splice(to, 0, it)
    this._commitArray(before)
    return true
  }

  // —— P7 组合 ——
  group() {
    const items = this.getItems()
    const sel = this.sel.filter(it => items.includes(it))
    if (sel.length < 2) { this.onMessage('至少选中 2 个对象才能组合'); return false }
    const depth = 1 + Math.max(...sel.map(groupDepth))
    if (depth > MAX_GROUP_DEPTH) { this.onMessage(`组合最多嵌套 ${MAX_GROUP_DEPTH} 层（官方限制）`); return false }
    const before = items.slice()
    const g = makeGroup(sel, this._groupName(items))
    const maxIdx = Math.max(...sel.map(it => items.indexOf(it)))
    const rest = items.filter(it => !sel.includes(it))
    let pos = 0
    for (let i = 0; i < maxIdx; i++) if (!sel.includes(items[i])) pos++
    rest.splice(pos, 0, g)
    items.length = 0
    for (const it of rest) items.push(it)
    this.sel = [g]
    this._commitArray(before)
    this.onSelection([g])
    this.layoutSelection()
    this.onMessage(`已组合 ${sel.length} 个对象`)
    return true
  }

  ungroup() {
    const items = this.getItems()
    const sel = this.sel.filter(it => it.type === 'group' && items.includes(it))
    if (!sel.length) { this.onMessage('没有选中的组合'); return false }
    const before = items.slice()
    const out = []
    for (const it of items) {
      if (sel.includes(it)) out.push(...flattenGroup(it))
      else out.push(it)
    }
    items.length = 0
    for (const it of out) items.push(it)
    this.sel = []
    this._commitArray(before)
    this.onSelection([])
    this.layoutSelection()
    this.onMessage(`已取消 ${sel.length} 个组合`)
    return true
  }

  _groupName(items) {
    const used = new Set()
    const walk = (arr) => { for (const it of arr || []) { if (it.name) used.add(it.name); if (it.items) walk(it.items) } }
    walk(items)
    for (let i = 1; i < 999; i++) if (!used.has('组合' + i)) return '组合' + i
    return '组合'
  }

  // 双击进组：之后点击组内子对象才是选它，外面仍然是选整个组
  enterGroup(item) {
    const p = this.pathOf(item)
    if (p == null) return false
    this.editGroupItem = item
    this.editPath = p
    this.sel = []
    this.onSelection([])
    this.layoutSelection()
    this.onEditGroup(item, p)
    this.onMessage('已进入组内编辑：可单独选中子对象，Esc 退出')
    return true
  }

  exitGroup() {
    if (!this.editPath) return false
    const g = this.editGroupItem
    this.editPath = null
    this.editGroupItem = null
    this.sel = g ? [g] : []
    this.onSelection(this.sel.slice())
    this.layoutSelection()
    this.onEditGroup(null, null)
    return true
  }

  // 可见性 / 锁定（图层上的眼睛与锁）
  setFlag(item, key, val) {
    if (!item || (key !== 'hidden' && key !== 'locked')) return false
    const from = !!item[key]
    const to = !!val
    if (from === to) return false
    item[key] = to
    this.history.push(cmdProps([{ item, key, from, to }]))
    if (key === 'locked' && to) this.setSel(this.sel.filter(x => x !== item))
    this.onDirty()
    this.onHistory()
    this.onRebuild()
    this.onLayers()
    return true
  }

  markSaved() { /* 保留接口：保存成功后不清撤销栈，与 WinCC 一致 */ }

  // —— 属性面板（P3）——
  // 拖动数值字段时的实时预览：只改数据 + 就地改样式，不入撤销栈、不置脏
  previewProps(changes) {
    if (!changes || !changes.length) return
    for (const c of changes) c.item[c.key] = c.to
    this.onRestyle()
    this.layoutSelection()
  }

  // 一次字段编辑（输入完成 / 拖动松手 / 选色）：入撤销栈，可 Ctrl+Z 撤回
  applyProps(changes) {
    if (!changes || !changes.length) return
    const real = changes.filter(c => JSON.stringify(c.from) !== JSON.stringify(c.to))
    if (!real.length) return
    for (const c of real) c.item[c.key] = c.to
    this.history.push(cmdProps(real))
    this.onDirty()
    this.onHistory()
    // P5：属性真变了 → 上层发 object.change / <attr>.change
    if (this.onPropsChanged) {
      try { this.onPropsChanged(real) } catch (e) { /* 事件回调异常不影响属性提交 */ }
    }
    this.onRestyle()
    this.layoutSelection()
    // 让面板拿到提交后的真实值（多选时各对象 from 不同，需要重算）
    this.onSelection(this.sel.slice())
  }
}
