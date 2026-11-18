// 09 站点与点位管理：品牌 → 协议 → 参数组 → 默认值 → 地址格式。
// 这一份是"配置驱动"的源头：加新协议只改这个对象，不改表单代码。
// 注意：地址规则的唯一实现在后端 shared/addr.py（前端这份正则只做即时提示，
// 真校验一律以后端为准）。

export const BRANDS = [
  { v: 'siemens', label: '西门子' },
  { v: 'mitsubishi', label: '三菱' },
  { v: 'omron', label: '欧姆龙' },
  { v: 'delta', label: '台达' },
  { v: 'inovance', label: '汇川' },
  { v: 'abb', label: 'ABB' },
  { v: 'schneider', label: '施耐德' },
  { v: 'rockwell', label: '罗克韦尔' },
  { v: 'other', label: '其他' },
]

export const BRAND_LABEL = Object.fromEntries(BRANDS.map(b => [b.v, b.label]))

export const SERIES = {
  // G2 是 2024 年后新平台。rack/slot 与一代是否相同**未确证**，
  // 所以 seriesDefaults 里只给「参考值」不直接套用，避免把错的默认值写进现场。
  siemens: ['S7-200SMART', 'S7-200SMART G2', 'S7-1200', 'S7-1200 G2',
            'S7-1500', 'S7-300', 'S7-400'],
  mitsubishi: ['FX3U', 'FX5U', 'Q', 'L', 'iQ-R'],
  omron: ['CP1H', 'CJ2M', 'NJ', 'NX1P'],
  delta: ['DVP', 'AS'],
  inovance: ['AM600', 'H5U'],
  abb: ['AC500'],
  schneider: ['M221', 'M241', 'M251'],
  rockwell: ['CompactLogix', 'ControlLogix'],
  other: [],
}

// 品牌可选协议（02 任务书对照表）
export const BRAND_PROTOCOLS = {
  siemens: ['s7', 'modbus_tcp', 'opcua'],
  mitsubishi: ['mc', 'modbus_tcp'],
  omron: ['fins', 'modbus_tcp', 'opcua'],
  delta: ['modbus_tcp', 'modbus_rtu'],
  inovance: ['modbus_tcp', 'modbus_rtu'],
  abb: ['modbus_tcp', 'opcua'],
  schneider: ['modbus_tcp', 'opcua'],
  rockwell: ['cip', 'opcua'],
  other: ['modbus_tcp', 'modbus_rtu', 'opcua', 's7', 'mc', 'fins'],
}

// 协议中文全名（站点表单与设备表单共用这一份，改一处两边同时变）
export const PROTOCOL_LABEL = {
  s7: '西门子 S7', mc: '三菱 MC', fins: '欧姆龙 FINS', opcua: 'OPC UA',
  modbus_tcp: 'Modbus TCP', modbus_rtu: 'Modbus RTU', cip: 'AB CIP',
}

// 不选品牌时的全量协议（顺序即下拉顺序）
export const ALL_PROTOCOLS = [
  's7', 'mc', 'fins', 'modbus_tcp', 'modbus_rtu', 'opcua', 'cip',
].map(v => ({ v, label: PROTOCOL_LABEL[v] }))

export function protoLabel(v) {
  return PROTOCOL_LABEL[v] || v || ''
}

// 每个协议的专属参数（type: text/number/select/switch）
const P = (k, label, type, def, extra = {}) => Object.assign({ k, label, type, def }, extra)

export const PROTOCOL_SCHEMA = {
  s7: {
    port: 102,
    addrRe: '^(DB\\d+\\.DB[XBWD]\\d+(?:\\.\\d+)?|V[BWD]?\\d+(?:\\.\\d+)?|M[BWD]?\\d+(?:\\.\\d+)?|[IQ][BWD]?\\d+(?:\\.\\d+)?)$',
    addrHint: 'VD1000 / VW100 / VB0 / V1000.3 / M10.1 / IW0 / QW2 / DB1.DBW0',
    // 系列联动：槽号 / 优化块默认值（02 任务书三.：S7-1200 槽 1、S7-300 槽 2）
    seriesDefaults: {
      // S7-200 SMART 是整体式 CPU，没有机架：rack 恒 0、slot 恒 1。
      // 这两个值填错（比如 rack=1/slot=0）时 PLC 会在 102 口直接把 S7 会话
      // 重置成 "Connection reset by peer"，看着像网络问题，2026-11-09 实测。
      'S7-200SMART': { rack: 0, slot: 1, optimized_block: false },
      'S7-1200': { rack: 0, slot: 1, optimized_block: false },
      'S7-1500': { rack: 0, slot: 1, optimized_block: false },
      'S7-300': { rack: 0, slot: 2 },
      'S7-400': { rack: 0, slot: 2 },
      // ---- G2 系列：rack/slot 未确证，不自动填（填错 PLC 会直接 RST 会话）----
      // rack/slot 留 undefined → applySeries 不覆盖，TSAP 也不会被算出来，
      // 界面显示参考值让人自己填；填完 TSAP 按标准公式自动补。
      'S7-200SMART G2': {
        rack: undefined, slot: undefined, optimized_block: false,
        ref: '参考 S7-200SMART：机架 0 / 槽号 1',
      },
      'S7-1200 G2': {
        rack: undefined, slot: undefined, optimized_block: false,
        ref: '参考 S7-1200：机架 0 / 槽号 1',
      },
    },
    params: [
      P('conn_type', '连接类型', 'select', 'OP', { opts: ['OP', 'PG', 'S7basic'] }),
      // TSAP：改 rack/slot/连接类型会自动重算（见 tsapOf），也可以手改覆盖。
      // 手改后如果连不上，PLC 会直接 RST 会话 —— 这是预期行为，不做自动纠正。
      P('local_tsap', '本地 TSAP', 'combo', '0x0100', { opts: ['0x0100', '0x0101', '0x0102'] }),
      P('remote_tsap', '远程 TSAP', 'combo', '0x0201',
        { opts: ['0x0200', '0x0201', '0x0202', '0x0301', '0x0101'],
          tip: 'remote = 连接类型<<8 | rack×0x20 | slot。OP+rack0+slot1 = 0x0201' }),
      // PDU：可编辑下拉，自定义值也收；PLC 协商时取双方小的
      P('pdu_size', 'PDU 大小', 'combo', 480,
        { opts: [240, 480, 960, 1024], tip: '客户端提议值；PLC 回自己的上限，实际取小的。留空=默认 480' }),
      // 最大连接数：驱动层并发度上限。
      // S7-200 SMART 的以太网口对"编程/上位机连接"有限制（官方口径：编程软件 1 个、
      // HMI 最多 8 个），多个连接同时问同一个 CPU 会让响应错序。
      // 默认 1 = 严格串行，最稳；现场想提速可以按实际 CPU 组态调大。
      P('max_conn', '最大连接数', 'number', 1,
        { tip: '驱动层并发上限。S7-200 SMART 建议填 1（严格串行）；调大会在部分 CPU 上出现响应错序/Stale packet' }),
      P('optimized_block', '优化块访问', 'switch', false, {
        tip: 'S7-1200/1500 若在 TIA Portal 里开了"优化块访问"，必须关掉它或改用绝对地址，否则按 DB1.DBW0 这类地址读不到数据（最容易漏的一条）',
      }),
    ],
  },
  mc: {
    port: 5000,
    addrRe: '^([DMRXYSTCLFVBWZ]\\d+|W[0-9A-Fa-f]{1,3}|ZR\\d+)$',
    addrHint: 'D1018 / M100 / X10 / Y20 / W1E0 / ZR100',
    // 帧格式联动：FX3U/FX3G 挂 ENET-ADP 只认 A 兼容 1E 帧（3E 会被 ADP 静默
    // 拒绝成 0，2026-11-09 实测），选系列时必须强制刷成 1E；FX5U/Q/L/iQ-R 走 3E。
    seriesDefaults: {
      FX3U: { frame: '1E' }, FX3G: { frame: '1E' },
      FX5U: { frame: '3E' }, Q: { frame: '3E' }, L: { frame: '3E' }, 'iQ-R': { frame: '3E' },
    },
    params: [
      P('network_no', '网络号', 'number', 0),
      P('pc_no', 'PC 号', 'number', 255),
      P('module_io', '目标模块 IO 号', 'text', '03FF'),
      P('station_no', '站号', 'number', 0),
      P('max_conn', '最大连接数', 'number', 1,
        { tip: '驱动层并发上限。三菱 1E 帧是单连接一问一答，建议保持 1' }),
      P('frame', '帧格式', 'select', '3E', {
        opts: ['1E', '3E', '4E'],
        tip: 'FX3U/FX3G 用 FX3U-ENET-ADP 时只能选 1E（A 兼容 1E 帧）；'
           + 'ADP 收到 3E 帧不报错、直接把数据读成 0，这个坑踩过。'
           + 'Q/L/iQ-R 内置以太网走 3E，需要 UDP/多站才用 4E。',
      }),
    ],
  },
  fins: {
    port: 9600,
    addrRe: '^([DCWATE]\\d+|CIO\\d+)$',
    addrHint: 'D100 / CIO10 / W20 / A100',
    params: [
      P('network_no', '网络号', 'number', 0),
      P('node_no', '节点号', 'number', 1),
      P('unit_no', '单元号', 'number', 0),
      P('mem_area', '内存区', 'select', 'D', { opts: ['D', 'CIO', 'W', 'H', 'A'] }),
    ],
  },
  modbus_tcp: {
    port: 502,
    addrRe: '^(\\d+|[34]\\d{4}|HR\\d+)$',
    addrHint: 'HR8 / 十进制偏移 8 / 40001 式',
    params: [
      P('unit_id', '单元号', 'number', 1),
      P('func_read', '读功能码', 'select', '03', { opts: ['03', '04'] }),
      P('func_write', '写功能码', 'select', '06', { opts: ['06', '16'] }),
      P('reg_base', '寄存器基址', 'select', 0, {
        opts: [{ v: 0, label: '0（40001 对应偏移 0，多数设备）' }, { v: 1, label: '1（40001 对应偏移 1）' }],
        tip: '现场最容易搞反：0 表示 40001 即偏移 0；读出来全是错位数据就先翻这个开关',
      }),
      P('max_regs', '单次最大寄存器数', 'number', 120),
      P('byte_order', '字节序', 'select', 'CDAB', { opts: ['ABCD', 'CDAB', 'BADC', 'DCBA'] }),
    ],
  },
  modbus_rtu: {
    port: 502,
    addrRe: '^(\\d+|[34]\\d{4}|HR\\d+)$',
    addrHint: 'HR8 / 十进制偏移 8 / 40001 式',
    params: [
      P('unit_id', '单元号', 'number', 1),
      P('func_read', '读功能码', 'select', '03', { opts: ['03', '04'] }),
      P('func_write', '写功能码', 'select', '06', { opts: ['06', '16'] }),
      P('reg_base', '寄存器基址', 'select', 0, {
        opts: [{ v: 0, label: '0（40001 对应偏移 0，多数设备）' }, { v: 1, label: '1（40001 对应偏移 1）' }],
        tip: '现场最容易搞反：0 表示 40001 即偏移 0',
      }),
      P('max_regs', '单次最大寄存器数', 'number', 120),
      P('byte_order', '字节序', 'select', 'CDAB', { opts: ['ABCD', 'CDAB', 'BADC', 'DCBA'] }),
    ],
  },
  opcua: {
    port: 4840,
    addrRe: '^ns=\\d+;[isgb]=.+$',
    addrHint: 'ns=2;s=Tank.Level',
    params: [
      P('endpoint', 'Endpoint', 'text', '', { ph: 'opc.tcp://192.168.1.10:4840' }),
      P('security_policy', '安全策略', 'select', 'None', { opts: ['None', 'Basic256Sha256'] }),
      P('security_mode', '安全模式', 'select', 'None', { opts: ['None', 'Sign', 'SignAndEncrypt'] }),
      P('auth', '认证方式', 'select', 'anonymous', { opts: ['anonymous', 'username'] }),
      P('username', '用户名', 'text', ''),
      P('nodeid_prefix', 'NodeId 前缀', 'text', 'ns=2;s='),
    ],
  },
  cip: {
    port: 44818,
    addrRe: null,
    addrHint: 'Tag 名，如 Tank_Level',
    params: [],
  },
}

export function protocolsOf(brand) {
  return (BRAND_PROTOCOLS[brand] || []).map(p => ({ v: p, label: PROTOCOL_LABEL[p] || p }))
}

// 选品牌后：协议联动 + 默认端口
export function applyBrand(form) {
  const ps = protocolsOf(form.brand)
  if (ps.length && !ps.find(x => x.v === form.protocol)) {
    form.protocol = ps[0].v
    // 端口必须在这里强制刷：el-input-number 的 :min 会把初始 0 钳成 1，
    // applyProtocol 里"port 为 0 才填默认"就会看到 1 当成已填过（实测踩过）
    form.port = PROTOCOL_SCHEMA[form.protocol]?.port || form.port
    applyProtocol(form)
  }
  return ps
}

// 选协议后：默认端口 + 参数组默认值（保留用户已改过的值）
export function applyProtocol(form) {
  const sc = PROTOCOL_SCHEMA[form.protocol]
  if (!sc) return []
  if (!form.port) form.port = sc.port
  const pp = form.proto_params || (form.proto_params = {})
  for (const f of sc.params) {
    if (pp[f.k] === undefined || pp[f.k] === '') pp[f.k] = f.def
  }
  return sc.params
}

// 选系列后（S7：槽号 / 优化块；MC：帧格式——FX3U 必须是 1E，见 mc.seriesDefaults）
// —— S7 TSAP ——
// S7comm / COTP 标准：remote TSAP = 连接类型<<8 | rack×0x20 | slot
//   PG(1)=0x0100  OP(2)=0x0200  S7basic(3)=0x0300，再 + rack*32 + slot
// 这就是 snap7 内部 connect() 干的事（client.py:451），我们把它显式化，
// 才能让人看到、也能手改（手改会真生效，见 gateway/s7_200smart.py）。
const CONN_TYPE_CODE = { PG: 1, OP: 2, S7BASIC: 3, BASIC: 3, S7_BASIC: 3, '': 2 }

export function tsapOf(connType, rack, slot) {
  const t = CONN_TYPE_CODE[String(connType == null ? '' : connType).toUpperCase()]
  // 注意 Number(null) === 0、Number('') === 0 —— 必须先判"没填"，否则
  // G2 这种 rack/slot 留空的型号会被算成 rack0/slot0，看似"自动填好了"其实是错的。
  const blank = (v) => v === null || v === undefined || v === ''
  if (blank(rack) || blank(slot)) return null
  const r = Number(rack)
  const s = Number(slot)
  // slot 没填（G2 等未知型号）→ 返回 null，不猜。
  // 猜错的代价是 PLC 在 102 口直接 RST 会话，现场会当成网络故障排查半天。
  if (!Number.isFinite(r) || r < 0) return null
  if (!Number.isFinite(s) || s < 0) return null
  return {
    local: 0x0100,
    remote: ((t === undefined ? 2 : t) << 8) | (r << 5) | s,
  }
}

export function fmtTsap(n) {
  return '0x' + Number(n).toString(16).toUpperCase().padStart(4, '0')
}

/** 把算出来的 TSAP 写进 proto_params（算不出来就不动，保留用户手填的值） */
export function applyTsap(form) {
  if (!form || !form.proto_params) return
  const v = tsapOf(form.proto_params.conn_type, form.rack, form.slot)
  if (!v) return
  form.proto_params.local_tsap = fmtTsap(v.local)
  form.proto_params.remote_tsap = fmtTsap(v.remote)
}

/** TSAP 下拉的建议值：当前 rack/slot 下三种连接类型各一个 */
export function tsapSuggestions(rack, slot) {
  const out = []
  for (const t of ['PG', 'OP', 'S7basic']) {
    const v = tsapOf(t, rack, slot)
    if (v) out.push(fmtTsap(v.remote))
  }
  return [...new Set(out)]
}

export function applySeries(form) {
  const sc = PROTOCOL_SCHEMA[form.protocol]
  if (!sc || !sc.seriesDefaults) return
  const d = sc.seriesDefaults[form.series]
  if (!d) return
  if (d.rack !== undefined) form.rack = d.rack
  if (d.slot !== undefined) form.slot = d.slot
  // G2 这类「未确证」型号（带 ref 但没有 rack/slot）：明确清空，别让表单里的默认 0/1
  // 冒充成这个型号的正确答案。清空后 tsapOf 返回 null，TSAP 也保持空 —— 由现场填。
  if (d.ref && d.rack === undefined && d.slot === undefined) {
    form.rack = null
    form.slot = null
  }
  if (d.optimized_block !== undefined) form.proto_params.optimized_block = d.optimized_block
  // 帧格式要强制刷而不是"没填才填"：FX3U 带着 3E 存进库，现场读出来全是 0，
  // 而且网关会判成"平台通了但数据是 0"，最难查的一类故障
  if (d.frame !== undefined) form.proto_params.frame = d.frame
  // rack/slot 定下来后，TSAP 按标准公式补上（G2 因为 slot 是空，这里不会动）
  applyTsap(form)
}
