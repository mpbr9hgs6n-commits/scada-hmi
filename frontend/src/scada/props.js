// 组态对象属性表（P3）—— 面板与渲染器共用同一份定义
//
// 三条设计约定：
// 1) 每个字段带 dyn 标记：该属性「能不能被动态化」。
//    WinCC 4.8.4.2：Some attributes cannot be made dynamic because a change has no
//    effect in runtime. These attributes have no dynamics icon.
//    P4 接动态化时直接读这个标记决定是否显示动态化入口，避免用户点了没反应。
// 2) 按类型分支（family）组织字段，不做万能表单。每个 family 只列该类型真正有意义的属性。
// 3) 默认值只有这一份：面板显示它、渲染器取它，保证「面板上的颜色」与「画布上的颜色」一致。

export const TYPE_CN = {
  tank: '液位罐', pump: '水泵', pump_v: '立式泵', pump_h: '卧式泵', valve: '阀门', pipe: '管道',
  pipe_v: '垂直管道', pipe_t: 'T 形管道', pipe_elbow: '弯头', fan: '风机', grill: '格栅',
  conveyor: '皮带输送机', value: 'I/O 域', input: '数值输入', button: '按钮', lamp: '指示灯',
  text: '静态文本', line: '线', polyline: '折线', polygon: '多边形', rect: '矩形',
  circle: '圆', ellipse: '椭圆', arc: '圆弧', video: '视频窗', alarm_list: '报警窗',
  trend: '趋势', table: '表格', xy: 'X-Y 曲线', gauge: '仪表盘', clock: '时钟',
  image: '图片', symbol: '符号库', group: '组合', faceplate: '组件模板',
  // 提示词 11：scada-deck 大屏组件
  kpi: 'KPI 卡', progress: '进度条', ring: '环形进度', statusbadge: '状态徽章', panel: '面板卡'
}
export const typeLabel = (t) => TYPE_CN[t] || t

// 控件中文名（用于自动命名「趋势曲线1」「报警窗2」）
const CONTROL_CN = {
  alarm: '报警窗', trend: '趋势曲线', table: '数据表格', xyTrend: 'X-Y曲线',
  gauge: '仪表盘', clock: '时钟', video: '视频窗', symbolLib: '符号库'
}

// 页签顺序固定（与 WinCC 一致：属性在前、事件在后）
export const TABS = [
  { key: 'geom', label: '几何' },
  { key: 'look', label: '外观' },
  { key: 'font', label: '字体' },
  // I/O 域专用（WinCC: Object Properties → Input/Output）
  { key: 'io', label: '输入输出' },
  { key: 'dyn', label: '动态化' },
  { key: 'event', label: '事件' }
]

// —— 字段定义 ——
// type: num 数值 / color 颜色 / select 下拉 / bool 开关 / text 文本 / image 上传
// key: 极少数字段用别的键名写入（如「粗细」写的其实是 h）
export const FIELDS = {
  x: { label: 'X', type: 'num', min: -4000, max: 8000, step: 1, unit: 'px', dyn: true },
  y: { label: 'Y', type: 'num', min: -4000, max: 8000, step: 1, unit: 'px', dyn: true },
  w: { label: '宽 W', type: 'num', min: 1, max: 8000, step: 1, unit: 'px', dyn: true },
  h: { label: '高 H', type: 'num', min: 1, max: 8000, step: 1, unit: 'px', dyn: true },
  rot: { label: '旋转角度', type: 'num', min: -360, max: 360, step: 1, unit: '°', dyn: true },

  fillMode: {
    label: '填充模式', type: 'select', dyn: true,
    options: [{ v: 'solid', t: '实心' }, { v: 'none', t: '无' }]
  },
  fill: { label: '填充色', type: 'color', dyn: true },
  // 视频窗：下拉选哪一路（选项由 PropPanel 从 /api/video/channels 注入）
  ch: {
    label: '视频通道', type: 'select', dyn: false,
    optionsFrom: 'channels',
    help: '下拉选这个窗口显示哪一路；留空则自动取第一路可播通道'
  },
  // 码流：主/辅。现场经常出现"主码流还是 H.265、子码流已经改成 H.264"，
  // 这时必须能切子码流，否则这个窗口永远黑屏。
  chStream: {
    label: '码流', type: 'select', dyn: false,
    options: [{ v: 'main', t: '主码流（高清）' }, { v: 'sub', t: '子码流（流畅）' }],
    help: '主码流播不出来时切子码流试试。属性页下方会显示当前实际连的流和能不能播。'
  },
  // 手动流名：下拉里没有的通道（camera 未登记 / 跨站点取流 / 测试流）
  chManual: {
    label: '手动流名', type: 'text', dyn: false,
    placeholder: '如 S001-4；填了就优先用它',
    help: '填了就以它为准，即使 camera 表里没有这个通道。'
  },
  // 14 号：按钮点击跳转到哪张画面（选项由 PropPanel 从 /api/pages?kind=scada 注入）
  targetPage: {
    label: '跳转画面', type: 'select', dyn: false,
    optionsFrom: 'pages',
    help: '点击按钮切换到这张画面；留空则不跳转（走原来的写 PLC 事件）'
  },
  liquidColor: { label: '液体色', type: 'color', dyn: true },
  direction: {
    label: '液位方向', type: 'select', dyn: true,
    options: [{ v: 'up', t: '由下向上' }, { v: 'down', t: '由上向下' }]
  },
  colorIdle: { label: '静止色', type: 'color', dyn: true },
  colorRun: { label: '运行色', type: 'color', dyn: true },
  spin: { label: '运行时旋转', type: 'bool', dyn: true },
  stroke: { label: '边框色', type: 'color', dyn: true },
  strokeWidth: { label: '边框宽', type: 'num', min: 0, max: 20, step: 1, unit: 'px', dyn: true },
  lineStyle: {
    label: '线型', type: 'select', dyn: true,
    options: [
      { v: 'solid', t: '实线' }, { v: 'dash', t: '虚线' },
      { v: 'dot', t: '点线' }, { v: 'dashdot', t: '点划线' }
    ]
  },
  radius: { label: '圆角', type: 'num', min: 0, max: 200, step: 1, unit: 'px', dyn: true },
  opacity: { label: '不透明度', type: 'num', min: 0, max: 100, step: 1, unit: '%', dyn: true },
  // 背景图是 URL，运行时换图没意义（且要重新请求），官方也没有这个动态化
  bgImage: { label: '背景图', type: 'image', dyn: false },
  // P8 图片对象的图片地址：可被「图形列表」动态化接管（官方 4.7.2）
  // 图片对象：走上传控件（后端 /api/upload，存 /data/uploads），不再是手填地址
  src: { label: '图片', type: 'image', dyn: true },
  flow: { label: '流动动画', type: 'bool', dyn: true },
  thickness: { label: '粗细', type: 'num', key: 'h', min: 2, max: 160, step: 1, unit: 'px', dyn: true },

  fontFamily: {
    label: '字体族', type: 'select', dyn: false,
    options: [
      { v: '', t: '系统默认' },
      { v: '"Microsoft YaHei",sans-serif', t: '微软雅黑' },
      { v: 'SimSun,serif', t: '宋体' },
      { v: 'SimHei,sans-serif', t: '黑体' },
      { v: 'Consolas,monospace', t: 'Consolas' }
    ]
  },
  fontSize: { label: '字号', type: 'num', min: 6, max: 240, step: 1, unit: 'px', dyn: true },
  bold: { label: '粗体', type: 'bool', dyn: true },
  italic: { label: '斜体', type: 'bool', dyn: true },
  color: { label: '文字颜色', type: 'color', dyn: true },
  align: {
    label: '水平对齐', type: 'select', dyn: true,
    options: [{ v: 'left', t: '左' }, { v: 'center', t: '中' }, { v: 'right', t: '右' }]
  },
  valign: {
    label: '垂直对齐', type: 'select', dyn: true,
    options: [{ v: 'top', t: '上' }, { v: 'middle', t: '中' }, { v: 'bottom', t: '下' }]
  },
  decimals: { label: '小数位', type: 'num', min: 0, max: 6, step: 1, unit: '位', dyn: true },
  unit: { label: '单位', type: 'text', maxLen: 12, dyn: true },

  // —— I/O 域输入输出（修复 09）——
  // dyn:false：这些是"怎么显示/怎么提交"的元配置，动态化它们没有运行语义
  // （官方 WinCC 里也只有值本身能动态化，Type 是静态属性）
  mode: {
    label: '类型', type: 'select', dyn: false,
    options: [
      { v: 'output', t: '仅输出（只显示）' },
      { v: 'input', t: '仅输入（显示可键入）' },
      { v: 'inputoutput', t: '输入输出（显示实时值，可改）' }
    ]
  },
  submitBy: {
    label: '提交方式', type: 'select', dyn: false,
    options: [{ v: 'enter', t: '回车' }, { v: 'blur', t: '失焦' }, { v: 'both', t: '回车或失焦' }]
  },
  // nullable: 空 = 不限（WinCC 的 Limiting values 也是可留空）
  inputMin: { label: '输入下限', type: 'num', nullable: true, min: -9999999, max: 9999999, step: 1, dyn: false },
  inputMax: { label: '输入上限', type: 'num', nullable: true, min: -9999999, max: 9999999, step: 1, dyn: false },
  showUnit: { label: '输入时显示单位', type: 'bool', dyn: false },
  confirmWrite: { label: '写入前二次确认', type: 'bool', dyn: false },

  // —— 提示词 11：scada-deck 图库字段 ——
  // 显示文字（KPI 卡标签 / 徽章文字 / 面板标题）
  text: { label: '显示文字', type: 'text', maxLen: 32, dyn: true },
  // 量程（罐/进度条/环形）：液位百分比与进度都按它折算
  min: { label: '量程下限', type: 'num', dyn: true },
  max: { label: '量程上限', type: 'num', dyn: true },
  // 介质（原则 3）：罐/管道的液体颜色从枚举取，不手填色值
  medium: {
    label: '介质', type: 'select', dyn: true,
    options: [
      { v: '', t: '（自定义液体色）' },
      { v: 'influent', t: '进水（浑浊灰黄绿）' },
      { v: 'effluent', t: '出水（清澈蓝）' },
      { v: 'sludge', t: '污泥（褐）' },
      { v: 'chemical', t: '药剂（淡紫）' },
      { v: 'clean', t: '清水' },
      { v: 'air', t: '空气' },
      { v: 'steam', t: '蒸汽' },
      { v: 'gas', t: '沼气' }
    ]
  },
  showScale: { label: '显示液位标尺', type: 'bool', dyn: false },
  // 设备状态值（渲染约定：runValue=运行 faultValue=故障 其余=停止；valve openValue=开）
  runValue: { label: '运行值', type: 'num', dyn: false },
  faultValue: { label: '故障值', type: 'num', dyn: false },
  openValue: { label: '开阀值', type: 'num', dyn: false },
  onValue: { label: '点亮值', type: 'num', dyn: false },
  // 大屏组件文本
  accentColor: { label: '强调色', type: 'color', dyn: true },
  goodText: { label: '正常时文字', type: 'text', maxLen: 16, dyn: false },
  badText: { label: '无数据时文字', type: 'text', maxLen: 16, dyn: false }
}

// —— 类型分组 ——
const FAMILY = {
  tank: 'tank',
  pump: 'pump', pump_v: 'pump', pump_h: 'pump',
  valve: 'valve', fan: 'machine', grill: 'machine', conveyor: 'machine',
  pipe: 'pipe', pipe_v: 'pipe',
  pipe_t: 'locked', pipe_elbow: 'locked',
  value: 'value', input: 'value',
  button: 'button',
  lamp: 'lamp',
  text: 'text',
  rect: 'fill', circle: 'fill', polygon: 'fill', ellipse: 'fill',
  line: 'stroke', polyline: 'stroke', arc: 'stroke',
  video: 'video', image: 'imgx',
  alarm_list: 'datalist', table: 'datalist',
  control: 'ctrl',
  trend: 'chart', xy: 'chart', gauge: 'chart', clock: 'chart',
  symbol: 'symbol',
  group: 'grp',
  faceplate: 'fpt',
  // 提示词 11：scada-deck 大屏组件
  kpi: 'deck', progress: 'deck', ring: 'deck', statusbadge: 'deck', panel: 'deck'
}
export const familyOf = (t) => FAMILY[t] || 'symbol'

// 分组：sec = 面板上的小标题，fields = 该组字段
const G_POS = { sec: '位置与大小', fields: ['x', 'y', 'w', 'h', 'rot'] }
const G_FILL = { sec: '填充', fields: ['fill', 'fillMode'] }
const G_BORDER = { sec: '边框', fields: ['stroke', 'strokeWidth', 'lineStyle', 'radius'] }
const G_MISC = { sec: '其他', fields: ['opacity', 'bgImage'] }
const G_LINE = { sec: '线条', fields: ['stroke', 'strokeWidth', 'lineStyle'] }
const G_STYLE = { sec: '外观', fields: ['fill', 'stroke', 'strokeWidth', 'lineStyle', 'radius'] }

// 字体页签：FONT_ALL 用于数值类（带小数位/单位），FONT_TXT 用于纯文本类
const FONT_TXT = {
  sec: '文本',
  fields: ['fontFamily', 'fontSize', 'bold', 'italic', 'color', 'align', 'valign']
}
const FONT_ALL = {
  sec: '文本',
  fields: ['fontFamily', 'fontSize', 'bold', 'italic', 'color', 'align', 'valign', 'decimals', 'unit']
}

// 每个 family 的页签与字段。没有 font 的 family 就是不显示字体页签（如管道）。
const SCHEMA = {
  // font 用 FONT_ALL：标准对象现在也能「显示数值」，必须有小数位和单位
  fill: { tabs: ['geom', 'look', 'font', 'dyn', 'event'], look: [G_FILL, G_BORDER, G_MISC], font: [FONT_ALL] },
  // 线段类原来没有字体页签；既然要能显示数值，字号/颜色/小数位/单位都得能配
  stroke: { tabs: ['geom', 'look', 'font', 'dyn', 'event'],
            look: [G_LINE, { sec: '其他', fields: ['opacity'] }],
            font: [FONT_ALL] },
  text: { tabs: ['geom', 'look', 'font', 'dyn', 'event'], look: [G_FILL, G_BORDER, G_MISC], font: [FONT_ALL] },
  tank: {
    tabs: ['geom', 'look', 'font', 'dyn', 'event'],
    look: [
      { sec: '罐体', fields: ['fill', 'stroke', 'strokeWidth', 'lineStyle', 'radius'] },
      { sec: '液体', fields: ['medium', 'liquidColor', 'direction'] },
      { sec: '量程与标尺', fields: ['min', 'max', 'showScale'] },
      G_MISC
    ],
    font: [FONT_ALL]
  },
  pump: {
    tabs: ['geom', 'look', 'dyn', 'event'],
    look: [
      { sec: '颜色', fields: ['colorIdle', 'colorRun', 'spin'] },
      { sec: '状态值', fields: ['runValue', 'faultValue'] },
      { sec: '其他', fields: ['opacity'] }
    ]
  },
  machine: {
    tabs: ['geom', 'look', 'dyn', 'event'],
    look: [
      G_STYLE,
      { sec: '状态值', fields: ['runValue', 'faultValue'] },
      { sec: '其他', fields: ['opacity'] }
    ]
  },
  valve: {
    tabs: ['geom', 'look', 'dyn', 'event'],
    look: [G_STYLE, { sec: '阀状态', fields: ['openValue'] }, { sec: '其他', fields: ['opacity'] }]
  },
  // 管道：没有字体页签（官方 Pipe 没有文本属性）；
  // 也不放背景图——管道的底色由流动动画接管，加背景图只会互相打架
  pipe: {
    tabs: ['geom', 'look', 'dyn', 'event'],
    look: [
      { sec: '管线', fields: ['fill', 'medium', 'thickness', 'flow'] },
      { sec: '其他', fields: ['opacity'] }
    ]
  },
  // T 形管/弯头：尺寸由图形决定，只有几何，且只读
  locked: { tabs: ['geom'], readonly: true },
  value: {
    // 页签顺序照 WinCC：几何/外观/字体/输入输出/动态化/事件
    tabs: ['geom', 'look', 'font', 'io', 'dyn', 'event'],
    look: [{ sec: '填充', fields: ['fill', 'stroke', 'strokeWidth', 'radius'] }, G_MISC],
    font: [FONT_ALL],
    io: [
      { sec: '类型', fields: ['mode', 'submitBy', 'showUnit', 'confirmWrite'] },
      { sec: '输入范围', fields: ['inputMin', 'inputMax'] }
    ]
  },
  // 按钮：靠事件动作，不靠动态化 —— 有事件页签、没有动态化页签
  button: {
    tabs: ['geom', 'look', 'font', 'event'],
    look: [
      { sec: '按钮', fields: ['targetPage'] },
      { sec: '填充', fields: ['fill', 'stroke', 'strokeWidth', 'radius'] },
      { sec: '其他', fields: ['opacity'] }
    ],
    font: [FONT_TXT]
  },
  lamp: {
    tabs: ['geom', 'look', 'dyn', 'event'],
    look: [
      { sec: '颜色', fields: ['colorIdle', 'colorRun'] },
      { sec: '点亮条件', fields: ['onValue'] },
      { sec: '其他', fields: ['opacity'] }
    ]
  },
  video: {
    tabs: ['geom', 'look', 'dyn', 'event'],
    look: [{ sec: '视频', fields: ['ch', 'chStream', 'chManual'] },
           { sec: '文字', fields: ['text'] },
           { sec: '边框', fields: ['stroke', 'strokeWidth', 'radius'] },
           { sec: '其他', fields: ['opacity'] }]
  },
  // P8 图片对象：只管图片地址（图形列表绑的就是它）
  imgx: {
    tabs: ['geom', 'look', 'dyn', 'event'],
    look: [{ sec: '图片', fields: ['src'] }, { sec: '边框', fields: ['stroke', 'strokeWidth', 'radius'] },
           { sec: '其他', fields: ['opacity'] }]
  },
  datalist: {
    tabs: ['geom', 'look', 'font', 'dyn', 'event'],
    look: [{ sec: '填充', fields: ['fill', 'stroke', 'strokeWidth', 'radius'] }, { sec: '其他', fields: ['opacity'] }],
    font: [FONT_TXT]
  },
  chart: {
    tabs: ['geom', 'look', 'dyn', 'event'],
    look: [{ sec: '外观', fields: ['fill', 'stroke', 'strokeWidth'] }, { sec: '其他', fields: ['opacity'] }]
  },
  symbol: {
    tabs: ['geom', 'look', 'dyn', 'event'],
    look: [{ sec: '外观', fields: ['fill', 'stroke', 'strokeWidth'] }, { sec: '其他', fields: ['opacity'] }]
  },
  // 控件：配置项太多，走双击配置对话框；属性面板只管几何与外观
  // （控件自身的数据由控件管，所以没有「动态化」页签）
  ctrl: {
    tabs: ['geom', 'look', 'event'],
    look: [{ sec: '外观', fields: ['fill', 'stroke', 'strokeWidth', 'radius'] }, { sec: '其他', fields: ['opacity'] }]
  },
  // P7 组合：只能改几何（整组移动/缩放），外观由子对象各自决定
  grp: {
    tabs: ['geom'],
    look: [{ sec: '其他', fields: ['opacity'] }]
  },
  // P8 组件模板实例：几何 + 接口变量绑定（绑定表在 PropPanel 里单独画，不走字段表）
  fpt: {
    tabs: ['geom'],
    look: [{ sec: '其他', fields: ['opacity'] }]
  },
  // 提示词 11：scada-deck 大屏组件（外观自带，只配内容与量程）
  deck: {
    tabs: ['geom', 'look', 'font', 'dyn', 'event'],
    look: [
      { sec: '内容', fields: ['text', 'accentColor'] },
      { sec: '量程', fields: ['min', 'max'] },
      { sec: '状态文字', fields: ['goodText', 'badText'] },
      G_MISC
    ],
    font: [FONT_ALL]
  }
}

export function schemaOf(type) {
  const f = familyOf(type)
  return SCHEMA[f] || SCHEMA.symbol
}

// 取某页签的分组（几何页签统一用 G_POS，但只读 family 要标记出来）
export function groupsOf(type, tab) {
  const sc = schemaOf(type)
  if (tab === 'geom') return [G_POS]
  if (tab === 'font') return sc.font || []
  // 少了这一行，点「输入输出」会落到下面的 sc.look，
  // 结果 I/O 域的类型/提交方式/输入范围全被外观字段顶掉，用户配不了仅输出/输入输出。
  if (tab === 'io') return sc.io || []
  return sc.look || []
}

// 多选：所有选中类型的页签交集与字段交集
// 老画面判定：item.var 没有站点前缀（P1 的旧格式），运行时要靠"当前站点"兜底才能取值
export function isLegacyVar(it) {
  // 只有「字符串形式」的 var 才算旧格式。
  //   新格式：{ site:'S001', point:'V300OUT' }  ← 对象，永远不是旧格式
  //   旧格式：'S001' / 'LEVEL' / '${S001.LEVEL}' 这类裸字符串
  //
  // 原先的实现是 `!String(it.var).includes('.')`，对对象取 String 得到 "[object Object]"，
  // 里面没有点号 → 所有对象都被误判成"旧格式"，属性面板弹出红条要求重选点位。
  if (!it || !it.var) return false
  if (typeof it.var === 'object') return false      // 对象 = 新格式，直接放行
  const s = String(it.var).trim()
  if (!s) return false
  return !s.includes('.')                            // 字符串里没有 "站点.点位" 的分隔点
}

export function sharedSchema(types) {
  const list = [...new Set(types)]
  if (!list.length) return { tabs: [], groups: {}, readonly: false }
  const schemas = list.map(schemaOf)
  let tabs = schemas[0].tabs.slice()
  for (const s of schemas.slice(1)) tabs = tabs.filter(t => s.tabs.includes(t))

  const groups = {}
  for (const tab of ['geom', 'look', 'font', 'io']) {
    if (!tabs.includes(tab)) continue
    const per = list.map(t => groupsOf(t, tab))
    // 以第一个类型的分组顺序为基准，逐个字段与其他类型求交集
    const out = []
    for (const g of per[0]) {
      const fields = g.fields.filter(k => per.slice(1).every(gs => gs.some(x => x.fields.includes(k))))
      if (fields.length) out.push({ sec: g.sec, fields })
    }
    groups[tab] = out
  }
  // 所有选中类型都只读时，几何才只读
  const readonly = schemas.every(s => s.readonly)
  return { tabs: TABS.filter(t => tabs.includes(t.key)).map(t => t.key), groups, readonly }
}

// —— 默认值：面板显示与渲染器取用同一份 ——
const COMMON_DEF = {
  rot: 0, opacity: 100, fillMode: 'solid', lineStyle: 'solid',
  fontFamily: '', bold: false, italic: false, align: 'left', valign: 'middle', decimals: 2
}

const FAM_DEF = {
  // decimals/unit：标准对象现在能「显示数值」，字体页签配的小数位和单位要有默认值，
  // 否则新建对象时这两个字段是 undefined，fmtNum 里要走 ?? 兜底，属性面板也显示空。
  fill: { fill: '#0e1f33', stroke: '#1e3a5f', strokeWidth: 1, radius: 0, color: '#e2e8f0', fontSize: 14, decimals: 2, unit: '' },
  stroke: { stroke: '#7cc4ff', strokeWidth: 2, color: '#7cc4ff', fontSize: 14, decimals: 2, unit: '' },
  text: { fill: '#0e1f33', fillMode: 'none', stroke: '#1e3a5f', strokeWidth: 0, radius: 0, color: '#e2e8f0', fontSize: 16, decimals: 2, unit: '' },
  tank: {
    fill: '#12263f', stroke: '#2c4a6e', strokeWidth: 2, radius: 6,
    liquidColor: '#1ec8ff', direction: 'up', color: '#ffffff', fontSize: 13,
    min: 0, max: 100, showScale: false, medium: ''
  },
  pump: { colorIdle: '#64748b', colorRun: '#22c55e', spin: true, stroke: '#475569', runValue: 1, faultValue: 2 },
  valve: { fill: '#1ec8ff', stroke: '#2c4a6e', strokeWidth: 2, radius: 0 },
  pipe: { fill: '#1b3a5c', strokeWidth: 2, flow: true },
  locked: {},
  value: {
    fill: '#0e1f33', stroke: '#1e3a5f', strokeWidth: 1, radius: 4,
    color: '#e2e8f0', fontSize: 0, align: 'center', valign: 'middle', decimals: 2, unit: ''
  },
  button: {
    fill: '#1d4ed8', stroke: '#1e3a5f', strokeWidth: 0, radius: 6,
    color: '#ffffff', fontSize: 14, align: 'center', valign: 'middle'
  },
  lamp: { colorIdle: '#334155', colorRun: '#22c55e', onValue: 1 },
  machine: { fill: '#0e1f33', stroke: '#2c4a6e', strokeWidth: 2, radius: 0, runValue: 1, faultValue: 2 },
  valve: { fill: '#1ec8ff', stroke: '#2c4a6e', strokeWidth: 2, radius: 0, openValue: 1 },
  pipe: { fill: '#1b3a5c', strokeWidth: 2, flow: true },
  deck: {
    fill: 'transparent', fillMode: 'none', stroke: '', strokeWidth: 0,
    color: '#f0f5fa', fontSize: 14, decimals: 2, unit: '',
    min: 0, max: 100, text: '', goodText: '', badText: ''
  },
  video: { stroke: '#1e3a5f', strokeWidth: 1, radius: 4 },
  imgx: { stroke: '#1e3a5f', strokeWidth: 1, radius: 2 },
  datalist: { fill: '#0e1f33', stroke: '#1e3a5f', strokeWidth: 1, radius: 4, color: '#9fc3e8', fontSize: 13 },
  chart: { fill: '#0e1f33', stroke: '#2c4a6e', strokeWidth: 1.5, radius: 0 },
  symbol: { fill: '#1ec8ff', stroke: '#2c4a6e', strokeWidth: 2 },
  // P6 控件：外观只给边框/底色（内部由控件自己画），默认细边框不抢眼
  ctrl: { fill: '#0b1622', stroke: '#1e3a5f', strokeWidth: 1, radius: 3 },
  // P7 组合：没有自己的外观
  grp: {},
  // P8 组件模板实例：外观全在模板里
  fpt: {}
}

export function defaultsOf(type) {
  return Object.assign({}, COMMON_DEF, FAM_DEF[familyOf(type)] || {})
}

// 取「有效值」：对象自己写过的优先，否则用该类型默认值
export function effOf(item, key) {
  const v = item[key]
  if (v === undefined || v === null || v === '') {
    if (key === 'unit') return ''      // 单位空是合法值，不能回落到默认
    return defaultsOf(item.type)[key]
  }
  return v
}

// —— 对象命名 ——
// 官方要求：同一画面内对象名唯一，且不能只靠大小写区分 → 比较前统一转小写
export function isNameTaken(name, items, exclude) {
  const n = String(name || '').trim().toLowerCase()
  if (!n) return false
  return items.some(o => o !== exclude && String(o.name || '').trim().toLowerCase() === n)
}

export function defaultName(type, items, exclude, labelOverride) {
  const label = labelOverride || typeLabel(type)
  // 从 1 开始找第一个没被占用的号。
  // 不能按「同类型已有几个 + 1」算：那样一页两个罐会变成 液位罐2 / 液位罐3，第一个号永远空着。
  let n = 1
  while (isNameTaken(label + n, items, exclude)) n++
  return label + n
}

// 老画面没有 name 字段：按类型编号补齐（只在内存里补，保存时随 json 落库）
export function ensureNames(items) {
  for (const it of items) {
    if (!it.name) {
      const lb = it.type === 'control' ? (CONTROL_CN[it.control] || '控件') : ''
      it.name = defaultName(it.type, items, it, lb)
    }
  }
}
