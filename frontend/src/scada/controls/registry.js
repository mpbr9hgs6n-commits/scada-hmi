import { tagText } from '../varbind'
// 控件注册表（P6）——照 WinCC 4.9.2 的 8 件套
//
// 一个控件在画面 json 里的形态：
//   { "type":"control", "control":"trend", "x":100,"y":80,"w":500,"h":300,
//     "props": {...控件专属配置...}, "style": {...} }
//
// 为什么 type 与 control 两级：P1~P5 的老画面有 type='trend'/'video' 之类的
// 简易实现，不能一刀切掉。type='control' 才走 P6 的真控件；老 type 继续走
// render.js 的老分支，画面照常打开。
//
// 所有控件组件都只认 mode: 'edit' | 'runtime'（env.mode），
// 不许出现 TrendControlEdit.vue + TrendControlView.vue 两份渲染代码。

export const CONTROL_TYPES = {
  alarm: {
    name: '报警窗', group: '数据', minW: 320, minH: 200, w: 520, h: 260,
    icon: 'alarmico',
    tip: '报警窗（SSE 实时，行内确认/关闭）',
    props: () => ({
      title: '实时报警', source: 'current', maxRows: 20,
      onlyUnacked: false, blinkNew: true, autoScroll: true,
      timeSpan: '24h', customMinutes: 1440, allowRange: true,
      vars: [],
      columns: ['time', 'site', 'point', 'msg', 'level', 'state', 'count']
    })
  },
  trend: {
    name: '趋势曲线', group: '数据', minW: 400, minH: 240, w: 520, h: 260,
    icon: 'trendico',
    tip: '趋势曲线（历史 + 实时，5m 内走推送）',
    props: () => ({
      title: '', vars: [{ expr: '', color: '#2ecc71', width: 2, visible: true }],
      timeSpan: '1h', customMinutes: 60, allowRange: true,
      refresh: 5, yMode: 'auto', yMin: 0, yMax: 100,
      legend: 'top', grid: true, crosshair: true
    })
  },
  table: {
    name: '数据表格', group: '数据', minW: 360, minH: 200, w: 420, h: 240,
    icon: 'tableico',
    tip: '数据表格（分页 + 导出 CSV，带 BOM）',
    props: () => ({
      title: '', vars: [{ expr: '', label: '', decimals: 2 }],
      pageSize: 10, showTime: true, exportCsv: true,
      timeSpan: '4h', customMinutes: 240, allowRange: true
    })
  },
  xyTrend: {
    name: 'X-Y 曲线', group: '数据', minW: 400, minH: 260, w: 420, h: 300,
    icon: 'xyico',
    tip: 'X-Y 曲线（流量-扬程这类两量关系）',
    props: () => ({
      title: '', xVar: '', yVars: [{ expr: '', color: '#2ecc71' }],
      minutes: 60, grid: true, pointSize: 2
    })
  },
  gauge: {
    name: '仪表盘', group: '显示', minW: 160, minH: 160, w: 200, h: 200,
    icon: 'gaugeico',
    tip: '仪表盘（分区色 + 指针平滑）',
    props: () => ({
      'var': '', title: '', min: 0, max: 100, unit: '', decimals: 1,
      ranges: [
        { from: 0, to: 60, color: '#22c55e' },
        { from: 60, to: 80, color: '#eab308' },
        { from: 80, to: 100, color: '#ef4444' }
      ],
      needleColor: '#f87171', showValue: true
    })
  },
  clock: {
    name: '时钟', group: '显示', minW: 120, minH: 60, w: 220, h: 80,
    icon: 'clockico',
    tip: '时钟（全局单定时器广播）',
    props: () => ({ format: 'HH:mm:ss', showDate: true, tz: 'Asia/Shanghai' })
  },
  video: {
    name: '视频窗', group: '媒体', minW: 320, minH: 180, w: 440, h: 260,
    icon: 'videoico',
    tip: '视频窗（同源 /live/，主辅码流可切）',
    props: () => ({ channel: 1, stream: 'main', fit: 'contain', title: '现场监控' })
  },
  symbolLib: {
    name: '符号库', group: '图元', minW: 40, minH: 40, w: 240, h: 260,
    icon: 'symbolico',
    tip: '符号库面板（编辑态可拖图元，运行态隐藏）',
    props: () => ({ group: '泵类' })
  }
}

export const CONTROL_GROUPS = ['数据', '显示', '媒体', '图元']

export function controlDef(c) {
  return CONTROL_TYPES[c] || { name: c || '控件', group: '数据', minW: 40, minH: 40, w: 200, h: 120, props: () => ({}) }
}

export function defaultControlProps(c) {
  try { return controlDef(c).props() } catch (e) { return {} }
}

// 新建控件时的完整 item
export function newControlItem(c, x = 40, y = 40) {
  const d = controlDef(c)
  return {
    type: 'control', control: c, name: d.name,
    x, y, w: d.w, h: d.h, props: defaultControlProps(c),
    fill: '#0b1622', stroke: '#2c4a6e', strokeWidth: 1
  }
}

// 面板/标签上的一行摘要（让人不看配置也知道这个控件在干什么）
export function controlSummary(c, p) {
  p = p || {}
  // 变量可能是对象，String(对象) 会得到 [object Object]（非空，计数偶然还对，但显示全错）
  const v = (x) => (x && typeof x === 'object') ? tagText(x) : String(x == null ? '' : x).trim()
  switch (c) {
    case 'alarm':
      return [p.title || '实时报警', p.source === 'global' ? '全部站点' : '@CurrentSite',
        p.onlyUnacked ? '仅未确认' : '全部状态'].join(' · ')
    case 'trend': {
      const n = (p.vars || []).filter(x => v(x.expr)).length
      return `${n} 条曲线 · ${p.timeSpan || '1h'} · ${p.refresh || 5}s`
    }
    case 'table': {
      const n = (p.vars || []).filter(x => v(x.expr)).length
      return `${n} 列 · 每页 ${p.pageSize || 10} 行`
    }
    case 'xyTrend':
      return `X=${v(p.xVar) || '未设'} · ${(p.yVars || []).length} 条 Y · ${p.minutes || 60}min`
    case 'gauge':
      return `${v(p['var']) || '未绑定'} · ${p.min ?? 0}~${p.max ?? 100}${p.unit ? ' ' + p.unit : ''}`
    case 'clock':
      return `${p.format || 'HH:mm:ss'}${p.showDate ? ' · 含日期' : ''} · ${p.tz || 'Asia/Shanghai'}`
    case 'video':
      return `通道 ${p.channel || 1} · ${p.stream === 'sub' ? '辅码流' : '主码流'}`
    case 'symbolLib':
      return `${p.group || '泵类'} · 编辑态可用`
    default:
      return ''
  }
}
