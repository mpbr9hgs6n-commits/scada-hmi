<template>
  <el-row :gutter="12">
    <el-col :span="16">
      <el-card shadow="never">
        <template #header>
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span>{{ site.name }} · 工艺图（{{ site.id }}）</span>
            <span>
              <el-tag :type="sseOk ? 'success' : 'warning'" size="small">
                {{ sseOk ? 'SSE 实时' : '轮询兜底' }}
              </el-tag>
            </span>
          </div>
        </template>
        <div ref="scadaBox" class="scada-box"></div>
      </el-card>
    </el-col>
    <el-col :span="8">
      <el-card shadow="never" style="margin-bottom:12px">
        <template #header>
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span>实时数据</span>
            <span style="font-size:12px;color:#909399">{{ freshText }}</span>
          </div>
        </template>
        <el-table :data="pointRows" size="small" max-height="380">
          <el-table-column prop="name" label="点位" min-width="110" />
          <el-table-column label="值" width="100" align="right">
            <template #default="{ row }">
              <span style="font-family:Consolas,monospace;font-weight:600"
                    :style="{ color: row.q === 1 ? '#c0c4cc' : '#1d4ed8' }">
                {{ row.val == null ? '--' : row.val }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="unit" label="单位" width="70" />
          <el-table-column label="采集时间" width="86">
            <template #default="{ row }">
              <span style="font-size:12px"
                    :style="{ color: row.fresh ? '#67c23a' : '#f56c6c' }">{{ row.time }}</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
      <el-card shadow="never">
        <template #header>
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span>视频监控</span>
            <el-select v-model="stream" size="small" style="width:190px" @change="switchStream">
              <el-option v-for="c in cameras" :key="c.stream" :value="c.stream"
                         :label="c.name" :disabled="!c.online" />
            </el-select>
          </div>
        </template>
        <video ref="videoEl" class="live-video" muted autoplay playsinline></video>
        <div v-if="isMock" class="mock-tip">
          当前为演示流（SMPTE 测试卡），非现场画面。配置真实相机后自动切换。
        </div>
        <div class="video-state">{{ videoState }}</div>
      </el-card>
    </el-col>
  </el-row>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { get, post } from '../utils/request'
import { fmtNum } from '../scada/deck.js'
import { renderScada, ensureScadaStyles, destroyScada } from '../scada/render'
import flvjs from 'flv.js'
import { liveUrl } from '../utils/live'

const route = useRoute()
const siteId = route.params.id
const site = ref({ id: siteId, name: '' })
const values = ref({})       // code -> {val, ts, q}
const meta = ref({})         // code -> {name, unit, decimals}
const scadaBox = ref(null)
const videoEl = ref(null)
const sseOk = ref(false)
const pageJson = ref(null)
const alarms = ref([])
const cameras = ref([])
const stream = ref('')
// 画布内视频用的带 token 地址；token 过期/断流时由 onVideoError 重签
const streamSrc = ref('')
const isMock = ref(false)
const videoState = ref('未连接')
let es = null, pollTimer = null, renderTimer = null
let player = null, retryTimer = null, retry = 0

// 点位名/单位来自站点详情（元数据），实时值来自 SSE —— 两者按 code 对齐
const pointRows = computed(() => {
  const now = Date.now()
  return Object.keys(meta.value).map(code => {
    const m = meta.value[code]
    const v = values.value[code]
    const ts = v?.ts || 0
    const age = ts ? (now - ts) / 1000 : 99999
    return {
      code, name: m.name || code, unit: m.unit || '',
      val: v && v.val != null ? fmtNum(v.val, { dtype: m.dtype, ts: v.ts, pollMs: v.poll_ms }, m) : null,
      q: v?.q ?? 1,
      fresh: age < 15,
      time: ts ? new Date(ts).toLocaleTimeString('zh-CN', { hour12: false }) : '--'
    }
  })
})

const freshText = computed(() => {
  const t = pointRows.value.map(r => r.time).filter(t => t !== '--').sort().pop()
  return t ? `最新 ${t}` : '暂无数据'
})

function draw() {
  if (!scadaBox.value) return
  ensureScadaStyles()
  const vals = {}
  for (const [k, v] of Object.entries(values.value)) vals[k] = v
  const json = pageJson.value || defaultJson()
  json.items.forEach(it => {
    if (it.type === 'video') {
      it.src = streamSrc.value
      it.stream = stream.value
    }
    if (it.type === 'alarm_list') it.alarms = alarms.value
  })
  renderScada(scadaBox.value, json, vals, {
    onVideoError: async (s) => {
      // 画布里的流断了（多为 token 过期/网络抖动）：重签一次，下一轮 patch 自动重连
      if (!s) return
      const u = await liveUrl(s, true)
      if (u) streamSrc.value = u
    },
    onWrite: async (code, value) => {
      try {
        const r = await post('/api/write', { site: siteId, point: code, value })
        ElMessage.success(`下发成功，回读值 ${r.value}`)
      } catch (e) { /* 已提示 */ }
    }
  })
}

function defaultJson() {
  return { width: 1600, height: 900, bg: '#0b1622', items: [
    { type: 'tank', x: 120, y: 160, w: 200, h: 320, var: 'LEVEL', min: 0, max: 5, unit: 'm', label: '集水井液位' },
    { type: 'pump', x: 480, y: 220, w: 100, h: 110, var: 'PUMP1_RUN', label: '1号泵' },
    { type: 'pump', x: 480, y: 400, w: 100, h: 110, var: 'PUMP2_RUN', label: '2号泵' },
    { type: 'pipe', x: 320, y: 270, w: 160, h: 18, var: 'PUMP1_RUN' },
    { type: 'value', x: 120, y: 520, w: 200, h: 40, var: 'LEVEL', decimals: 2, unit: 'm' },
    { type: 'value', x: 640, y: 160, w: 220, h: 40, var: 'PH', decimals: 2, unit: 'pH', label: 'PH' },
    { type: 'value', x: 640, y: 220, w: 220, h: 40, var: 'FLOW', decimals: 1, unit: 'm3/h', label: '流量' },
    { type: 'value', x: 640, y: 280, w: 220, h: 40, var: 'DO', decimals: 2, unit: 'mg/L', label: '溶解氧' },
    { type: 'value', x: 640, y: 340, w: 220, h: 40, var: 'TEMP', decimals: 1, unit: '℃', label: '水温' },
    { type: 'lamp', x: 480, y: 150, w: 36, h: 36, var: 'PUMP1_RUN', label: '运行' },
    { type: 'button', x: 480, y: 560, w: 140, h: 46, var: 'PUMP1_RUN', label: '启停1号泵' },
    { type: 'video', x: 920, y: 160, w: 560, h: 330, label: '现场监控' },
    { type: 'alarm_list', x: 920, y: 520, w: 560, h: 240 }
  ]}
}

// SSE 订阅 + 3 秒无消息兜底轮询快照（硬约束 19）
function connectSSE() {
  const token = localStorage.getItem('token')
  es = new EventSource(`/api/live/subscribe?site=${siteId}&token=${token}`)
  let got = false
  es.addEventListener('delta', e => {
    got = true; sseOk.value = true
    for (const d of JSON.parse(e.data)) {
      values.value[d.code] = { ...(values.value[d.code] || {}), val: parseFloat(d.val), ts: +d.ts, q: +d.q }
    }
  })
  es.onerror = () => { sseOk.value = false }
  pollTimer = setInterval(async () => {
    if (!got) {
      try {
        const snap = await get(`/api/site/${siteId}/snapshot`)
        for (const [code, v] of Object.entries(snap.values)) {
          values.value[code] = { val: v.val, ts: v.ts, q: v.q }
          if (!meta.value[code] && v.name) {
            meta.value[code] = { name: v.name, unit: v.unit, decimals: v.decimals, dtype: v.dtype }
          }
        }
      } catch (e) {}
    }
    got = false
  }, 3000)
}

/* ---------- 视频：单实例 + 错误分类，只有网络/媒体错误才重建 ---------- */
function teardown() {
  if (retryTimer) { clearTimeout(retryTimer); retryTimer = null }
  if (!player) return
  try { player.pause() } catch (e) {}
  try { player.unload() } catch (e) {}
  try { player.detachMediaElement() } catch (e) {}
  try { player.destroy() } catch (e) {}
  player = null
}

async function setupVideo(name) {
  if (!name || !videoEl.value) return
  teardown()
  if (!flvjs.isSupported()) { videoState.value = '浏览器不支持 flv 播放'; return }
  videoState.value = '连接中…'
  // 每次（重）连都重新签 token：ZLM 的 on_play 只校验播放开始那一刻
  const url = await liveUrl(name, true)
  if (!url) { videoState.value = '取流鉴权失败，请重新登录'; return }
  streamSrc.value = url
  const p = flvjs.createPlayer(
    { type: 'flv', url, isLive: true, hasAudio: false },
    { enableStashBuffer: false, stashInitialSize: 128, autoCleanupSourceBuffer: true,
      lazyLoad: false, fixAudioTimestampGap: false }
  )
  player = p
  p.attachMediaElement(videoEl.value)
  p.on(flvjs.Events.ERROR, (type, detail) => {
    // 只有真正的网络/媒体错误才重建；其余只记录，避免"建了销毁、销毁又建"的死循环
    const fatal = type === 'NetworkError' || type === 'MediaError'
    console.warn('[flv]', type, detail)
    if (!fatal) return
    teardown()
    retry = Math.min(retry + 1, 6)
    const delay = Math.min(2000 * retry, 15000)
    videoState.value = `断流，${delay / 1000}s 后重连（第 ${retry} 次）`
    retryTimer = setTimeout(() => setupVideo(name), delay)
  })
  p.on(flvjs.Events.STATISTICS_INFO, () => { videoState.value = '播放中'; retry = 0 })
  p.load()
  try {
    await videoEl.value.play()
    videoState.value = '播放中'
    retry = 0
  } catch (e) {
    // 自动播放被浏览器拦截时不算错误，静音自动播放一般可过
    if (e.name !== 'AbortError') console.warn('[video] play:', e.message)
  }
}

async function switchStream(name) { retry = 0; await setupVideo(name) }

async function loadCameras() {
  try {
    const r = await get(`/api/video/cameras?site=${siteId}`)
    cameras.value = r.items || []
    const online = cameras.value.find(c => c.online)
    const first = online || cameras.value[0]
    if (first) {
      stream.value = first.stream
      isMock.value = first.kind === 'mock'
      streamSrc.value = first.url || await liveUrl(first.stream)
      await setupVideo(first.stream)
    }
  } catch (e) { videoState.value = '取流失败' }
}

async function loadAlarms() {
  try {
    const r = await get('/api/alarms?state=0&size=6')
    alarms.value = r.items.map(a => `[${a.site_id}] ${a.msg}`)
  } catch (e) {}
}

onMounted(async () => {
  ensureScadaStyles()
  const s = await get('/api/site/' + siteId)
  site.value = s
  // 09 改造：站点详情不再内嵌点位数组，点位元数据走 /api/points（最多 200 点足够详情页用）
  const pts = await get(`/api/points?site_id=${encodeURIComponent(siteId)}&size=200`).catch(() => ({ items: [] }))
  for (const p of pts.items || []) {
    meta.value[p.code] = { name: p.name, unit: p.unit, decimals: p.decimals ?? 2, dtype: p.dtype }
  }
  const pages = await get('/api/pages?kind=scada').catch(() => ({ items: [] }))
  const pg = pages.items.find(p => p.site_id === siteId)
  if (pg) {
    const full = await get('/api/page/' + pg.id)
    pageJson.value = full.json
  }
  connectSSE()
  loadCameras()
  renderTimer = setInterval(draw, 1000)
  draw()
  setInterval(loadAlarms, 5000); loadAlarms()
  setInterval(() => {
    if (stream.value) post('/api/video/heartbeat', { stream: stream.value }).catch(() => {})
  }, 30000)
})
onUnmounted(() => {
  es && es.close()
  clearInterval(pollTimer); clearInterval(renderTimer)
  teardown()
  destroyScada(scadaBox.value)   // 连组态画布里的视频流一起断掉，别把连接留给下一个页面
})
</script>

<style scoped>
.scada-box { width: 100%; overflow: hidden; background: #0b1622; border-radius: 4px; min-height: 520px; }
.live-video { width: 100%; height: 280px; background: #000; border-radius: 4px; }
.mock-tip { margin-top: 6px; font-size: 12px; color: #e6a23c; background: #fdf6ec; padding: 6px 8px; border-radius: 4px; }
.video-state { margin-top: 4px; font-size: 12px; color: #909399; }
</style>
