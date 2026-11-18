<template>
  <div class="publish" :class="{ collapsed }">
    <!-- 左侧目录树 -->
    <aside class="tree-wrap">
      <div class="tree-hd">
        <span class="ttl" v-if="!collapsed">监控画面</span>
        <span class="cnt" v-if="!collapsed && total">{{ total }} 张</span>
        <button class="fold-btn" :title="collapsed ? '展开目录' : '折叠目录'"
                @click="toggleCollapsed">{{ collapsed ? '▶' : '◀' }}</button>
      </div>

      <div class="tree-body">
        <el-tree
          v-if="treeData.length"
          ref="treeRef"
          :data="treeData"
          :props="{ label: 'label', children: 'children' }"
          node-key="key"
          :default-expanded-keys="expandedKeys"
          :highlight-current="true"
          :expand-on-click-node="false"
          @node-click="onNodeClick"
          @node-expand="onExpand"
          @node-collapse="onCollapse" />

        <div v-else class="empty-tree">
          还没有发布任何画面<br />
          <span class="dim">到「组态管理 → 画面列表」里点【发布】</span>
        </div>
      </div>

      <div class="tree-ft">
        <el-button size="small" @click="toggleFull">{{ isFull ? '退出全屏' : '全屏' }}</el-button>
        <el-button size="small" type="primary" @click="goBack">返回平台</el-button>
      </div>
    </aside>

    <!-- 右侧画面（纯渲染，无任何编辑 UI） -->
    <main class="pane" :class="{ 'site-offline': curSiteId && curSiteOnline === false }">
      <div v-if="curSiteId && curSiteOnline === false" class="offline-tip">
        站点 {{ curSiteName }} 离线 —— 采集已暂停，画面数据为最后一次有效值
      </div>
      <ViewPage v-if="curId" :page-id-prop="curId" :embedded="true" />
      <div v-else class="pane-empty">
        <div class="big">还没有发布任何画面</div>
        <div class="dim">管理员在「组态管理 → 画面列表」点【发布】后，这里会出现目录树</div>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { get } from '../utils/request'
import ViewPage from './ViewPage.vue'

const LS_KEY = 'publish.expanded'
// 左侧目录树手动折叠（用户 2026-11-14 要求）：折叠后画面占满整个右侧，
// 只留一条 30px 窄条 + ▶ 按钮，随时能点开，不会把操作员困在无目录的界面里。
const LS_FOLD = 'publish.collapsed'
const collapsed = ref(localStorage.getItem(LS_FOLD) === '1')
function toggleCollapsed() {
  collapsed.value = !collapsed.value
  localStorage.setItem(LS_FOLD, collapsed.value ? '1' : '0')
}

const route = useRoute()
const router = useRouter()
const treeRef = ref(null)
const groups = ref([])
const total = ref(0)
const curId = ref(null)
const sitesOnline = ref({})        // site_id -> true/false
let statusTimer = null

// 当前画面属于哪个站点、该站点是否在线
const curSiteId = computed(() => {
  for (const g of groups.value) {
    if ((g.pages || []).some(p => p.id === curId.value)) return g.site_id || ''
  }
  return ''
})
const curSiteName = computed(() => {
  for (const g of groups.value) {
    if ((g.pages || []).some(p => p.id === curId.value)) return g.site_name || g.site_id || ''
  }
  return ''
})
const curSiteOnline = computed(() => {
  const sid = curSiteId.value
  if (!sid) return null
  const v = sitesOnline.value[sid]
  return typeof v === 'boolean' ? v : null
})

// 站点在线状态：网关心跳写 Redis site:status，/api/sites 会带出来
async function loadSitesOnline() {
  try {
    const r = await get('/api/sites?size=500')
    const m = {}
    for (const s of (r.items || [])) m[s.id] = !!s.online
    sitesOnline.value = m
  } catch (e) { /* 读不到就保持上次状态，不弹错 */ }
}
const expandedKeys = ref([])
const isFull = ref(false)

const treeData = computed(() => groups.value.map(g => {
  const siteKey = `site:${g.site_id || 'none'}`
  return {
    key: siteKey,
    label: g.pages.length > 1 ? `${g.site_name} (${g.pages.length})` : g.site_name,
    isGroup: true,
    children: g.pages.map(p => ({
      key: `page:${p.id}`,
      label: p.id === curId.value ? `● ${p.name}` : p.name,
      isGroup: false,
      pageId: p.id,
    })),
  }
}))

async function loadTree() {
  try {
    const r = await get('/api/publish/tree')
    groups.value = r.groups || []
    total.value = r.total || 0
    restoreExpanded()
    // 默认选中：URL 指定 > 树里第一张
    const want = Number(route.params.id) || 0
    if (want) {
      const hit = groups.value.some(g => g.pages.some(p => p.id === want))
      curId.value = hit ? want : firstPageId()
    } else {
      curId.value = firstPageId()
    }
    // 让树高亮当前项（默认选中也要有视觉反馈）
    await nextTick()
    if (curId.value && treeRef.value) {
      treeRef.value.setCurrentKey(`page:${curId.value}`)
    }
  } catch (e) {
    groups.value = []
    total.value = 0
  }
}

function firstPageId() {
  for (const g of groups.value) {
    if (g.pages && g.pages.length) return g.pages[0].id
  }
  return null
}

function restoreExpanded() {
  // 默认全展开（除非存过折叠状态）
  let saved = null
  try { saved = JSON.parse(localStorage.getItem(LS_KEY) || 'null') } catch (e) { saved = null }
  if (Array.isArray(saved)) {
    expandedKeys.value = saved
  } else {
    // 首次：≤5 张的站点展开，>5 张的折叠（用户要求：站点下画面多时默认收起）
    expandedKeys.value = groups.value
      .filter(g => (g.pages || []).length <= 5)
      .map(g => `site:${g.site_id || 'none'}`)
  }
}

function saveExpanded() {
  try { localStorage.setItem(LS_KEY, JSON.stringify(expandedKeys.value)) } catch (e) {}
}

function onExpand(node) {
  if (!expandedKeys.value.includes(node.key)) {
    expandedKeys.value = [...expandedKeys.value, node.key]
    saveExpanded()
  }
}

function onCollapse(node) {
  expandedKeys.value = expandedKeys.value.filter(k => k !== node.key)
  saveExpanded()
}

function onNodeClick(node) {
  if (node.isGroup) return
  if (node.pageId) {
    curId.value = node.pageId
    // URL 同步（不刷新页面，便于收藏/分享）
    history.replaceState(null, '', `/publish/${node.pageId}`)
  }
}

function goBack() {
  // 用户明确要求：内嵌页必须有返回入口，不能困住
  if (window.history.length > 1 && document.referrer) router.back()
  else router.push('/')
}

async function toggleFull() {
  try {
    if (!document.fullscreenElement) {
      await document.documentElement.requestFullscreen()
      isFull.value = true
    } else {
      await document.exitFullscreen()
      isFull.value = false
    }
  } catch (e) { /* 用户拒绝或浏览器不支持，静默 */ }
}

function onFsChange() {
  isFull.value = !!document.fullscreenElement
}

function onKey(e) {
  if (e.key === 'f' || e.key === 'F') toggleFull()
}

// 发布态拿只读 token：现场电视没人登录，但数据接口要鉴权。
// 拿不到也不影响目录树（树和画面内容都是免登录接口），只是实时数值会空。
async function ensureToken() {
  if (localStorage.getItem('token')) return
  try {
    const r = await get('/api/publish/token')
    if (r && r.token) localStorage.setItem('token', r.token)
  } catch (e) { /* 没有已发布画面时会 404，忽略 */ }
}

// 画面内的「跳转画面」按钮会把 URL 推到 /publish/{id}，
// 此时组件是复用不是重挂，必须自己同步 curId 和树高亮
watch(() => route.params.id, async (nv) => {
  const pid = Number(nv)
  if (!pid || pid === curId.value) return
  curId.value = pid
  await nextTick()
  if (treeRef.value) treeRef.value.setCurrentKey(`page:${pid}`)
})

onMounted(async () => {
  await ensureToken()
  loadTree()
  // 站点在线状态：进页面先拉一次，之后每 10 秒刷新（离线要能实时变灰）
  loadSitesOnline()
  if (!statusTimer) statusTimer = setInterval(loadSitesOnline, 10000)
  document.addEventListener('fullscreenchange', onFsChange)
  window.addEventListener('keydown', onKey)
})

onUnmounted(() => {
  if (statusTimer) { clearInterval(statusTimer); statusTimer = null }
  document.removeEventListener('fullscreenchange', onFsChange)
  window.removeEventListener('keydown', onKey)
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {})
})
</script>

<style scoped>
.publish { display: flex; height: 100vh; background: #0b1622; overflow: hidden; }

/* 左树 */
.tree-wrap { width: 210px; flex: 0 0 210px; display: flex; flex-direction: column;
             background: #0e1c2a; border-right: 1px solid #16283c; }
.tree-hd { padding: 10px 12px 8px; display: flex; align-items: baseline; gap: 8px;
           border-bottom: 1px solid #16283c; }
.tree-hd .ttl { font-size: 14px; color: #cfe4f7; font-weight: 600; }
.tree-hd .cnt { font-size: 11px; color: #5f7f9f; }
.tree-body { flex: 1; overflow-y: auto; padding: 6px 4px; }
.tree-ft { padding: 8px; border-top: 1px solid #16283c; display: flex; gap: 6px; }
.tree-ft .el-button { flex: 1; }
.empty-tree { padding: 20px 12px; color: #6b8cb0; font-size: 12px; line-height: 1.9; text-align: center; }

/* 右侧画面 */
/* 目录树折叠（用户 2026-11-14 要求）：可手动折叠 / 展开，折叠时右侧画面占满 */
.tree-wrap { transition: width .18s ease, flex-basis .18s ease; }
.publish.collapsed .tree-wrap { width: 30px; flex: 0 0 30px; }
.publish.collapsed .tree-hd { padding: 8px 0; justify-content: center; }
.publish.collapsed .tree-body,
.publish.collapsed .tree-ft { display: none; }
.fold-btn { margin-left: auto; background: transparent; border: 1px solid #24405c;
            color: #7cc4ff; border-radius: 3px; width: 20px; height: 20px; line-height: 1;
            font-size: 10px; cursor: pointer; padding: 0; flex: 0 0 auto; }
.fold-btn:hover { background: #16283c; border-color: #1ec8ff; }
.publish.collapsed .fold-btn { margin-left: 0; }

.pane { flex: 1; min-width: 0; position: relative; background: #0b1622; overflow: hidden; }
.pane-empty { height: 100%; display: flex; flex-direction: column; align-items: center;
              justify-content: center; gap: 10px; }
.pane-empty .big { font-size: 16px; color: #6b8cb0; }
.pane-empty .dim { font-size: 12px; color: #47596b; }
.dim { color: #47596b; }

/* el-tree 深色适配 */
:deep(.el-tree) { background: transparent; color: #9fc3e8; font-size: 13px; }
:deep(.el-tree-node__content) { height: 30px; border-radius: 3px; }
:deep(.el-tree-node__content:hover) { background: #16283c; }
:deep(.el-tree-node.is-current > .el-tree-node__content) { background: #1d3a56; color: #e6f2ff; }
:deep(.el-tree-node__expand-icon) { color: #5f7f9f; }

/* 站点离线：整个画面区灰度显示（用户 2026-11 要求） */
.pane.site-offline { filter: grayscale(1) opacity(0.75); }
.offline-tip {
  position: absolute; top: 0; left: 0; right: 0; z-index: 20;
  padding: 6px 12px; font-size: 12px; text-align: center;
  background: rgba(245, 108, 108, .92); color: #fff;
  filter: none; pointer-events: none;
}
</style>
