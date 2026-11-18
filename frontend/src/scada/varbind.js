// 变量绑定（提示词 10 4.3）：页面里只允许「站点 + 点位」两级对象，禁止表达式字符串。
//   ✅ { "site": "S001", "point": "LEVEL" }
//   ❌ { "var": "S001.LEVEL" } / "${S001.LEVEL}" / "@CurrentSite + '.LEVEL'"
// 渲染时：site → 订阅 rt:{site}，point → 取该 field。

export function isValidVar(v) {
  if (!v || typeof v !== 'object' || Array.isArray(v)) return false
  // 必须按 trim 后的结果判空：'  ' 这种空白点位原先会拼出 "S001." 的坏 tag，
  // 又不报错，到了运行时才变成「取不到值」，最难查。
  const site = typeof v.site === 'string' ? v.site.trim() : ''
  const point = typeof v.point === 'string' ? v.point.trim() : ''
  return site.length > 0 && point.length > 0
}

/** 变量对象 → 内部 tag 字符串（S001.LEVEL）。非法返回 ''（调用方必须报错，不要猜） */
export function tagOfVar(v) {
  return isValidVar(v) ? `${v.site.trim()}.${v.point.trim()}` : ''
}

/** 变量 → 可读文本，对象和字符串都能吃（UI 显示、日志用，永不返回 "[object Object]"） */
export function tagText(v) {
  if (v && typeof v === 'object') return tagOfVar(v)
  return String(v == null ? '' : v).trim()
}

/**
 * 文本 → {site, point} 对象（保存时用，和 4.3 规范对齐）。
 *   "S001.V300" → {site:'S001', point:'V300'}
 *   裸点位名 "V300" → undefined（没有站点前缀，交给运行时按当前站点兜底，不要瞎猜站点）
 *   已经是合法对象 → 原样返回副本
 */
export function toVar(v) {
  if (v && typeof v === 'object') {
    return isValidVar(v) ? { site: v.site.trim(), point: v.point.trim() } : undefined
  }
  const s = String(v == null ? '' : v).trim()
  if (!s) return undefined
  const i = s.indexOf('.')
  if (i <= 0) return undefined
  const site = s.slice(0, i).trim()
  const point = s.slice(i + 1).trim()
  return site && point ? { site, point } : undefined
}

/** 对象上的 var 是否非法（存在但不是 {site, point} 对象）——字符串格式必须报错 */
export function invalidVar(item) {
  return !!item && item.var !== undefined && item.var !== null && item.var !== ''
    && !isValidVar(item.var)
}

/** 递归收集画面里所有合法变量的站点（运行时按站点订阅） */
export function collectVarSites(items) {
  const out = new Set()
  const walk = (arr) => {
    for (const it of arr || []) {
      if (isValidVar(it && it.var)) out.add(it.var.site)
      if (it && Array.isArray(it.items)) walk(it.items)
    }
  }
  walk(items)
  return [...out]
}

/** 递归找出第一个非法 var 的对象（报「变量格式错误」用） */
export function findInvalidVar(items) {
  const walk = (arr) => {
    for (const it of arr || []) {
      if (invalidVar(it)) return it
      if (it && Array.isArray(it.items)) {
        const hit = walk(it.items)
        if (hit) return hit
      }
    }
    return null
  }
  return walk(items)
}
