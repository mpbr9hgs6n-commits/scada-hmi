// 控件运行环境（P6）
//
// 一个画布一个 env，所有控件共享。env 只做三件事：
//   1) 告诉控件现在是编辑态还是运行态（mode）
//   2) 提供取值入口 read(expr) —— 走 P4 的同一套求值引擎，不另写一份
//   3) 给一个「值版本号」v —— runtime 每 tick 递增，组件的 computed 依赖它就能自动重算
//
// 为什么用版本号而不是把值深拷贝到 reactive：一屏 20 个控件、每个 250ms 全量拷贝一次
// 值表，纯属浪费；组件只读自己关心的那几个表达式，读到版本变化就重算即可。
import { reactive } from 'vue'
import { evaluate } from '../expr'
// 4.3 变量是 {site,point} 对象，控件的 read() 也要能直接吃对象
import { tagOfVar, tagText } from '../varbind'
import { clock } from './clock'

export function makeEnv(o = {}) {
  const env = reactive({
    mode: o.mode === 'edit' ? 'edit' : 'runtime',
    rt: o.rt || null,
    site: o.site || '',
    v: 0,
    clock,
    toast: o.toast || (() => {}),
    // 控件里需要跳转/关画面时用（报警窗双击、视频窗全屏之类）
    openPage: o.openPage || null,
    closePage: o.closePage || null
  })

  // 求值：与动态化、事件动作共用 expr.js，控件的显示值不会和画面上的数字对不上
  env.read = (expr) => {
    void env.v                    // 建立依赖：值一更新，用到它的 computed 就重算
    if (!env.rt) return { ok: false, reason: 'no_rt' }
    // 变量可能是 {site, point} 对象（4.3 规范），String(对象) 会变 "[object Object]"
    // → lex 语法错 → 控件全部读不到值。对象直接按 tag 读，字符串才走表达式引擎。
    if (expr && typeof expr === 'object') {
      const tag = tagOfVar(expr)
      if (!tag) return { ok: false, reason: 'bad_var', msg: '变量必须是 {site, point}' }
      const v = env.rt.read(tag)
      if (!v || !v.found) return { ok: false, reason: 'tag_not_found', tag, msg: '点位不存在：' + tag }
      // dtype 必须带出去：控件（仪表盘/表格）要按点位类型决定小数位，
      // uint32/uint16/byte/bool 不能补 .00。丢掉的话整数会被 toFixed(2) 变成 2587962.00
      return { ok: true, value: v.val, quality: v.q === 1 ? 'bad' : 'good', tag, dtype: v.dtype }
    }
    const s = String(expr == null ? '' : expr).trim()
    if (!s) return { ok: false, reason: 'empty' }
    try {
      return evaluate(s, env.rt.evalCtx())
    } catch (e) {
      return { ok: false, reason: 'syntax', msg: String(e && e.message) }
    }
  }

  // 只取数值（拿不到就是 null，绝不返回 0 —— 0 是值，null 是没值，两者不能混）
  env.num = (expr) => {
    const r = env.read(expr)
    if (!r || !r.ok) return null
    const n = Number(r.value)
    return isFinite(n) ? n : null
  }

  env.bump = () => { env.v = env.v + 1 }
  env.setMode = (m) => { env.mode = m === 'edit' ? 'edit' : 'runtime' }
  env.setSite = (s) => { env.site = s || '' }
  return env
}
