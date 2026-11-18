// 控件宿主（P6）
//
// 控件是真正的 Vue 组件，而画布是 render.js 手写的 DOM —— 这里做桥：
// 给每个控件的占位 div 建一个独立的 Vue app，把组件挂上去。
//
// 一条硬约束：编辑态与只读页共用同一个组件，只有 env.mode 不同。
// 不许出现 TrendControlEdit / TrendControlView 两份渲染代码（返工率最高的做法）。
import { createApp, h, reactive } from 'vue'
import AlarmControl from './AlarmControl.vue'
import TrendControl from './TrendControl.vue'
import TableControl from './TableControl.vue'
import XYTrendControl from './XYTrendControl.vue'
import GaugeControl from './GaugeControl.vue'
import ClockControl from './ClockControl.vue'
import VideoControl from './VideoControl.vue'
import SymbolLibControl from './SymbolLibControl.vue'

const COMP = {
  alarm: AlarmControl,
  trend: TrendControl,
  table: TableControl,
  xyTrend: XYTrendControl,
  gauge: GaugeControl,
  clock: ClockControl,
  video: VideoControl,
  symbolLib: SymbolLibControl
}

export const CONTROL_COMPONENTS = COMP

const MAP = new WeakMap()

function keyOf(item) {
  return String(item && item.control) + '|' + JSON.stringify((item && item.props) || {})
}

export function mountControl(host, item, env) {
  if (!host || !item) return null
  const key = keyOf(item)
  const prev = MAP.get(host)
  if (prev && prev.key === key) {
    prev.st.item = item
    return prev
  }
  unmountControl(host)
  const C = COMP[item.control]
  if (!C) {
    host.textContent = '未知控件：' + item.control
    return null
  }
  const st = reactive({ item })
  const app = createApp({ render: () => h(C, { item: st.item, env }) })
  // 单个控件崩了不能把整张画面带走
  app.config.errorHandler = (e, _i, info) => {
    console.warn('[control]', item.control, info, e)
  }
  try {
    app.mount(host)
  } catch (e) {
    console.warn('[control] 挂载失败', item.control, e)
    host.textContent = '控件加载失败：' + item.control
    return null
  }
  const rec = { app, key, st }
  MAP.set(host, rec)
  return rec
}

// 每帧调用（runtime 250ms / restyle）。配置没变就只更新 item 引用，绝不重建 ——
// 重建会把视频流断开、把趋势的累积点清空，改个标题就闪一下不能接受。
export function updateControl(host, item, env) {
  if (!host) return null
  const prev = MAP.get(host)
  if (!prev) return mountControl(host, item, env)
  if (keyOf(item) !== prev.key) return mountControl(host, item, env)
  prev.st.item = item
  return prev
}

export function unmountControl(host) {
  const rec = MAP.get(host)
  if (!rec) return
  try { rec.app.unmount() } catch (e) { /* 已卸载 */ }
  MAP.delete(host)
}
