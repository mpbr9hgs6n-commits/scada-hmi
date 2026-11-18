// 组态表达式求值引擎（P4）
//
// 为什么自己写词法+递归下降，而不用 eval / new Function：
// 表达式来自画面 json（人写的、也存在库里），eval 等于把「谁能改画面」变成「谁能执行任意 JS」。
// 这里只认白名单语法：变量引用、字符串拼接、四则、比较、三元、括号、字面量。
// 不做函数定义、循环、对象字面量、赋值，也绝不调 eval / new Function。
//
// 支持：
//   S001.LEVEL          带站点前缀的变量
//   LEVEL               裸名 = @CurrentSite + '.' + LEVEL（等价写法）
//   @CurrentSite        当前站点 id，字符串
//   @Tag("S001.LEVEL")  动态拼出来的变量名
//   @Quality("S001.LEVEL")  质量码（0 正常 / 1 坏值 / -1 不存在）
//   "abc" + '.LEVEL'    字符串拼接
//   LEVEL * 100         算术 + - * / %
//   LEVEL > 3.5 ? 1 : 0 比较 + 三元
//
// 返回值统一为对象，绝不抛异常给调用方：
//   { ok: true, value, quality: 'good'|'bad', refs: [tag...] }
//   { ok: false, reason: 'tag_not_found'|'bad_number'|'syntax'|'empty', msg, pos, tag }

const TAG_CHAR = /[A-Za-z0-9_\-.:]/
const ID_START = /[A-Za-z_]/

// —— 词法 ——
function lex(src) {
  const out = []
  let i = 0
  const n = src.length
  while (i < n) {
    const c = src[i]
    if (c === ' ' || c === '\t' || c === '\n' || c === '\r') { i++; continue }

    // 字符串字面量："..." 或 '...'，支持反斜杠转义
    if (c === '"' || c === "'") {
      const q = c
      let j = i + 1
      let s = ''
      let closed = false
      while (j < n) {
        const d = src[j]
        if (d === '\\') {
          const nx = src[j + 1]
          s += nx === 'n' ? '\n' : nx === 't' ? '\t' : (nx === undefined ? '\\' : nx)
          j += 2
          continue
        }
        if (d === q) { closed = true; break }
        s += d
        j++
      }
      if (!closed) return { err: { msg: '字符串没有闭合（少了 ' + q + '）', pos: i } }
      out.push({ t: 'str', v: s, pos: i })
      i = j + 1
      continue
    }

    // 数字：123 / 1.5 / .5
    if (/[0-9]/.test(c) || (c === '.' && /[0-9]/.test(src[i + 1] || ''))) {
      let j = i
      while (j < n && /[0-9]/.test(src[j])) j++
      if (src[j] === '.') { j++; while (j < n && /[0-9]/.test(src[j])) j++ }
      out.push({ t: 'num', v: Number(src.slice(i, j)), pos: i })
      i = j
      continue
    }

    // @ 开头：@CurrentSite / @Tag(...) / @Quality(...)
    if (c === '@') {
      let j = i + 1
      while (j < n && /[A-Za-z0-9_]/.test(src[j])) j++
      const name = src.slice(i + 1, j)
      if (!name) return { err: { msg: '@ 后面要跟名字，如 @CurrentSite', pos: i } }
      out.push({ t: 'at', v: name, pos: i })
      i = j
      continue
    }

    // 标识符 / 变量：允许点号（S001.LEVEL）
    if (ID_START.test(c)) {
      let j = i
      while (j < n && TAG_CHAR.test(src[j])) j++
      // 末尾的点号不算（如 "a." → a + 语法错，交给解析器报）
      let raw = src.slice(i, j)
      while (raw.endsWith('.')) raw = raw.slice(0, -1)
      out.push({ t: 'id', v: raw, pos: i })
      i = i + raw.length
      continue
    }

    // 运算符（先长后短）
    const three = src.slice(i, i + 2)
    if (three === '>=' || three === '<=' || three === '==' || three === '!=' || three === '&&' || three === '||') {
      out.push({ t: 'op', v: three, pos: i })
      i += 2
      continue
    }
    if ('+-*/%<>!?:(),'.includes(c)) {
      out.push({ t: 'op', v: c, pos: i })
      i++
      continue
    }
    return { err: { msg: '不认识的字符「' + c + '」', pos: i } }
  }
  out.push({ t: 'eof', pos: n })
  return { tokens: out }
}

// —— 语法：递归下降 ——
// 优先级（低→高）：? :  →  ||  →  &&  →  == !=  →  > < >= <=  →  + -  →  * / %  →  一元 → 基本
function parse(tokens) {
  let p = 0
  const peek = () => tokens[p]
  const eat = (v) => {
    const t = tokens[p]
    if (t && t.t === 'op' && t.v === v) { p++; return true }
    return false
  }
  const expect = (v, what) => {
    if (!eat(v)) {
      const t = peek()
      throw { msg: '这里需要「' + what + '」', pos: t ? t.pos : 0 }
    }
  }

  function ternary() {
    const c = orExpr()
    if (eat('?')) {
      const a = ternary()
      expect(':', ':')
      const b = ternary()
      return { k: '?', c, a, b }
    }
    return c
  }
  function orExpr() {
    let l = andExpr()
    while (eat('||')) l = { k: 'bin', op: '||', l, r: andExpr() }
    return l
  }
  function andExpr() {
    let l = eqExpr()
    while (eat('&&')) l = { k: 'bin', op: '&&', l, r: eqExpr() }
    return l
  }
  function eqExpr() {
    let l = cmpExpr()
    for (;;) {
      if (eat('==')) l = { k: 'bin', op: '==', l, r: cmpExpr() }
      else if (eat('!=')) l = { k: 'bin', op: '!=', l, r: cmpExpr() }
      else return l
    }
  }
  function cmpExpr() {
    let l = addExpr()
    for (;;) {
      const t = peek()
      if (t && t.t === 'op' && (t.v === '>' || t.v === '<' || t.v === '>=' || t.v === '<=')) {
        p++
        l = { k: 'bin', op: t.v, l, r: addExpr() }
      } else return l
    }
  }
  function addExpr() {
    let l = mulExpr()
    for (;;) {
      if (eat('+')) l = { k: 'bin', op: '+', l, r: mulExpr() }
      else if (eat('-')) l = { k: 'bin', op: '-', l, r: mulExpr() }
      else return l
    }
  }
  function mulExpr() {
    let l = unary()
    for (;;) {
      if (eat('*')) l = { k: 'bin', op: '*', l, r: unary() }
      else if (eat('/')) l = { k: 'bin', op: '/', l, r: unary() }
      else if (eat('%')) l = { k: 'bin', op: '%', l, r: unary() }
      else return l
    }
  }
  function unary() {
    if (eat('-')) return { k: 'neg', e: unary() }
    if (eat('!')) return { k: 'not', e: unary() }
    if (eat('+')) return unary()
    return primary()
  }
  function primary() {
    const t = peek()
    if (!t) throw { msg: '表达式不完整', pos: 0 }
    if (t.t === 'num') { p++; return { k: 'lit', v: t.v } }
    if (t.t === 'str') { p++; return { k: 'lit', v: t.v } }
    if (t.t === 'op' && t.v === '(') {
      p++
      const e = ternary()
      expect(')', ')')
      return e
    }
    if (t.t === 'at') {
      p++
      const name = t.v
      if (name === 'CurrentSite') return { k: 'site' }
      if (name === 'Tag' || name === 'Quality') {
        expect('(', '(')
        const arg = ternary()
        expect(')', ')')
        return { k: name === 'Tag' ? 'tagfn' : 'qualsfn', arg }
      }
      throw { msg: '不认识的 @' + name + '（只支持 @CurrentSite / @Tag / @Quality）', pos: t.pos }
    }
    if (t.t === 'id') {
      p++
      return { k: 'tag', name: t.v, pos: t.pos }
    }
    throw { msg: '这里需要一个值', pos: t.pos }
  }

  const ast = ternary()
  const rest = peek()
  if (rest && rest.t !== 'eof') throw { msg: '多出来的内容「' + (rest.v || '') + '」', pos: rest.pos }
  return { ast }
}

// —— 求值 ——
const cache = new Map()       // key -> {ts, res}
const TTL = 200               // 任务书要求：200ms 缓存（20 万点位时不能每 tick 全量算）
let cacheHits = 0
let cacheMiss = 0

function numOf(v) {
  if (typeof v === 'number') return isFinite(v) ? v : NaN
  if (typeof v === 'boolean') return v ? 1 : 0
  if (typeof v === 'string' && v.trim() !== '') return Number(v)
  return NaN
}

function fmtTag(tag) {
  // 裸名（没有点号）= 当前站点下的点位
  return tag.includes('.') ? tag : null
}

function evalNode(node, ctx, st) {
  switch (node.k) {
    case 'lit':
      return node.v

    case 'site':
      if (!ctx.site) throw { reason: 'no_site', msg: '没有 @CurrentSite（未选站点）' }
      return ctx.site

    case 'tag': {
      const name = node.name
      if (!ctx.read) throw { reason: 'tag_not_found', msg: '没有实时数据源' }
      const full = fmtTag(name) ? name : (ctx.site ? ctx.site + '.' + name : name)
      if (!fmtTag(name) && !ctx.site) throw { reason: 'no_site', msg: '裸变量名需要先选站点' }
      const r = ctx.read(full)
      if (!r || !r.found) throw { reason: 'tag_not_found', tag: full, msg: '点位不存在：' + full }
      st.refs.push(full)
      if (r.q === 1) st.bad = true
      if (r.val === null || r.val === undefined) {
        throw { reason: 'bad_number', tag: full, msg: '点位还没有值：' + full }
      }
      return r.val
    }

    case 'tagfn': {
      const v = evalNode(node.arg, ctx, st)
      const full = String(v)
      const r = ctx.read ? ctx.read(full) : null
      if (!r || !r.found) throw { reason: 'tag_not_found', tag: full, msg: '点位不存在：' + full }
      st.refs.push(full)
      if (r.q === 1) st.bad = true
      return r.val
    }

    case 'qualsfn': {
      const v = evalNode(node.arg, ctx, st)
      const full = String(v)
      const r = ctx.read ? ctx.read(full) : null
      if (!r || !r.found) return -1
      st.refs.push(full)
      return r.q === 1 ? 1 : 0
    }

    case 'neg': {
      const v = evalNode(node.e, ctx, st)
      const n = numOf(v)
      if (Number.isNaN(n)) throw { reason: 'bad_number', msg: '取负号的值不是数字' }
      return -n
    }

    case 'not':
      return !truthy(evalNode(node.e, ctx, st))

    case '?':
      return truthy(evalNode(node.c, ctx, st)) ? evalNode(node.a, ctx, st) : evalNode(node.b, ctx, st)

    case 'bin': {
      const op = node.op
      // 短路：&& || 不能先把两边都算完（右侧可能引用不存在的点位）
      if (op === '&&') return truthy(evalNode(node.l, ctx, st)) ? truthy(evalNode(node.r, ctx, st)) : false
      if (op === '||') return truthy(evalNode(node.l, ctx, st)) ? true : truthy(evalNode(node.r, ctx, st))

      const l = evalNode(node.l, ctx, st)
      const r = evalNode(node.r, ctx, st)
      if (op === '+' && (typeof l === 'string' || typeof r === 'string')) return String(l) + String(r)
      if (op === '==') return l == r            // eslint-disable-line eqeqeq
      if (op === '!=') return l != r            // eslint-disable-line eqeqeq
      const a = numOf(l)
      const b = numOf(r)
      if (Number.isNaN(a) || Number.isNaN(b)) {
        throw { reason: 'bad_number', msg: '算术/比较的运算数不是数字：' + JSON.stringify(l) + ' ' + op + ' ' + JSON.stringify(r) }
      }
      switch (op) {
        case '+': return a + b
        case '-': return a - b
        case '*': return a * b
        case '/': return b === 0 ? NaN : a / b
        case '%': return b === 0 ? NaN : a % b
        case '>': return a > b
        case '<': return a < b
        case '>=': return a >= b
        case '<=': return a <= b
        default: throw { reason: 'syntax', msg: '不支持的运算符 ' + op }
      }
    }
    default:
      throw { reason: 'syntax', msg: '不支持的语法节点' }
  }
}

function truthy(v) {
  if (typeof v === 'string') return v !== '' && v !== '0' && v.toLowerCase() !== 'false'
  return !!v
}

// 编译（带语法缓存的 AST）
const astCache = new Map()

export function compile(expr) {
  const src = String(expr == null ? '' : expr)
  if (astCache.has(src)) return astCache.get(src)
  let out
  if (!src.trim()) {
    out = { ok: false, reason: 'empty', msg: '表达式为空', pos: 0 }
  } else {
    const lx = lex(src)
    if (lx.err) out = { ok: false, reason: 'syntax', msg: lx.err.msg, pos: lx.err.pos }
    else {
      try {
        const { ast } = parse(lx.tokens)
        out = { ok: true, ast }
      } catch (e) {
        // 解析器用 throw {msg,pos} 报错（不是 Error），这里原样转成结果对象
        out = { ok: false, reason: 'syntax', msg: e && e.msg ? e.msg : '语法错误', pos: (e && e.pos) || 0 }
      }
    }
  }
  if (astCache.size > 500) astCache.clear()
  astCache.set(src, out)
  return out
}

// 语法校验：给 UI 的「检查」按钮用，返回 {ok} 或 {ok:false,msg,pos}
export function validate(expr) {
  const c = compile(expr)
  return c.ok ? { ok: true } : c
}

// 真正的求值。ctx = { site, read(tag) -> {found,val,q,ts} }
export function evaluate(expr, ctx) {
  const c = compile(expr)
  if (!c.ok) return c
  const st = { refs: [], bad: false }
  try {
    const value = evalNode(c.ast, ctx || {}, st)
    if (typeof value === 'number' && !isFinite(value)) {
      return { ok: false, reason: 'bad_number', msg: '计算结果不是有效数字（可能除零）' }
    }
    return { ok: true, value, quality: st.bad ? 'bad' : 'good', refs: st.refs }
  } catch (e) {
    if (e && e.reason) {
      return { ok: false, reason: e.reason, msg: e.msg || '', tag: e.tag, pos: e.pos }
    }
    return { ok: false, reason: 'syntax', msg: (e && e.message) || '求值失败' }
  }
}

// 200ms 缓存：同一个表达式 + 同一个站点，200ms 内只算一次。
// 注意 key 里必须带 site，否则切站点会读到上一个站点的缓存。
export function evaluateCached(expr, ctx) {
  const key = (ctx && ctx.site ? ctx.site : '') + '|' + String(expr)
  const now = Date.now()
  const hit = cache.get(key)
  if (hit && now - hit.ts < TTL) {
    cacheHits++
    // 缓存里存的是结果，refs 也一并返回；调用方不要改它
    return hit.res
  }
  cacheMiss++
  const res = evaluate(expr, ctx)
  if (cache.size > 2000) cache.clear()
  cache.set(key, { ts: now, res })
  return res
}

export function cacheStats() {
  return { hits: cacheHits, miss: cacheMiss, size: cache.size }
}

export function clearExprCache() {
  cache.clear()
}

// 名称表达式（间接变量连接）：只允许拼出字符串，用同样的引擎算
export function evalName(expr, ctx) {
  const res = evaluate(expr, ctx)
  if (!res.ok) return res
  return { ok: true, value: String(res.value) }
}
