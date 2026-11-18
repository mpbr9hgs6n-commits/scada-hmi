// 组态运行时（P4）—— 编辑器与只读页共用一套取值/求值/应用
//
// 之前是三套各写一遍（ViewPage / SiteDetail / ScadaEditor 各一个 setInterval + 各自的 values），
// 结果同样是「液位罐怎么不动」，三个地方要改三遍。P4 起收敛到这里：
//   值缓存（按 站点.点位） → 求值（expr.js） → 应用（dyn.js）
//
// 三条硬要求（都来自任务书）：
//   1) @CurrentSite 优先级：URL 参数 > 画面 json.currentSite > 全局当前站点
//   2) 切站点时整张画面重新求值，不刷新页面
//   3) 一个全局定时器广播（不是每个对象各自 setInterval）

import { get, post } from '../utils/request'
import { applyDynToCanvas, clearDynLast } from './dyn'

const TICK_MS = 250          // 全局广播周期
const SNAP_MS = 3000         // SSE 静默期兜底快照

export function splitTag(tag) {
  // 4.3 起变量统一是 {site, point} 对象。这里是全平台唯一的拆分入口：
  //   事件写点位、取反复用读、rw 预取、趋势/表格取历史，全部走这里。
  // 早期只做 String(tag)，对象会被转成 "[object Object]" —— 拆出
  // site='' code='[object Object]'，后端就报「点位不存在：[object Object]」。
  // 归一化放在这一处，所有调用方一次修好。
  if (tag && typeof tag === 'object') {
    const site = typeof tag.site === 'string' ? tag.site.trim() : ''
    const code = typeof tag.point === 'string' ? tag.point.trim()
      : (typeof tag.code === 'string' ? tag.code.trim() : '')
    return { site, code }
  }
  const s = String(tag || '')
  const i = s.indexOf('.')
  if (i <= 0) return { site: '', code: s }
  return { site: s.slice(0, i), code: s.slice(i + 1) }
}

/** 变量 → 可读的字面量 "S001.V300"（对象和字符串都能吃），用于 UI 显示与日志 */
export function tagText(tag) {
  const { site, code } = splitTag(tag)
  return site ? site + '.' + code : code
}

export class ScadaRuntime {
  constructor(o = {}) {
    this.token = o.token || localStorage.getItem('token') || ''
    this.site = o.site || ''
    this.values = new Map()        // 'S001.LEVEL' -> {val, ts, q}
    this.es = null
    this.timers = []
    this.extraEs = []      // 多站点（提示词 11）：画面里跨站点变量的附加 SSE
    this.extra = []
    this.extraLast = new Map()   // site -> 最后收到 delta 的时间（跨站点静默兜底用）
    this.container = null
    this.onIssues = o.onIssues || (() => {})
    this.onTick = o.onTick || (() => {})
    this.onSse = o.onSse || (() => {})
    this.issueCount = 0
    this.applied = 0
    this.lastIssues = []
    // 订阅者（P6 控件）：每次广播后通知一次，组件据此重算自己绑定的值
    this.subs = new Set()
    // P8：组件模板定义（id → {id,name,w,h,iface,json}）与值列表（name → {kind,items}）
    // 实例渲染时从这里实时取模板 —— 不拷贝，才有「改模板所有实例同步变」
    this.fpt = new Map()
    this.lists = new Map()
    this._defs = null
  }

  // 一次性拉模板表 + 值列表（编辑器和只读页都调；失败不阻塞画面）
  async loadDefs(force) {
    if (this._defs && !force) return this._defs
    this._defs = (async () => {
      try {
        const [a, b] = await Promise.all([get('/api/fpt?full=1'), get('/api/valuelists')])
        const m = new Map()
        for (const f of (a && a.items) || []) m.set(Number(f.id), f)
        this.fpt = m
        const l = new Map()
        for (const x of (b && b.items) || []) {
          // 同时按 id 和 name 建索引：
          //   面板存的 listId 是数字 id，老数据可能存的是列表名。
          //   只按 name 建索引会导致 rt.list(102) 永远查不到 → 文本/图形列表全部 no_list。
          l.set(String(x.id), x)
          if (x.name !== undefined && x.name !== null) {
            l.set(String(x.name), x)
          }
        }
        this.lists = l
        return { fpt: m.size, lists: l.size }
      } catch (e) {
        return { fpt: 0, lists: 0, error: (e && e.message) || '加载失败' }
      }
    })()
    return this._defs
  }

  def(fid) {
    return this.fpt.get(Number(fid)) || null
  }

  list(name) {
    return this.lists.get(String(name || '')) || null
  }

  // —— 站点 ——
  setSite(site) {
    const s = sceneSite(site)
    if (s === this.site) {
      // 同一个站点但连接已断（页面切回、SSE 被关）：补一次连接，否则永远停在旧值
      if (s && !this.es) this.connect()
      return
    }
    this.site = s
    for (const f of this.subs) { try { f() } catch (e) { /* 忽略 */ } }
    // 换站：把「上一次成功求值的值」清掉，否则新站点缺点位时会留着上个站点的数字
    clearDynLast(this.container)
    this.connect()
    // 切站点后立刻重算一遍（不重建 DOM、不刷新页面）
    this.tick(true)
  }

  // —— 多站点订阅（提示词 11：画面变量是 {site,point}，一张画面可以混排多个站点）——
  // 画面加载后把 collectVarSites(json.items) 传进来：除主站点外，把其余绑定的站点也连上。
  // 护栏：单画面最多 6 个站点（一张画面混 6 个以上站点属于画面设计问题，不迁就）。
  watchSites(sites) {
    const list = [...new Set((sites || []).map(s => String(s || '').trim()).filter(Boolean))]
    this.extra = list.filter(s => s !== this.site).slice(0, 5)
    this.reconnectExtras()
  }

  reconnectExtras() {
    for (const es of (this.extraEs || [])) { try { es.close() } catch (e) { /* 已关 */ } }
    this.extraEs = []
    for (const site of (this.extra || [])) this.attachExtra(site)
  }

  // 单个附加站点：SSE + 断线重连 + 静默兜底 —— 与主站点同等对待。
  // 之前只建 ES 不设 onerror、不兜底，跨站点一条 SSE 断掉就永久静默（画面里 S002 那半边永远是 --）。
  attachExtra(site) {
    if (!site || !this.extra.includes(site)) return
    try {
      const url = `/api/live/subscribe?site=${encodeURIComponent(site)}&token=${encodeURIComponent(this.token)}`
      const es = new EventSource(url)
      es.addEventListener('delta', (e) => {
        this.extraLast.set(site, Date.now())
        let arr = []
        try { arr = JSON.parse(e.data) } catch (err) { return }
        for (const d of arr) {
          if (!d || !d.code || !d.site) continue
          const v = parseFloat(d.val)
          const kk = d.site + '.' + d.code
          const old = this.values.get(kk) || {}
          // 注意：这里绝不能写成 `|| {}` 换行接 `(() => {...})()`。
          // `{}` 后面紧跟 `(` 是合法的表达式续行，ASI 不会补分号，
          // 会被解析成「把 {} 当函数调用」→ 首次收到某点位时 values.get() 返回
          // undefined，走右边直接抛 TypeError: {} is not a function，
          // 回调中断、tick() 不执行 → 表现就是「组态只显示不自动刷新」。
          const nts = +d.ts || Date.now()
          let ob = old.obsMs
          if (old.ts && nts > old.ts) {
            const dt = nts - old.ts
            if (dt >= 100 && dt <= 600000) ob = ob ? Math.round(ob * 0.7 + dt * 0.3) : dt
          }
          this.values.set(kk, { val: isFinite(v) ? v : null, ts: nts, q: +(d.q || 0),
                                rw: old.rw, dtype: old.dtype, pollMs: old.pollMs, obsMs: ob })
        }
        this.tick(true)
      })
      es.onerror = () => {
        try { es.close() } catch (err) { /* 已关 */ }
        const i = this.extraEs.indexOf(es)
        if (i >= 0) this.extraEs.splice(i, 1)
        if (this.extra.includes(site)) {
          setTimeout(() => { if (this.extra.includes(site)) this.attachExtra(site) }, 5000)
        }
      }
      this.extraEs.push(es)
      this.extraLast.set(site, Date.now())
      this.snapshot(site)
    } catch (e) { /* 多站点连不上不影响主站点 */ }
  }

  // —— 值 ——
  // 修复 09：裸名（老画面 var:'LEVEL'）自动补当前站点。
  // 只在"没有前缀"时生效，手填的 S002.LEVEL 原样用，不会被改成当前站点。
  fullTag(tag) {
    const t = String(tag || '').trim()
    if (!t) return ''
    return t.includes('.') ? t : (this.site ? this.site + '.' + t : t)
  }

  read(tag) {
    const t = this.fullTag(tag)
    if (!t) return { found: false }
    const hit = this.values.get(t)
    if (!hit) return { found: false }
    // pollMs 一起带出去：上层按「该点位周期×3」算 stale，不能丢
    // dtype 也必须带：数值显示要按点位类型决定小数位（bool/整数 0 位，浮点按 decimals），
    // 在这一层丢掉的话 render 永远拿不到类型，只能一律 toFixed(2)。
    if (hit.val === null || hit.val === undefined) return { found: true, val: null, q: hit.q, ts: hit.ts, pollMs: hit.pollMs, obsMs: hit.obsMs, dtype: hit.dtype }
    return { found: true, val: hit.val, q: hit.q, ts: hit.ts, pollMs: hit.pollMs, obsMs: hit.obsMs, dtype: hit.dtype }
  }

  // 给 expr.js 用：裸名会补上当前站点
  evalCtx() {
    const self = this
    return {
      site: this.site,
      read(tag) {
        const t = String(tag || '')
        const full = t.includes('.') ? t : (self.site ? self.site + '.' + t : t)
        return self.read(full)
      }
    }
  }

  // 旧接口（renderScada 的 values）仍按 code 取：只给当前站点的平坦表
  flat() {
    const out = {}
    if (!this.site) return out
    const pre = this.site + '.'
    for (const [k, v] of this.values) {
      if (k.startsWith(pre)) out[k.slice(pre.length)] = v
    }
    return out
  }

  put(site, code, val, ts, q, meta) {
    const k = site + '.' + code
    const old = this.values.get(k) || {}
    const nts = ts || Date.now()
    // obsMs：实测相邻两次更新的间隔（指数平滑 0.7/0.3）。
    // poll_ms 是「配置意图」，网关按站点分片轮询，真实周期可能长很多
    // （实测 S001 配 500ms，实际 4s）——stale 阈值要跟着事实走。
    let obsMs = old.obsMs
    if (old.ts && nts > old.ts) {
      const dt = nts - old.ts
      if (dt >= 100 && dt <= 600000) obsMs = obsMs ? Math.round(obsMs * 0.7 + dt * 0.3) : dt
    }
    this.values.set(k, { val, ts: nts, q: q || 0,
                         rw: meta && meta.rw !== undefined ? meta.rw : old.rw,
                         dtype: (meta && meta.dtype) || old.dtype,
                         pollMs: (meta && meta.pollMs) || old.pollMs,
                         obsMs })
  }

  // I/O 域输入态用：rw=0 只读；取不到（SSE 先到、快照还没回）返回 null，前端按"未知"处理，
  // 真写了后端还会按 rw 拦一道（/api/write 400）
  rwOf(tag) {
    const hit = this.values.get(this.fullTag(tag))
    return hit && hit.rw !== undefined ? Number(hit.rw) : null
  }

  // —— 数据源 ——
  connect() {
    this.close()
    if (!this.site) return
    const site = this.site
    // 先要一份快照：SSE 只推动「变化」，没有快照的话首帧全是空的
    this.snapshot(site)
    // 跨站点附加连接（提示词 11 多站点画面）：主站连上后再补，别倒过来
    this.reconnectExtras()
    try {
      const url = `/api/live/subscribe?site=${encodeURIComponent(site)}&token=${encodeURIComponent(this.token)}`
      const es = new EventSource(url)
      this.es = es
      let got = false
      es.addEventListener('delta', (e) => {
        got = true
        this.onSse(true)
        let arr = []
        try { arr = JSON.parse(e.data) } catch (err) { return }
        for (const d of arr) {
          if (!d || !d.code) continue
          const s = d.site || site
          if (s !== this.site) continue
          const v = parseFloat(d.val)
          const kk = s + '.' + d.code
          const old = this.values.get(kk) || {}
          // 注意：这里绝不能写成 `|| {}` 换行接 `(() => {...})()`。
          // `{}` 后面紧跟 `(` 是合法的表达式续行，ASI 不会补分号，
          // 会被解析成「把 {} 当函数调用」→ 首次收到某点位时 values.get() 返回
          // undefined，走右边直接抛 TypeError: {} is not a function，
          // 回调中断、tick() 不执行 → 表现就是「组态只显示不自动刷新」。
          const nts = +d.ts || Date.now()
          let ob = old.obsMs
          if (old.ts && nts > old.ts) {
            const dt = nts - old.ts
            if (dt >= 100 && dt <= 600000) ob = ob ? Math.round(ob * 0.7 + dt * 0.3) : dt
          }
          this.values.set(kk, { val: isFinite(v) ? v : null, ts: nts, q: +(d.q || 0),
                                rw: old.rw, dtype: old.dtype, pollMs: old.pollMs, obsMs: ob })
        }
      })
      es.onerror = () => { this.onSse(false) }
      // 兜底快照：网关只在「值变化」时写 stream，恒定不变的点位永远收不到 delta。
      // 所以不能只看 got —— 有 SSE 数据时也最多 10s 强制拉一次全量，
      // 否则那些恒定值点位的 ts 会冻住，被误判 stale 而显示 --。
      this.pollId = setInterval(() => {
        const now = Date.now()
        if (!got || now - (this.lastSnap || 0) > 10000) {
          this.snapshot(this.site)
          this.lastSnap = now
        }
        got = false
        this.pollExtras()
      }, SNAP_MS)
    } catch (e) {
      this.pollId = setInterval(() => { this.snapshot(this.site); this.pollExtras() }, SNAP_MS)
    }
  }

  // 跨站点兜底：某站 SSE 静默超过 2 个周期就拉一次快照。
  // 断线重连有 5 秒空窗，空窗期靠这里续上，否则画面里那半边会短暂变 --
  pollExtras() {
    for (const s of (this.extra || [])) {
      if (Date.now() - (this.extraLast.get(s) || 0) > SNAP_MS * 2) {
        this.extraLast.set(s, Date.now())
        this.snapshot(s)
      }
    }
  }

  async snapshot(site) {
    if (!site) return
    try {
      const r = await get(`/api/site/${encodeURIComponent(site)}/snapshot`)
      const vs = (r && r.values) || {}
      for (const [code, v] of Object.entries(vs)) {
        this.put(site, code, v.val, v.ts, v.q, { rw: v.rw, dtype: v.dtype, pollMs: v.poll_ms })
      }
      this.tick(true)
    } catch (e) { /* 站点没权限或断网：保持上一帧 */ }
  }

  // —— 应用 ——
  attach(container) {
    this.container = container
    this.tick(true)
  }

  detach() {
    this.container = null
  }

  start() {
    if (this.timerId) return
    // 构造时就带了站点（只读页 / 已绑定站点的画面）：立刻连上。
    // 少了这一句，定时器转得再准也没有数据 —— 画面全是 --、动态化全标黄。
    if (this.site && !this.es) this.connect()
    this.timerId = setInterval(() => this.tick(), TICK_MS)
  }

  stop() {
    if (this.timerId) { clearInterval(this.timerId); this.timerId = 0 }
    this.close()
  }

  close() {
    if (this.es) { try { this.es.close() } catch (e) { /* 已关闭 */ } this.es = null }
    if (this.pollId) { clearInterval(this.pollId); this.pollId = 0 }
    // 停止连接时把跨站点附加连接一并关掉；重连由 connect() 末尾负责（stop() 不该重连）
    for (const es of (this.extraEs || [])) { try { es.close() } catch (e) { /* 已关闭 */ } }
    this.extraEs = []
  }

  // 一次广播：先同步旧式 var 绑定，再应用动态化
  tick(force) {
    const c = this.container
    if (!c || !c.__scada) return
    try {
      c.__scada.patch(this.flat(), c.__scada.data)
    } catch (e) { /* 单个组件异常不影响其他 */ }
    const r = applyDynToCanvas(c, this)
    this.applied = r.applied
    this.lastIssues = r.issues
    this.issueCount = r.issues.length
    // 保留明细，排障时 window.__rt.issues 能直接看到是哪个对象哪条绑定坏了
    this.issues = r.issues
    this.onIssues(r.issues)
    // 控件（趋势/仪表盘/表格…）订阅值变化：只递增一个版本号，不深拷贝值表
    for (const f of this.subs) { try { f() } catch (e) { /* 单个订阅者异常不影响其他 */ } }
    this.onTick()
  }

  subscribe(fn) {
    if (typeof fn !== 'function') return () => {}
    this.subs.add(fn)
    return () => this.subs.delete(fn)
  }

  // —— 写点位（按钮/输入框）——
  // opts 透传给 request（{ silent: true } 时不让底层弹 toast，由调用方给操作员看得懂的提示）
  async write(tag, value, opts) {
    const { site, code } = splitTag(tag)
    const s = site || this.site
    if (!s || !code) throw new Error('变量名要写成 站点.点位，如 S001.PUMP1_RUN')
    return post('/api/write', { site: s, point: code, value }, opts)
  }
}

function sceneSite(s) {
  return String(s || '').trim()
}

// 站点优先级：URL 参数 > 画面默认站点 > 全局
export function resolveSite({ query, page, global }) {
  // 优先级说明（2026-11-12 调整）：
  //   1) URL ?site=   —— 显式指定，编辑器预览 / 发布入口跳转会带
  //   2) page.site_id —— **画面绑定的站点，权威来源**（画面列表里能看能改的那个）
  //   3) page.currentSite —— 老画面兜底：4.3 之前的 json 只存了这个
  // 为什么 site_id 要优先于 currentSite：currentSite 是编辑器"上次看哪个站点"的记忆，
  // 不是画面归属。原来 currentSite 优先，导致画面绑 S201 却按 S001 取数（串站点）。
  const q = query && query.site
  if (q) return String(q)
  const sid = page && page.site_id
  if (sid) return String(sid)
  const cs = page && page.currentSite
  if (cs) return String(cs)
  return global ? String(global) : ''
}

// 批量解析变量名（200 站点预览）：一次请求，避免 200 个单查
export async function resolveTags(tags) {
  const list = (tags || []).slice(0, 500)
  if (!list.length) return []
  try {
    const r = await post('/api/scada/resolve', { tags: list })
    return (r && r.items) || []
  } catch (e) {
    return []
  }
}
