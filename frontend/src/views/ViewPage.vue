<template>
  <div class="view-wrap">
    <div class="view-head">
      <span>
        {{ page.name || '加载中…' }}
        <el-tag v-if="effectiveSite" size="small" style="margin-left:8px">{{ effectiveSite }}</el-tag>
        <el-tag v-else type="warning" size="small" style="margin-left:8px">模板预览</el-tag>
      </span>
      <span>
        <el-tag :type="sseOk ? 'success' : 'warning'" size="small" style="margin-left:8px">
          {{ sseOk ? '实时' : '轮询' }}
        </el-tag>
        <el-tag v-if="issueCount" type="warning" size="small" style="margin-left:6px"
                :title="'有绑定取不到值，画布上已标黄'">{{ issueCount }} 个绑定异常</el-tag>
        <el-button v-if="!embedded" size="small" style="margin-left:10px" @click="goBack">返回平台</el-button>
      </span>
    </div>

    <!-- 画面没绑站点：站点是画面自身的属性，不是看的人临时选的，所以这里不给选择器，
         只给出明确出路（去画面列表把站点定下来），避免"看的人随手一选"把数据看串。 -->
    <div v-if="!effectiveSite && page.id" class="bind-bar">
      <el-alert type="warning" :closable="false" show-icon style="flex:1"
                title="这张画面还没有绑定站点，取不到数据。请到「组态管理 → 画面列表」编辑这张画面，在「站点」里选定后保存。" />
    </div>

    <!-- 提示词 10 4.3：读到字符串格式的 var 直接报错，不猜、不渲染 -->
    <el-alert v-if="varError" type="error" :closable="false" show-icon :title="varError"
              style="margin:12px" />
    <div v-else ref="box" class="view-canvas"></div>
  </div>
</template>

<script setup>
// 只读渲染页 —— 与编辑器共用 renderScada（硬约束 18），只看不可改。
// P4 起数值与动态化统一走 ScadaRuntime：SSE + 快照兜底 + 求值 + 应用，编辑器同一套。
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useUserStore } from '../store'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { get, post } from '../utils/request'
import { renderScada, ensureScadaStyles, destroyScada } from '../scada/render'
import { liveUrl } from '../utils/live'
import { ScadaRuntime, resolveSite, resolveTags } from '../scada/runtime'
import { findInvalidVar, collectVarSites } from '../scada/varbind'
import { attachEvents, firePictureClose } from '../scada/events'
import { makeEnv } from '../scada/controls/env'

const props = defineProps({
  // 14 号：发布入口把画面作为子组件用，通过这个 prop 指定要看哪张
  pageIdProp: { type: [String, Number], default: null },
  // embedded=true 时不显示「返回平台」等导航按钮（发布入口自己有）
  embedded: { type: Boolean, default: false },
})

const route = useRoute()
const router = useRouter()
let pageId = props.pageIdProp || route.params.id
// 发布态用只读接口（校验 published=1），独立访问用普通接口
const user = useUserStore()
const pageApi = props.embedded ? '/api/publish/page/' : '/api/page/'
const page = ref({})
const box = ref(null)
const sseOk = ref(false)
const issueCount = ref(0)
const alarms = ref([])
const curSite = ref('')
const stream = ref('')
const varError = ref('')
const streamSrc = ref('')
// 该站点的全部通道（每个视频窗按自己的 ch / stream 从这里取）
const camList = ref([])
const isMock = ref(false)
let rt = null
let hbTimer, alTimer
// P6 控件环境：运行态 mode='runtime' —— 报警窗能确认、视频窗能切码流
const ctrlEnv = makeEnv({ mode: 'runtime', rt: null, site: '' })

const effectiveSite = computed(() => curSite.value || '')

// 事件上下文（P5）：只读页是运行态 —— 鼠标/键盘动作真的执行
function evCtx() {
  return {
    container: box.value,
    rt,
    interactive: true,
    onToast: (text, type) => ElMessage({ message: text, type: type || 'info' }),
    openPage: (pid) => { if (pid) location.href = '/view/' + pid },
    closePage: () => goBack(),
    resolveTags,
    rebind: () => { if (box.value) attachEvents(box.value, evCtx()) }
  }
}

async function draw() {
  if (!box.value) return
  ensureScadaStyles()
  const json = page.value.json || {}
  json.items = json.items || []
  const videoJobs = []
  json.items.forEach(it => {
    if (it.type === 'alarm_list') it.alarms = alarms.value
    if (it.type === 'video') videoJobs.push(it)
  })
  // 视频窗：必须按「当前实际的那一路流名」现签播放地址。
  // cam.url 是 /api/video/cameras 按主码流算好的，切了子码流还用它就会播错路。
  await Promise.all(videoJobs.map(async (it) => {
    const cam = pickCam(it)
    if (!cam) { it.src = streamSrc.value; it.stream = stream.value; return }
    it.stream = cam.stream
    const u = await liveUrl(cam.stream)      // 按实际那一流的流名签（主/辅）
    it.src = u || ''
  }))
  renderScada(box.value, json, rt ? rt.flat() : {}, {
    onVideoError: async (s) => {
      // token 5 分钟过期会断流，按流名重签一次（只更新这一路，不影响别的窗）
      if (!s) return
      const u = await liveUrl(s, true)
      if (!u) return
      const cam = camList.value.find(c => c.stream === s)
      if (cam) cam.url = u
      else streamSrc.value = u
      draw()
    },
    // 14 号：按钮配了「跳转画面」时走这里（render.js 里 targetPage 优先级最高）
    // 发布态要留在发布入口里跳（否则目录树就丢了），普通运行态才跳 /view/
    onNavigate: (pid) => {
      if (!pid) return
      router.push(props.embedded ? `/publish/${pid}` : `/view/${pid}`)
    },
    // 老画面（按钮只用 var 字段、没配事件）仍然能点：走同一条写回链路
    onWrite: (code, val) => {
      if (!rt || !rt.site) {
        ElMessage.warning('未选站点，不能下发')
        return Promise.reject(new Error('未选站点，不能下发'))
      }
      return rt.write(code, val, { silent: false })
        .then((r) => { ElMessage.success('已写入 ' + ((r && r.value !== undefined) ? r.value : val)); return r })
        .catch((e) => { ElMessage.error((e && e.message) || '写入失败'); throw e })
    },
    // 修复 09：I/O 域输入态要的三样东西
    site: () => effectiveSite.value,
    readValue: (t) => { const r = rt ? rt.read(t) : null; return r && r.found ? r.val : undefined },
    // 提示词 11：渲染器统一三态取值（q/ts 一起给，跨站点对象 var 走这里）
    readFull: (t) => (rt ? rt.read(t) : null),
    // 视频窗属性页诊断行用：当前实际会连哪一路
    resolveCam: (it) => pickCam(it),
    rwOf: (t) => (rt ? rt.rwOf(t) : null),
    // 2026-11-13：I/O 域在预览态也要能输入（原「预览只显示」作废）。
    // 但要挡住两类：①只读角色 ②发布/大屏 kiosk（电视上误触会真写 PLC）。
    canWrite: (user.user?.role || '') !== 'viewer',
    // 2026-11-14 用户要求：①/publish 的 I/O 域必须能输入 ②外观不许变。
    // 所以 kiosk 不再裁可写性（render.js 的 canWrite 已不看它），只表示
    // 「这是发布端」→ 输入框渲染成与只读文本完全一致的无边框样式。
    kiosk: !!props.embedded,
    // P6 控件：与编辑器同一个组件，只是 mode 不同
    mode: 'runtime',
    ctrlEnv,
    // P8：组件模板实例实时读模板定义（改模板 → 所有实例同步变）
    fpt: rt ? rt.fpt : new Map()
  })
  if (rt) rt.attach(box.value)
  attachEvents(box.value, evCtx())
}

// 按控件的配置从通道列表里挑一路
function pickCam(it) {
  const list = camList.value
  if (!list || !list.length) return null
  const wantSub = String(it.chStream || 'main') === 'sub'

  // 1) 手动流名最高优先：填了就直接用，列表里没有也拉
  const manual = String(it.chManual || '').trim()
  if (manual) {
    const hit = list.find(c => c.stream === manual || c.stream_sub === manual)
    if (hit) {
      const st = wantSub ? (hit.stream_sub || hit.stream) : (hit.stream || hit.stream_sub)
      return { ...hit, stream: st, sub: wantSub, manual: true }
    }
    return { stream: manual, sub: wantSub, manual: true, browser_ok: true, browser_ok_sub: true,
             codec: '', codec_sub: '', name: '' }
  }

  // 2) 该码流下的流名和可播判定
  const streamOf = (c) => (wantSub ? (c.stream_sub || '') : (c.stream || ''))
  const okOf = (c) => (wantSub ? (c.browser_ok_sub !== false) : (c.browser_ok !== false))

  // 3) 按配置找：纯数字（老画面）按 legacy_stream 末尾数字；否则按流名（含老流名）
  const rawCh = String(it.ch === undefined || it.ch === null ? '' : it.ch).trim()
  let hit = null
  if (rawCh && /^\d+$/.test(rawCh)) {
    const n = Number(rawCh)
    hit = list.find(c => Number(String(c.legacy_stream || '').split('-').pop()) === n)
       || list.find(c => Number(String(c.stream || '').split('-').pop()) === n)
  } else if (rawCh) {
    // 注意：这里绝不能再比 legacy_stream。
    // 流名规则从 sort_no+1 改成主键后，同一个字符串两边都有主：
    //   "S001-5" 既是 id=5 的新流名，又是 id=8 的老流名（sort_no+1=5）。
    // camList 按 H.264 优先排序，find 会先撞上 id=8 → 选格栅间播出来是二沉池。
    // 老画面存的 ch 是纯数字（走上面那个分支），字符串一定是新流名。
    hit = list.find(c => c.stream === rawCh) || list.find(c => c.stream_sub === rawCh)
  }
  if (hit) {
    const st = streamOf(hit)
    if (st) return { ...hit, stream: st, sub: wantSub }
    // 这一路没配子码流 → 回落主码流，并在诊断里说清楚
    return { ...hit, stream: hit.stream, sub: false, fellbackMain: wantSub }
  }

  // 4) 都没配或匹配不到 → 第一路"该码流可播"的
  const fallback = list.find(c => okOf(c) && streamOf(c))
                || list.find(c => okOf(c))
                || list[0]
  if (!fallback) return null
  const fst = streamOf(fallback) || fallback.stream
  return { ...fallback, stream: fst, sub: wantSub && !!streamOf(fallback) }
}

async function loadStream() {
  try {
    const r = await get(`/api/video/cameras?site=${encodeURIComponent(effectiveSite.value)}`)
    const list = r.items || []
    camList.value = list
    // 默认一路（老画面没配 ch 时用）
    // 优先「在线且浏览器能播」的；H.265 通道即使在线，flv.js 也解不了，跳过
    const first = list.find(c => c.online && c.browser_ok !== false)
               || list.find(c => c.online)
               || list.find(c => c.browser_ok !== false)
               || list[0]
    stream.value = first ? first.stream : ''
    isMock.value = first ? first.kind === 'mock' : false
    streamSrc.value = first ? (first.url || await liveUrl(first.stream)) : ''
  } catch (e) { stream.value = ''; camList.value = [] }
}

function goBack() { location.href = '/site/' + (rt && rt.site ? rt.site : '') }

// 14 号：只拉画面内容 + 重绘，不动 SSE 订阅（切画面时复用）
async function loadPageData(pid) {
  const p = await get(pageApi + pid)
  page.value = p
  const bad = findInvalidVar((p.json && p.json.items) || [])
  if (bad) {
    varError.value = `变量格式错误：「${bad.name || bad.type}」的 var 必须是 {"site":"S001","point":"LEVEL"} 对象，`
      + `当前为 ${JSON.stringify(bad.var)}。旧表达式格式已废弃，请重新关联变量。`
    return false
  }
  varError.value = ''
  return true
}

// 只读入口（/view/:id）和发布入口一样，现场电视没人登录。
// 没有 token 时数据接口会 401，页面就卡在「加载中…」。这里自动领一个只读 token。
async function ensureReadToken() {
  if (localStorage.getItem('token')) return
  try {
    const r = await get('/api/publish/token')
    if (r && r.token) localStorage.setItem('token', r.token)
  } catch (e) { /* 后端会在下面报具体错误 */ }
}

onMounted(async () => {
  ensureScadaStyles()
  await ensureReadToken()
  const ok = await loadPageData(pageId)
  if (!ok) return
  // 站点只认画面自身配置：URL 参数（编辑器预览/发布入口会带）> json.currentSite > 画面 site_id。
  // 不再用 localStorage 兜底 —— 每个画面绑自己的站点，全局兜底会把上一张画面的站点串过来。
  const site = resolveSite({
    query: route.query,
    page: {
      currentSite: page.value.json && page.value.json.currentSite,
      site_id: page.value.site_id
    }
  })
  curSite.value = site

  rt = new ScadaRuntime({
    site,
    onIssues: (list) => { issueCount.value = list.length },
    onSse: (ok) => { sseOk.value = ok }
  })
  rt.start()
  // 调试钩子：控制台 __rt.values / __rt.es.readyState 直接看运行时状态。
  // 生产留着无害，现场排「画面不动」时比翻 bundler 快得多。
  if (typeof window !== 'undefined') window.__rt = rt
  // 提示词 11：画面变量是 {site,point}，一张画面可以混排多站点 —— 把画面里出现的站点都订阅上
  rt.watchSites(collectVarSites((page.value.json && page.value.json.items) || []))
  ctrlEnv.rt = rt
  ctrlEnv.setSite(site)
  rt.subscribe(() => ctrlEnv.bump())

  // P8：模板与值列表先到位再画，否则实例首帧是「模板不存在」
  await rt.loadDefs()
  await loadStream()
  draw()

  hbTimer = setInterval(() => {
    if (stream.value) post('/api/video/heartbeat', { stream: stream.value }).catch(() => {})
  }, 30000)
  alTimer = setInterval(async () => {
    try {
      const r = await get('/api/alarms?state=0&size=6')
      alarms.value = r.items.map(a => `[${a.site_id}] ${a.msg}`)
    } catch (e) {}
  }, 5000)
})

// 14 号：发布入口切画面 —— 只重载 json 重绘，ScadaRuntime(SSE) 保持不动
// 这样点目录树不会断订阅，数值不闪
watch(() => props.pageIdProp, async (nv) => {
  if (!nv || String(nv) === String(pageId)) return
  pageId = nv
  const ok = await loadPageData(nv)
  if (!ok) return
  await loadStream()
  draw()
})

onUnmounted(() => {
  clearInterval(hbTimer); clearInterval(alTimer)
  if (box.value) { try { firePictureClose(box.value, evCtx()) } catch (e) { /* 关闭事件异常不影响卸载 */ } }
  if (rt) { rt.stop(); rt = null }
  destroyScada(box.value)
})
</script>

<style scoped>
.view-wrap { height: 100vh; background: #060d16; display: flex; flex-direction: column; }
.view-head { padding: 8px 16px; color: #9fc3e8; display: flex; justify-content: space-between; align-items: center; background: #0b1622; }
.view-canvas { flex: 1; overflow: hidden; position: relative; }
.bind-bar { display: flex; gap: 10px; align-items: center; padding: 8px 16px; background: #0b1622; }
</style>
