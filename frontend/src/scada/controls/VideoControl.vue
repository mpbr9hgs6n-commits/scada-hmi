<template>
  <div class="ctl video" :class="{ 'ctl-edit': edit }">
    <video ref="vd" muted autoplay playsinline :style="{ objectFit: P.fit || 'contain' }" />
    <div class="bar">
      <span class="ttl">{{ P.title || '现场监控' }}</span>
      <span class="sp" />
      <span v-if="state === 'playing'" class="live">● LIVE</span>
      <span class="res">{{ res }}</span>
      <button v-if="!edit" class="vsw" :title="'切到' + (st === 'main' ? '辅码流' : '主码流')"
              @click="toggleStream">{{ st === 'main' ? '主码流' : '辅码流' }}</button>
    </div>
    <div v-if="err" class="err">
      <div class="em">{{ err }}</div>
      <button v-if="!edit" class="rt" @click="play">重试</button>
    </div>
    <div v-else-if="state === 'loading'" class="loading">正在打开视频流…</div>
  </div>
</template>

<script setup>
// 视频窗：同源 /live/ + flv.js。
// 四个坑（任务书点名）：
//   1) 必须同源（走 nginx 反代），直连 ZLM 端口会 CORS 白屏
//   2) 错误回调要分类 —— 一律 destroy 会形成「建了销毁、销毁又建」的死循环，现象是黑屏 + 控制台刷屏
//   3) 失败要显示具体原因（流不存在 / 编码不支持 / 网络），不许黑屏无提示
//   4) 主辅码流切换先 stop 再 play，不要直接换 src
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { get } from '../../utils/request'

const props = defineProps({ item: { type: Object, required: true }, env: { type: Object, required: true } })
const P = computed(() => props.item.props || {})
const edit = computed(() => props.env.mode === 'edit')

const vd = ref(null)
const state = ref('idle')
const err = ref('')
const res = ref('')
const st = ref('main')
const list = ref([])

let player = null
let flvjs = null
let retries = 0
let wd = 0
let retryTimer = 0
let lastT = -1
let still = 0
let stopped = false

const chs = computed(() => list.value)

async function loadChannels() {
  try {
    const site = props.env.site || ''
    const r = await get('/api/video/cameras?site=' + encodeURIComponent(site), { silent: true })
    list.value = r.items || []
  } catch (e) {
    list.value = []
  }
  // props.channel 是 1 起的通道号；越界就用第一个（不要让控件整块空白）
  const idx = Math.max(0, (Number(P.value.channel) || 1) - 1)
  return chs.value[idx] || chs.value[0] || null
}

function destroyPlayer() {
  if (player) {
    try { player.pause() } catch (e) { /* 已暂停 */ }
    try { player.unload() } catch (e) { /* 已卸载 */ }
    try { player.detachMediaElement() } catch (e) { /* 已分离 */ }
    try { player.destroy() } catch (e) { /* 已销毁 */ }
    player = null
  }
}

async function play() {
  if (stopped) return
  err.value = ''
  state.value = 'loading'
  destroyPlayer()
  const cam = await loadChannels()
  if (!cam) {
    state.value = 'error'
    err.value = '没有可用视频通道（相机清单为空）'
    return
  }
  if (cam.online === false && st.value === 'main') {
    state.value = 'error'
    err.value = '流不存在（通道离线，检查相机或 ZLM 拉流）'
    return
  }
  // 流名分隔符是短横线（S001-7-sub），不是下划线；写成 _sub 会 404
  const stream = cam.stream + (st.value === 'sub' ? '-sub' : '')
  let url = cam.url
  try {
    const tk = await get('/api/video/token?stream=' + encodeURIComponent(stream), { silent: true })
    url = '/live/' + stream + '.live.flv?token=' + tk.token
  } catch (e) {
    state.value = 'error'
    err.value = '取播放地址失败（' + (e && e.message ? e.message : '接口异常') + '）'
    return
  }
  try {
    if (!flvjs) {
      const m = await import('flv.js')
      flvjs = m.default || m
    }
    if (!flvjs.isSupported()) {
      state.value = 'error'
      err.value = '浏览器不支持 FLV 播放（需要 MSE）'
      return
    }
    const p = flvjs.createPlayer(
      { type: 'flv', url, isLive: true, hasAudio: false },
      { enableStashBuffer: false, stashInitialSize: 128, autoCleanupSourceBuffer: true, lazyLoad: false }
    )
    player = p
    p.attachMediaElement(vd.value)
    p.on(flvjs.Events.ERROR, (type, detail) => onErr(type, detail))
    p.on(flvjs.Events.STATISTICS_INFO, () => { state.value = 'playing' })
    p.load()
    const pr = vd.value.play()
    if (pr && pr.catch) pr.catch(() => { /* 自动播放被拦：静音已设，忽略 */ })
    vd.value.onloadedmetadata = () => {
      res.value = vd.value.videoWidth ? vd.value.videoWidth + '×' + vd.value.videoHeight : ''
      retries = 0                      // 成功了，重试计数归零
    }
    state.value = 'playing'
  } catch (e) {
    state.value = 'error'
    err.value = '播放器初始化失败：' + (e && e.message ? e.message : '')
  }
}

function onErr(type, detail) {
  // 只有网络/媒体错误才值得重建；其他（如解码器的偶发告警）重建没用，还会死循环
  if (type === 'NetworkError') {
    retries++
    armRetry()
    if (retries <= 3) {
      state.value = 'loading'
      setTimeout(() => { if (!stopped) play() }, 1500 * retries)
    } else {
      state.value = 'error'
      err.value = '网络中断，取不到视频流（已重试 3 次）'
    }
    return
  }
  if (type === 'MediaError') {
    state.value = 'error'
    err.value = '编码不支持（可能是 H.265），切到辅码流试试'
    return
  }
  // 其他错误：只记日志，不动播放器
  console.warn('[video] 忽略错误', type, detail)
}

function toggleStream() {
  st.value = st.value === 'main' ? 'sub' : 'main'
  retries = 0
  play()     // 先 stop 再 play —— play() 内部第一件事就是 destroyPlayer
}

// 出错后的受控自动重试：5 秒一次，不是「错误回调一律 destroy」的刷屏死循环 ——
// 拨掉的流重新推上来后视频窗要能自己恢复，不能让操作员手点重试
function armRetry() {
  if (retryTimer) return
  retryTimer = setInterval(() => {
    if (stopped || document.hidden) return
    if (state.value !== 'error') { clearInterval(retryTimer); retryTimer = 0; return }
    if (retries >= 12) return        // 连续 12 次（1 分钟）都失败：停手，留手动重试
    retries++
    play()
  }, 5000)
}

function watchdog() {
  const v = vd.value
  if (!v || state.value !== 'playing') { still = 0; return }
  if (v.currentTime !== lastT) { lastT = v.currentTime; still = 0; return }
  still++
  // 2s × 5 = 10s 没有任何画面推进：断流了，必须明确告诉操作员，不能留黑屏
  if (still >= 5) {
    state.value = 'error'
    err.value = '视频流已中断（10 秒没有数据）'
    armRetry()
  }
}

onMounted(() => {
  st.value = P.value.stream === 'sub' ? 'sub' : 'main'
  play()
  wd = setInterval(watchdog, 2000)
})
onUnmounted(() => {
  stopped = true
  clearInterval(wd)
  if (retryTimer) { clearInterval(retryTimer); retryTimer = 0 }
  destroyPlayer()
})
watch(() => [props.env.site, P.value.channel], () => { retries = 0; play() })
</script>

<style scoped>
.ctl { width: 100%; height: 100%; box-sizing: border-box; position: relative; overflow: hidden; background: #000; }
video { width: 100%; height: 100%; display: block; background: #000; }
.bar { position: absolute; left: 0; right: 0; top: 0; display: flex; align-items: center; gap: 6px;
  padding: 2px 6px; background: linear-gradient(180deg, rgba(4, 12, 20, .78), transparent); pointer-events: none; }
.ttl { font-size: 11px; color: #dbeafe; text-shadow: 0 1px 2px #000; }
.sp { flex: 1 1 auto; }
.live { font-size: 10px; color: #22c55e; font-weight: 600; }
.res { font-size: 10px; color: #9fc3e8; }
.vsw { pointer-events: auto; font-size: 10px; padding: 0 5px; line-height: 15px; background: rgba(18, 58, 92, .9);
  color: #cfe4f7; border: 1px solid #1e3a5f; border-radius: 2px; cursor: pointer; }
.vsw:hover { background: rgba(23, 69, 107, .95); }
.err { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; background: rgba(8, 18, 28, .92); text-align: center; padding: 8px; }
.em { color: #f87171; font-size: 12px; line-height: 1.5; max-width: 100%; }
.rt { font-size: 11px; padding: 2px 10px; background: #123a5c; color: #cfe4f7; border: 1px solid #1e3a5f;
  border-radius: 3px; cursor: pointer; }
.loading { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  color: #7fa8cc; font-size: 12px; background: rgba(8, 18, 28, .7); }
</style>
