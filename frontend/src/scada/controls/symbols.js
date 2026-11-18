// 符号库图元（P6）——工艺图元按 100×100 坐标系画，写入时按 w/h 拉伸
//
// 为什么与 render.js 的 VECTOR 分开：VECTOR 里是 P1 就有的基础图元（罐/泵/管道），
// 这里是任务书点名的 14 个符号库图元，条目要能在符号库里列出来、能被拖到画布。
// 两边都是纯字符串拼接（不含用户输入），不存在注入风险。

export const SYMBOL_GROUPS = [
  {
    key: '泵类', items: [
      { id: 'pump_v', name: '立式泵' },
      { id: 'pump_h', name: '卧式泵' },
      { id: 'pump_sub', name: '潜水泵' },
      { id: 'motor', name: '电机' }
    ]
  },
  {
    key: '阀门', items: [
      { id: 'valve_gate', name: '闸阀' },
      { id: 'valve_butterfly', name: '蝶阀' },
      { id: 'valve_ball', name: '球阀' },
      { id: 'valve_check', name: '止回阀' }
    ]
  },
  {
    key: '罐体', items: [
      { id: 'tank_round', name: '圆罐' },
      { id: 'pool_square', name: '方池' }
    ]
  },
  {
    key: '输送', items: [
      { id: 'grill_cleaner', name: '格栅清污机' },
      { id: 'screw_conveyor', name: '螺旋输送机' },
      { id: 'belt_conveyor', name: '皮带机' }
    ]
  },
  {
    key: '风机', items: [
      { id: 'fan', name: '风机' }
    ]
  }
]

export const ALL_SYMBOLS = SYMBOL_GROUPS.reduce((a, g) => a.concat(g.items.map(i => ({ ...i, group: g.key }))), [])

export function symbolName(id) {
  const s = ALL_SYMBOLS.find(x => x.id === id)
  return s ? s.name : id
}

// p = { stroke, accent, text, bg, sw }
export function symbolSvg(id, w, h, p) {
  const S = p.stroke, A = p.accent, T = p.text, sw = Math.max(1.2, p.sw || 1.6)
  const body = SYMBOL_BODY[id] ? SYMBOL_BODY[id](S, A, T, sw) : `<rect x="8" y="8" width="84" height="84" fill="none" stroke="${S}"/>`
  return `<g transform="scale(${(w / 100).toFixed(4)},${(h / 100).toFixed(4)})">${body}</g>`
}

const SYMBOL_BODY = {
  // 立式泵：圆泵体 + 上方出口
  pump_v: (S, A, T, sw) => `
    <circle cx="50" cy="58" r="26" fill="none" stroke="${S}" stroke-width="${sw}"/>
    <path d="M50 32 V10" stroke="${S}" stroke-width="${sw * 2}"/>
    <path d="M38 10 H62" stroke="${A}" stroke-width="${sw * 1.2}"/>
    <path d="M50 58 m-9 0 a9 9 0 1 1 18 0" fill="none" stroke="${A}" stroke-width="${sw}"/>`,

  // 卧式泵：圆泵体 + 两侧进出口
  pump_h: (S, A, T, sw) => `
    <circle cx="50" cy="50" r="24" fill="none" stroke="${S}" stroke-width="${sw}"/>
    <path d="M26 50 H6 M74 50 H94" stroke="${S}" stroke-width="${sw * 2}"/>
    <path d="M50 50 m-8 0 a8 8 0 1 1 16 0" fill="none" stroke="${A}" stroke-width="${sw}"/>
    <path d="M50 26 V14" stroke="${A}" stroke-width="${sw}"/>`,

  // 潜水泵：泵体 + 水面波纹
  pump_sub: (S, A, T, sw) => `
    <rect x="34" y="34" width="32" height="46" rx="6" fill="none" stroke="${S}" stroke-width="${sw}"/>
    <circle cx="50" cy="56" r="9" fill="none" stroke="${A}" stroke-width="${sw}"/>
    <path d="M50 34 V20" stroke="${S}" stroke-width="${sw}"/>
    <path d="M8 84 q10 -7 20 0 t20 0 t20 0 t20 0" fill="none" stroke="${A}" stroke-width="${sw}" opacity=".85"/>`,

  // 闸阀：两个三角 + 阀杆 + 手轮
  valve_gate: (S, A, T, sw) => `
    <path d="M14 24 L14 76 L50 50 Z" fill="none" stroke="${S}" stroke-width="${sw}"/>
    <path d="M86 24 L86 76 L50 50 Z" fill="none" stroke="${S}" stroke-width="${sw}"/>
    <path d="M50 50 V20" stroke="${S}" stroke-width="${sw * 1.6}"/>
    <path d="M36 14 H64" stroke="${A}" stroke-width="${sw * 1.6}"/>
    <path d="M14 50 H4 M86 50 H96" stroke="${S}" stroke-width="${sw * 2}"/>`,

  // 蝶阀：圆 + 斜蝶板
  valve_butterfly: (S, A, T, sw) => `
    <circle cx="50" cy="50" r="26" fill="none" stroke="${S}" stroke-width="${sw}"/>
    <path d="M32 50 L68 50" stroke="${A}" stroke-width="${sw * 2.4}"/>
    <path d="M50 50 L50 18" stroke="${S}" stroke-width="${sw * 1.4}"/>
    <path d="M40 14 H60" stroke="${A}" stroke-width="${sw * 1.4}"/>
    <path d="M24 50 H4 M76 50 H96" stroke="${S}" stroke-width="${sw * 2}"/>`,

  // 球阀：圆 + 中间方块 + 手柄
  valve_ball: (S, A, T, sw) => `
    <circle cx="50" cy="50" r="26" fill="none" stroke="${S}" stroke-width="${sw}"/>
    <rect x="40" y="40" width="20" height="20" fill="none" stroke="${A}" stroke-width="${sw}"/>
    <path d="M50 24 V14 M40 14 H60" stroke="${S}" stroke-width="${sw * 1.3}"/>
    <path d="M24 50 H4 M76 50 H96" stroke="${S}" stroke-width="${sw * 2}"/>`,

  // 止回阀：三角 + 阀座 + 流向箭头
  valve_check: (S, A, T, sw) => `
    <path d="M24 26 L24 74 L64 50 Z" fill="none" stroke="${S}" stroke-width="${sw}"/>
    <path d="M64 26 V74" stroke="${S}" stroke-width="${sw * 1.6}"/>
    <path d="M8 50 H24 M64 50 H92" stroke="${S}" stroke-width="${sw * 2}"/>
    <path d="M74 40 L90 50 L74 60" fill="none" stroke="${A}" stroke-width="${sw * 1.2}"/>`,

  // 圆罐：柱体 + 顶盖椭圆 + 液位线
  tank_round: (S, A, T, sw) => `
    <ellipse cx="50" cy="18" rx="30" ry="9" fill="none" stroke="${S}" stroke-width="${sw}"/>
    <path d="M20 18 V80 a30 9 0 0 0 60 0 V18" fill="none" stroke="${S}" stroke-width="${sw}"/>
    <path d="M20 56 h60" stroke="${A}" stroke-width="${sw}" opacity=".7" stroke-dasharray="4 4"/>`,

  // 方池：开口矩形 + 液位线
  pool_square: (S, A, T, sw) => `
    <path d="M14 22 V84 H86 V22" fill="none" stroke="${S}" stroke-width="${sw}"/>
    <path d="M8 22 H92" stroke="${S}" stroke-width="${sw * 1.4}"/>
    <path d="M16 60 H84" stroke="${A}" stroke-width="${sw}" opacity=".7" stroke-dasharray="4 4"/>`,

  // 格栅清污机：格栅条 + 耙齿
  grill_cleaner: (S, A, T, sw) => `
    <rect x="20" y="26" width="44" height="58" fill="none" stroke="${S}" stroke-width="${sw}"/>
    <path d="M28 26 V84 M36 26 V84 M44 26 V84 M52 26 V84 M60 26 V84" stroke="${S}" stroke-width="1"/>
    <path d="M18 20 H66 M18 20 V34" stroke="${A}" stroke-width="${sw * 1.4}"/>
    <path d="M66 20 L84 12" stroke="${A}" stroke-width="${sw * 1.4}"/>`,

  // 螺旋输送机：U 型槽 + 螺旋线
  screw_conveyor: (S, A, T, sw) => `
    <path d="M10 42 V62 a40 6 0 0 0 80 0 V42" fill="none" stroke="${S}" stroke-width="${sw}"/>
    <path d="M10 42 H90" stroke="${S}" stroke-width="${sw * 1.2}"/>
    <path d="M18 52 q8 -10 16 0 t16 0 t16 0 t16 0" fill="none" stroke="${A}" stroke-width="${sw}"/>`,

  // 皮带机：皮带 + 两个滚轮 + 支架
  belt_conveyor: (S, A, T, sw) => `
    <path d="M8 56 H92" stroke="${S}" stroke-width="${sw * 2.6}"/>
    <circle cx="16" cy="56" r="7" fill="none" stroke="${A}" stroke-width="${sw}"/>
    <circle cx="84" cy="56" r="7" fill="none" stroke="${A}" stroke-width="${sw}"/>
    <path d="M16 63 V84 M84 63 V84" stroke="${S}" stroke-width="${sw}"/>
    <path d="M8 50 H92" stroke="${A}" stroke-width="1" stroke-dasharray="5 5" opacity=".8"/>`,

  // 风机：蜗壳 + 叶片
  fan: (S, A, T, sw) => `
    <circle cx="50" cy="50" r="30" fill="none" stroke="${S}" stroke-width="${sw}"/>
    <path d="M50 50 Q74 40 70 22 Q50 30 50 50 Z" fill="${A}" opacity=".8"/>
    <path d="M50 50 Q30 66 40 80 Q58 68 50 50 Z" fill="${A}" opacity=".8"/>
    <circle cx="50" cy="50" r="4" fill="${T}"/>
    <path d="M80 50 H94" stroke="${S}" stroke-width="${sw * 1.6}"/>`,

  // 电机：圆 + M
  motor: (S, A, T, sw) => `
    <circle cx="50" cy="50" r="28" fill="none" stroke="${S}" stroke-width="${sw}"/>
    <path d="M36 62 V38 l14 16 l14 -16 v24" fill="none" stroke="${A}" stroke-width="${sw * 1.4}"/>
    <path d="M50 22 V10" stroke="${S}" stroke-width="${sw}"/>`
}
