// 画面缩略图（P8）—— 用前端 canvas 画 400×225 PNG，上传后后端存文件
//
// 为什么不用 headless chromium：200 个站点每次保存都起一次浏览器太重；
// 为什么不用 html2canvas：多一个依赖，而且 SVG/foreignObject 序列化会被 tainted canvas 挡住。
// 这里按 json 直接画：形状 + 填充 + 文字就够列表页认出来（缩略图不是截图，是"长什么样"的示意）。
//
// 约定：只读 json，不改任何对象；失败返回 null（列表页退回占位图，不影响保存）。

import { expandInstance, sizeOf } from './faceplate'

const W = 400
const H = 225

function cssColor(v, dflt) {
  const s = String(v || '').trim()
  return s || dflt
}

function fontOf(item, base) {
  const size = Number(item.fontSize) || 0
  return `${item.bold ? 'bold ' : ''}${Math.max(6, size * base)}px system-ui,"Microsoft YaHei",sans-serif`
}

function roundRect(ctx, x, y, w, h, r) {
  const rr = Math.max(0, Math.min(Number(r) || 0, Math.min(w, h) / 2))
  ctx.beginPath()
  ctx.moveTo(x + rr, y)
  ctx.arcTo(x + w, y, x + w, y + h, rr)
  ctx.arcTo(x + w, y + h, x, y + h, rr)
  ctx.arcTo(x, y + h, x, y, rr)
  ctx.arcTo(x, y, x + w, y, rr)
  ctx.closePath()
}

function drawOne(ctx, item, s, ox, oy, depth, fpt) {
  if (!item || item.hidden) return
  if (depth > 6) return
  const x = ox + (Number(item.x) || 0) * s
  const y = oy + (Number(item.y) || 0) * s
  const w = Math.max(1, (Number(item.w) || 10) * s)
  const h = Math.max(1, (Number(item.h) || 10) * s)
  const fill = cssColor(item.fill || item.liquidColor, '#12263f')
  const stroke = cssColor(item.stroke, '#1e3a5f')
  const t = item.type

  ctx.save()
  if (item.opacity !== undefined) ctx.globalAlpha = Math.max(0, Math.min(100, Number(item.opacity) || 0)) / 100
  if (item.rot) {
    ctx.translate(x + w / 2, y + h / 2)
    ctx.rotate((Number(item.rot) || 0) * Math.PI / 180)
    ctx.translate(-(x + w / 2), -(y + h / 2))
  }

  if (t === 'group') {
    for (const c of item.items || []) drawOne(ctx, c, s, x, y, depth + 1, fpt)
    ctx.restore()
    return
  }
  if (t === 'faceplate') {
    // 模板定义在手上：把 @接口变量 换成绑定值后按实例尺寸缩放画出来，
    // 否则列表页里凡是组件模板实例的画面都只剩两个虚线框，等于没有缩略图。
    const def = fpt && fpt.get ? fpt.get(item.fptId) : null
    if (def) {
      const ts = sizeOf(def)
      ctx.save()
      ctx.beginPath()
      ctx.rect(x, y, w, h)
      ctx.clip()
      ctx.translate(x, y)
      ctx.scale(w / ts.w, h / ts.h)
      for (const c of expandInstance(item, def)) drawOne(ctx, c, 1, 0, 0, depth + 1, fpt)
      ctx.restore()
      ctx.restore()
      return
    }
    ctx.setLineDash([4, 3])
    ctx.strokeStyle = '#4a6d92'
    ctx.strokeRect(x, y, w, h)
    ctx.restore()
    return
  }

  if (t === 'circle' || t === 'ellipse') {
    ctx.beginPath()
    ctx.ellipse(x + w / 2, y + h / 2, w / 2, h / 2, 0, 0, Math.PI * 2)
    ctx.fillStyle = fill
    ctx.fill()
    if (item.strokeWidth !== 0) { ctx.strokeStyle = stroke; ctx.stroke() }
  } else if (t === 'line' || t === 'polyline' || t === 'arc') {
    ctx.strokeStyle = cssColor(item.stroke, '#7cc4ff')
    ctx.lineWidth = Math.max(1, (Number(item.strokeWidth) || 1) * s)
    ctx.beginPath()
    if (t === 'arc') ctx.arc(x + w / 2, y + h, Math.min(w / 2, h), Math.PI, Math.PI * 2)
    else { ctx.moveTo(x, y + h / 2); ctx.lineTo(x + w, y + h / 2) }
    ctx.stroke()
  } else if (t === 'tank') {
    roundRect(ctx, x, y, w, h, 6 * s)
    ctx.fillStyle = cssColor(item.fill, '#12263f')
    ctx.fill()
    ctx.strokeStyle = cssColor(item.stroke, '#2c4a6e')
    ctx.lineWidth = Math.max(1, 2 * s)
    ctx.stroke()
    // 液体：默认画到 45%，看起来像"有液位"
    const pct = 0.45
    ctx.save()
    ctx.beginPath()
    roundRect(ctx, x, y, w, h, 6 * s)
    ctx.clip()
    ctx.fillStyle = cssColor(item.liquidColor, '#1ec8ff')
    ctx.fillRect(x, y + h * (1 - pct), w, h * pct)
    ctx.restore()
  } else if (t === 'pump' || t === 'pump_v' || t === 'pump_h' || t === 'valve' || t === 'fan' ||
             t === 'grill' || t === 'conveyor' || t === 'pipe' || t === 'pipe_v' ||
             t === 'pipe_t' || t === 'pipe_elbow' || t === 'symbol') {
    ctx.beginPath()
    if (t.startsWith('pipe') || t === 'conveyor') {
      ctx.fillStyle = cssColor(item.fill, '#1b3a5c')
      ctx.fillRect(x, y, w, h)
    } else {
      ctx.arc(x + w / 2, y + h / 2, Math.min(w, h) / 2, 0, Math.PI * 2)
      ctx.fillStyle = cssColor(item.fill || item.colorRun, '#1ec8ff')
      ctx.fill()
      ctx.strokeStyle = cssColor(item.stroke, '#2c4a6e')
      ctx.stroke()
    }
  } else if (t === 'control') {
    roundRect(ctx, x, y, w, h, 3 * s)
    ctx.fillStyle = '#0b1622'
    ctx.fill()
    ctx.strokeStyle = '#1e3a5f'
    ctx.stroke()
    ctx.fillStyle = '#1ec8ff'
    ctx.font = `${Math.max(6, 9 * s * 1.4)}px system-ui,sans-serif`
    ctx.fillText(String(item.control || '控件'), x + 3, y + Math.min(h - 2, 11 * s * 1.4))
  } else if (t === 'image') {
    ctx.fillStyle = '#0e1f33'
    ctx.fillRect(x, y, w, h)
    ctx.strokeStyle = '#334155'
    ctx.strokeRect(x, y, w, h)
  } else {
    // rect / value / input / button / text / 其它：方块 + 可能的文字
    roundRect(ctx, x, y, w, h, (Number(item.radius) || 0) * s)
    if ((item.fillMode || 'solid') !== 'none') {
      ctx.fillStyle = t === 'button' ? cssColor(item.fill, '#1d4ed8') : fill
      ctx.fill()
    }
    if (Number(item.strokeWidth) !== 0) {
      ctx.strokeStyle = stroke
      ctx.lineWidth = Math.max(1, (Number(item.strokeWidth) || 1) * s)
      ctx.stroke()
    }
  }

  const txt = item.text || item.label || (t === 'value' && item.var ? '--' : '')
  if (txt) {
    ctx.fillStyle = cssColor(item.color, '#e2e8f0')
    ctx.font = fontOf(item, Math.max(0.55, s * 1.6))
    ctx.textAlign = item.align === 'center' ? 'center' : (item.align === 'right' ? 'right' : 'left')
    ctx.textBaseline = 'middle'
    const tx = item.align === 'center' ? x + w / 2 : (item.align === 'right' ? x + w - 3 : x + 3)
    ctx.fillText(String(txt).slice(0, 40), tx, y + h / 2)
  }
  ctx.restore()
}

// json → 400×225 PNG 的 dataURL；画布超出/比例不符时等比缩放并居中
export function paintThumb(json, opts) {
  try {
    const o = opts || {}
    const cw = document.createElement('canvas')
    cw.width = W
    cw.height = H
    const ctx = cw.getContext('2d')
    if (!ctx) return null
    const bg = o.bg || (json && json.bg) || '#0b1622'
    ctx.fillStyle = (bg === 'transparent' ? '#0b1622' : bg)
    ctx.fillRect(0, 0, W, H)

    const pw = Number(json && json.width) || 1600
    const ph = Number(json && json.height) || 900
    const s = Math.min(W / pw, H / ph)
    const ox = (W - pw * s) / 2
    const oy = (H - ph * s) / 2
    for (const it of (json && json.items) || []) drawOne(ctx, it, s, ox, oy, 0, o.fpt)
    return cw.toDataURL('image/png')
  } catch (e) {
    return null
  }
}

export const THUMB_W = W
export const THUMB_H = H
