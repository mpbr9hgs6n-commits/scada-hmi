/**
 * 数字输入弹窗（运行态 /view、/publish 与编辑器预览共用）。
 *
 * 用户 2026-11 要求：
 *   1. I/O 域不再原地输入，改成弹窗
 *   2. 弹窗里只有数字和小数点（外加退格），带「确认」「取消」
 *   3. 确认 → 提交并关闭；取消 → 不提交也关闭
 *   4. 数字和小数点既能鼠标点击，也能键盘直接打
 *
 * 为什么不去用 Vue 组件：render.js 是纯 DOM 渲染管线，运行态没有 Vue 实例可挂。
 * 这里用原生 DOM 拼，样式内联到 style 标签一次注入，便于和 scada 主题对齐。
 */

const STYLE_ID = 'scada-numpad-style'
const CSS = `
.scada-np-mask {
  position: fixed; inset: 0; z-index: 99999;
  background: rgba(4, 12, 20, .72);
  display: flex; align-items: center; justify-content: center;
  font-family: Bahnschrift, 'Segoe UI', sans-serif;
}
.scada-np {
  width: 320px; padding: 14px 16px 16px;
  background: #0f2130; border: 1px solid #1e3a52; border-radius: 10px;
  box-shadow: 0 18px 48px rgba(0, 0, 0, .55);
  color: #e2e8f0; user-select: none;
}
.scada-np-ttl {
  font-size: 13px; color: #93a8bd; margin-bottom: 8px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.scada-np-disp {
  height: 52px; line-height: 52px; padding: 0 12px; margin-bottom: 4px;
  background: #08161f; border: 1px solid #1e3a52; border-radius: 6px;
  font-size: 30px; text-align: right; letter-spacing: .5px;
  color: #ffd24d; overflow: hidden;
}
.scada-np-disp.empty { color: #3f5570; }
.scada-np-disp.bad { border-color: #ef4444; color: #f87171; }
.scada-np-hint {
  height: 18px; line-height: 18px; font-size: 12px;
  color: #f87171; margin-bottom: 8px; text-align: right;
}
.scada-np-hint.dim { color: #5b7591; }
.scada-np-keys {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;
}
.scada-np-k {
  height: 46px; display: flex; align-items: center; justify-content: center;
  background: #16293a; border: 1px solid #23415a; border-radius: 6px;
  font-size: 20px; color: #dbe7f3; cursor: pointer;
  transition: background .12s, border-color .12s;
}
.scada-np-k:hover { background: #1b3348; }
.scada-np-k:active { background: #23415a; }
.scada-np-k.wide { grid-column: span 2; }
.scada-np-btns { display: flex; gap: 10px; margin-top: 12px; }
.scada-np-btn {
  flex: 1; height: 44px; border-radius: 6px; cursor: pointer;
  font-size: 15px; border: 1px solid transparent;
}
.scada-np-btn.cancel { background: #1a2d3e; border-color: #23415a; color: #b6c7d9; }
.scada-np-btn.cancel:hover { background: #22394d; }
.scada-np-btn.ok { background: #1d7fd6; color: #fff; }
.scada-np-btn.ok:hover { background: #2a91ef; }
.scada-np-btn.ok:disabled { background: #24405a; color: #6b8ba6; cursor: not-allowed; }
`

function ensureStyle() {
  if (document.getElementById(STYLE_ID)) return
  const st = document.createElement('style')
  st.id = STYLE_ID
  st.textContent = CSS
  document.head.appendChild(st)
}

/**
 * 打开数字输入弹窗。
 *
 * @param {Object} o
 * @param {string} o.title     标题（一般显示「名称 → 点位」）
 * @param {string} [o.unit]    单位，显示在提示行
 * @param {number|string} [o.initial] 初始值
 * @param {number|null} [o.min] 下限
 * @param {number|null} [o.max] 上限
 * @param {number} [o.decimals] 小数位上限（0 = 只允许整数）
 * @param {boolean} [o.confirmBeforeWrite] 提交前是否再要一次确认（沿用原 confirmWrite）
 * @param {(v:number)=>Promise|void} o.onSubmit 点「确认」时调用，异常则弹窗保持打开并显示原因
 * @returns {{close:()=>void}}
 */
export function openNumericPad(o) {
  ensureStyle()
  const opt = o || {}
  const dec = (opt.decimals === null || opt.decimals === undefined) ? 6 : Number(opt.decimals)
  const allowDot = dec > 0
  const lo = (opt.min === null || opt.min === undefined || opt.min === '') ? null : Number(opt.min)
  const hi = (opt.max === null || opt.max === undefined || opt.max === '') ? null : Number(opt.max)

  const mask = document.createElement('div')
  mask.className = 'scada-np-mask'

  const panel = document.createElement('div')
  panel.className = 'scada-np'
  mask.appendChild(panel)

  const ttl = document.createElement('div')
  ttl.className = 'scada-np-ttl'
  ttl.textContent = opt.title || '输入数值'
  panel.appendChild(ttl)

  const disp = document.createElement('div')
  disp.className = 'scada-np-disp'
  panel.appendChild(disp)

  const hint = document.createElement('div')
  hint.className = 'scada-np-hint dim'
  panel.appendChild(hint)

  const keys = document.createElement('div')
  keys.className = 'scada-np-keys'
  panel.appendChild(keys)

  const btns = document.createElement('div')
  btns.className = 'scada-np-btns'
  panel.appendChild(btns)

  const btnCancel = document.createElement('button')
  btnCancel.className = 'scada-np-btn cancel'
  btnCancel.textContent = '取消'
  const btnOk = document.createElement('button')
  btnOk.className = 'scada-np-btn ok'
  btnOk.textContent = '确认'
  btns.appendChild(btnCancel)
  btns.appendChild(btnOk)

  // ---- 状态 ----
  let buf = ''
  let closed = false
  // 打开弹窗时 buf 里是当前值。用户第一次按键/退格就应该「重输」而不是在原值后面追，
  // 否则点 1 2 . 5 会得到 211125（原值 211）。dirty 标记用户是否已动过键盘。
  let dirty = false

  function initVal() {
    const v = opt.initial
    if (v === null || v === undefined || v === '' || Number.isNaN(Number(v))) return ''
    const n = Number(v)
    return Number.isInteger(n) ? String(n) : String(Number(n.toFixed(dec)))
  }
  buf = initVal()

  function rangeText() {
    if (lo === null && hi === null) return ''
    return `范围 ${lo === null ? '-∞' : lo} ~ ${hi === null ? '+∞' : hi}`
  }

  function refresh() {
    disp.textContent = buf === '' ? '0' : buf
    disp.classList.toggle('empty', buf === '')
    disp.classList.remove('bad')
    // 提示行：有错误就显示错误，否则显示范围/单位
    const rt = rangeText()
    const ut = opt.unit ? `单位 ${opt.unit}` : ''
    const line = [rt, ut].filter(Boolean).join('   ')
    hint.textContent = line
    hint.classList.add('dim')
    btnOk.disabled = false
  }

  function fail(msg) {
    disp.classList.add('bad')
    hint.textContent = msg
    hint.classList.remove('dim')
  }

  function press(ch) {
    if (closed) return
    if (!dirty) {
      // 首次按键：丢掉初始值，从空开始
      dirty = true
      // 退格在未编辑状态下相当于「清空」
      if (ch === 'back') { buf = ''; refresh(); return }
      buf = ''
    }
    if (ch === '.') {
      if (!allowDot) return
      if (buf.includes('.')) return
      buf = (buf === '' ? '0' : buf) + '.'
    } else if (ch === 'back') {
      buf = buf.slice(0, -1)
    } else if (/^[0-9]$/.test(ch)) {
      // 限制小数位数
      const i = buf.indexOf('.')
      if (i >= 0 && buf.length - i - 1 >= dec) return
      // 前导零：'0' 再按数字就替换
      if (buf === '0') buf = ch
      else buf += ch
      if (buf.length > 16) return
    }
    refresh()
  }

  // ---- 键盘布局：7 8 9 / 4 5 6 / 1 2 3 / . 0 ⌫ ----
  const layout = [
    ['7', '8', '9'],
    ['4', '5', '6'],
    ['1', '2', '3'],
    ['.', '0', 'back'],
  ]
  for (const row of layout) {
    for (const k of row) {
      const b = document.createElement('div')
      b.className = 'scada-np-k'
      b.textContent = k === 'back' ? '⌫' : k
      if (k === '.' && !allowDot) {
        b.style.opacity = '.3'
        b.style.cursor = 'not-allowed'
      }
      b.addEventListener('click', () => press(k))
      keys.appendChild(b)
    }
  }

  // ---- 物理键盘 ----
  function onKey(e) {
    if (closed) return
    if (e.key === 'Escape') { e.preventDefault(); close(); return }
    if (e.key === 'Enter') { e.preventDefault(); submit(); return }
    if (e.key === 'Backspace') { e.preventDefault(); press('back'); return }
    if (e.key === '.' || e.key === ',') { e.preventDefault(); press('.'); return }
    if (/^[0-9]$/.test(e.key)) { e.preventDefault(); press(e.key) }
  }
  document.addEventListener('keydown', onKey, true)

  // ---- 提交 / 关闭 ----
  async function submit() {
    if (closed) return
    if (buf === '' || buf === '.') { fail('请输入数值'); return }
    const n = Number(buf)
    if (!Number.isFinite(n)) { fail('不是有效数字'); return }
    if (lo !== null && n < lo) { fail(`不能小于 ${lo}`); return }
    if (hi !== null && n > hi) { fail(`不能大于 ${hi}`); return }
    if (opt.confirmBeforeWrite && !window.confirm(`确认把 ${n} 写入 ${opt.title || ''}？`)) return
    btnOk.disabled = true
    btnOk.textContent = '提交中…'
    try {
      await opt.onSubmit?.(n)
      close()
    } catch (e) {
      btnOk.disabled = false
      btnOk.textContent = '确认'
      fail((e && e.message) || '写入失败')
    }
  }

  function close() {
    if (closed) return
    closed = true
    document.removeEventListener('keydown', onKey, true)
    mask.remove()
  }

  btnCancel.addEventListener('click', close)
  btnOk.addEventListener('click', submit)
  mask.addEventListener('mousedown', (e) => { if (e.target === mask) close() })

  document.body.appendChild(mask)
  refresh()
  return { close }
}
