<template>
  <div ref="edEl" class="ed">
    <!-- 顶栏 -->
    <div class="topbar">
      <div class="pname" title="点击改名" @click="renamePage">
        {{ page.name || ('#' + pageId) }}
        <span class="pen">✎</span>
      </div>
      <el-tag v-if="isFpt" size="small" type="success" effect="dark">组件模板</el-tag>
      <el-tag v-else-if="page.kind === 'template'" size="small" type="warning" effect="dark">模板</el-tag>
      <el-tag v-else-if="page.site_id" size="small" effect="dark">{{ page.site_id }}</el-tag>
      <span v-if="dirty" class="dirty">● 未保存</span>
      <el-tag v-if="issueCount" type="warning" size="small" effect="dark"
              :title="'有 ' + issueCount + ' 条动态化绑定取不到值（画布上标黄），请检查变量名或点位表'">
        {{ issueCount }} 个绑定异常
      </el-tag>
      <el-tag v-if="staleVars.length" type="danger" size="small" effect="dark" class="stale-tag"
              :title="'绑定的点位不存在或已停用，保存会被拒绝：' + staleText"
              @click="onShowStale">
        {{ staleVars.length }} 个变量已失效
      </el-tag>

      <span class="sep"></span>

      <el-button size="small" type="primary" :loading="saving" :disabled="saving" @click="save()">
        保存
      </el-button>
      <el-button size="small" :disabled="!canUndo" title="Ctrl+Z" @click="doUndo">撤销</el-button>
      <el-button size="small" :disabled="!canRedo" title="Ctrl+Y" @click="doRedo">重做</el-button>

      <span class="sep"></span>

      <el-button size="small" :type="grid ? 'primary' : ''" :plain="grid" @click="toggleGrid">
        网格{{ grid ? '开' : '关' }}
      </el-button>

      <span class="sep"></span>

      <!-- 对齐/分布（P7）：单选 = 相对画布，多选 = 相对基准 -->
      <span class="tools" title="对齐">
        <button v-for="t in ALIGN" :key="t.k" class="ico"
                :disabled="!selItems.length" :title="t.t + '（' + (selItems.length > 1 ? '多选' : '相对画布') + '）'"
                @click="doAlign(t.k)" v-html="t.svg"></button>
      </span>
      <el-select v-model="alignBase" size="small" class="base" title="对齐基准（多选时生效）">
        <el-option value="last" label="基准：最后选中" />
        <el-option value="bbox" label="基准：包围盒" />
      </el-select>
      <span class="tools" title="分布">
        <button v-for="t in DIST" :key="t.k" class="ico"
                :disabled="selItems.length < 3" :title="t.t + '（至少选 3 个）'"
                @click="doDistribute(t.k)" v-html="t.svg"></button>
      </span>

      <span class="sep"></span>

      <el-button v-if="isFpt" size="small" type="success" plain class="btn-iface"
                 :title="'定义模板的接口变量（实例上用 @变量名 引用）'" @click="openIface">
        接口变量（{{ iface.length }}）
      </el-button>
      <!-- 需求 2026-11-14：画布尺寸任何画面都能改（原来只对模板开放） -->
      <el-button size="small" class="btn-fptsize" @click="resizeFpt"
                 title="画布尺寸（宽x高，像素）">
        {{ json.width }}×{{ json.height }}
      </el-button>

      <span class="sep"></span>

      <span class="tools" title="组合">
        <button class="ico" :disabled="selItems.length < 2" title="组合（Ctrl+G）"
                @click="doGroup" v-html="ICON.group"></button>
        <button class="ico" :disabled="!hasGroup" title="取消组合（Ctrl+Shift+G）"
                @click="doUngroup" v-html="ICON.ungroup"></button>
      </span>

      <span class="sep"></span>

      <el-button v-if="!isFpt" size="small" type="primary" plain @click="newPage">新建</el-button>
      <el-dropdown v-if="!isFpt" trigger="click" @command="goPage">
        <el-button size="small">打开<span class="caret" style="margin-left:4px">▾</span></el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-for="pg in pageList" :key="pg.id" :command="pg.id"
                              :disabled="Number(pg.id) === Number(pageId)">
              {{ pg.id }} · {{ pg.name }}
            </el-dropdown-item>
            <el-dropdown-item v-if="!pageList.length" disabled>暂无其它画面</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <el-button size="small" @click="preview">预览</el-button>
      <el-button size="small" class="btn-back" @click="back">返回总览</el-button>

      <span class="grow"></span>

      <!-- 视图缩放：显示实际像素比例，点开可回 100% 或适应窗口 -->
      <el-dropdown trigger="click" @command="setZoom">
        <span class="zoom" title="Ctrl+滚轮缩放画布，点击选择比例">
          {{ zoomPct }}%
          <span class="caret">▾</span>
        </span>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="50">50%</el-dropdown-item>
            <el-dropdown-item command="75">75%</el-dropdown-item>
            <el-dropdown-item command="100">100%</el-dropdown-item>
            <el-dropdown-item command="custom" divided>自定义…</el-dropdown-item>
            <el-dropdown-item command="fit">适应窗口</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>

      <span class="sep"></span>

      <span class="site-ctx" title="站点上下文：P4 间接变量连接按它解析">
        <span class="at">@CurrentSite</span>
        <el-select v-model="curSite" size="small" filterable clearable placeholder="选择站点"
                   style="width:170px" @change="onSiteChange">
          <el-option v-for="s in sites" :key="s.id" :value="s.id" :label="s.id + ' ' + s.name" />
        </el-select>
        <span v-if="!curSite" class="warn">未选</span>
      </span>
    </div>

    <!-- 三栏 -->
    <div class="main">
      <aside class="left" :style="{ width: leftW + 'px' }">
        <!-- 10 §4.4：开发阶段只有一张画面，左栏不再放画面树（没有列表/新建/复制/删除入口） -->
        <div class="pane pane-info">
          <div class="pane-hd">画面信息</div>
          <div class="pane-bd info">
            <div class="ir"><span>名称</span><b :title="page.name">{{ page.name || ('#' + pageId) }}</b></div>
            <div class="ir"><span>编号</span><b>id = {{ pageId }}</b></div>
            <div class="ir"><span>尺寸</span><b>{{ json.width }} × {{ json.height }}</b></div>
            <div class="ir"><span>对象</span><b>{{ (json.items || []).length }} 个</b></div>
            <div class="ir"><span>状态</span><b :class="{ unsaved: dirty }">{{ dirty ? '未保存' : '已保存' }}</b></div>
            <div class="ir"><span>更新</span><b>{{ page.updated_at || '—' }}</b></div>
            <div class="ihint">
              保存写入 <code>PUT /api/page/{{ pageId }}</code>；顶部【新建】可加新画面、
              【打开】可切换。
            </div>
          </div>
        </div>
        <div class="pane" style="flex:1 1 auto;border-top:1px solid #16283d">
          <div class="pane-hd tabs">
            <span class="tab" :class="{ on: leftTab === 'palette' }" @click="setTab('palette')">对象库</span>
            <span class="tab" :class="{ on: leftTab === 'layer' }" @click="setTab('layer')">图层</span>
          </div>
          <div class="pane-bd">
            <ObjectPalette v-show="leftTab === 'palette'" ref="paletteRef" :faceplates="fptList" @pick="onPick" />
            <LayerPanel v-show="leftTab === 'layer'" :items="json.items" :layers="json.layers || []"
                        :cur-layer="curLayer" :sel="selItems"
                        @select="onLayerSelect" @toggleHidden="onToggleHidden" @toggleLock="onToggleLock"
                        @zorder="doZ" @reorder="onLayerReorder" @addLayer="addLayer" @setLayer="setLayer"
                        @rename="onLayerRename" />
          </div>
        </div>
      </aside>

      <div class="vbar" title="拖动调整宽度" @mousedown="startDrag('left', $event)"></div>

      <section class="center">
        <div ref="canvasWrap" class="canvas-wrap"
             :class="{ placing: !!pendingDef }"
             @click="onCanvasClick" @dragover.prevent @drop="onDrop">
          <div ref="canvas" class="canvas"></div>
          <div v-show="grid" ref="gridEl" class="grid-layer"></div>
          <div v-if="pendingDef" class="placing-tip">
            十字光标已激活：在画布单击一次落位「{{ pendingDef.name }}」（Esc 取消）
          </div>
          <div ref="readoutEl" class="drag-readout"></div>
          <div v-if="editGroupName" class="grp-tip">
            正在组内编辑「{{ editGroupName }}」：可单独选中子对象，Esc 退出
            <button class="gt-x" @click="exitGroup">退出</button>
          </div>
          <div class="preview-tag" :class="{ live: !!curSite }" :title="curSite
            ? ('正在按站点 ' + curSite + ' 的实时值预览；切换上方 @CurrentSite 立即换站')
            : '还没选站点：数值是演示数据，不是现场实时值'">{{ curSite ? ('实时 · ' + curSite) : '演示数据（未选站点）' }}</div>
        </div>
      </section>

      <div v-show="!rightFold" class="vbar" title="拖动调整宽度" @mousedown="startDrag('right', $event)"></div>

      <aside v-show="!rightFold" class="right" :style="{ width: rightW + 'px' }">
        <PropPanel :items="selItems" :all="json.items" :page-w="json.width" :page-h="json.height"
                   :sites="sites" :cur-site="curSite" :rt="rt" :ev-ctx="evCtx"
                   :channels="channels" :pages="pageOptions"
                   :resolve-cam="pickCamEditor"
                   :stale="staleTags"
                   @preview="onPropPreview" @commit="onPropCommit" @collapse="toggleRight"
                   @save="save()" />
      </aside>

      <!-- 面板收起后画布自动撑满，留一个窄把手可以再展开 -->
      <button v-if="rightFold" class="unfold" title="展开属性面板" @click="toggleRight">属性</button>

      <!-- P6：双击控件打开配置对话框（配置项太多，塞不进 280px 的属性面板） -->
      <ControlDialog v-model="ctrlDlg" :item="ctrlItem" :sites="sites" :cur-site="curSite"
                     @save="onCtrlSave" />

      <!-- P8：组件模板的接口变量定义（官方 4.6.2.5） -->
      <el-dialog v-model="ifaceDlg" title="定义接口变量" width="660px" append-to-body>
        <div class="ift">
          <div class="ift-h">
            模板内部的对象用 <code>@变量名</code> 引用（如液位罐高度 <code>@PV</code>、指示灯 <code>@RUN</code>），
            实例上再把每个变量绑成实际点位。名字字母/下划线开头，最长 16 位；<code>@CurrentSite</code> 是运行时关键字，不能占用。
          </div>
          <table class="ift-t">
            <thead><tr><th>变量名</th><th>类型</th><th>默认值</th><th>说明</th><th></th></tr></thead>
            <tbody>
              <tr v-for="(t, i) in ifaceEdit" :key="i">
                <td><input v-model="t.name" class="ift-in mono ift-name" placeholder="PV"></td>
                <td>
                  <select v-model="t.type" class="ift-sel">
                    <option value="real">real</option><option value="bool">bool</option>
                    <option value="int">int</option><option value="string">string</option>
                  </select>
                </td>
                <td><input v-model="t.default" class="ift-in" placeholder="0"></td>
                <td><input v-model="t.desc" class="ift-in" placeholder="液位"></td>
                <td><button class="ift-x" title="删除" @click="ifaceEdit.splice(i, 1)">×</button></td>
              </tr>
            </tbody>
          </table>
          <button class="ift-add" @click="ifaceEdit.push({ name: '', type: 'real', default: 0, desc: '' })">
            ＋ 增加一行
          </button>
        </div>
        <template #footer>
          <el-button @click="ifaceDlg = false">取消</el-button>
          <el-button type="primary" class="ift-ok" @click="saveIface">确定</el-button>
        </template>
      </el-dialog>
    </div>
  </div>
</template>

<script setup>
// 组态编辑器：P1 三栏骨架 + P2 画布交互（选中/拖拽/缩放/多选/撤销）
// 画布渲染沿用 scada/render.js（编辑器与只读页共用同一份渲染）
// 交互逻辑全部在 scada/canvas.js，本文件只做装配
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { get, post, put } from '../utils/request'
import { renderScada, destroyScada, ensureScadaStyles } from '../scada/render'
import { CanvasInteract, GRID_SIZE } from '../scada/canvas'
import { typeLabel, defaultName, ensureNames } from '../scada/props'
import ObjectPalette from '../scada/ObjectPalette.vue'
import PropPanel from '../scada/PropPanel.vue'
import { ScadaRuntime, resolveTags } from '../scada/runtime'
import { attachEvents, fireAttrChange, firePictureClose } from '../scada/events'
import { makeEnv } from '../scada/controls/env'
import { controlDef, newControlItem } from '../scada/controls/registry'
import { symbolName } from '../scada/controls/symbols'
import ControlDialog from '../scada/ControlDialog.vue'
import LayerPanel from '../scada/LayerPanel.vue'
import { MAX_LAYERS, defaultLayers, nextLayerId } from '../scada/arrange'
import { paintThumb } from '../scada/thumb'
import { tagOfVar, collectVarSites } from '../scada/varbind'

const route = useRoute()
const router = useRouter()

// 提示词 10 §4.4：开发阶段组态只有一张固定画面（page.id=1）。
// 画面列表 / 新建 / 复制 / 删除的入口全部去掉，保存固定 PUT /api/page/1。
const PAGE_ID = 1
// 组件模板路由（/scada/fpt/:id）在 4.4 里一并移除，这里恒为 false，
// 下面 isFpt 分支保留是给正式版恢复模板时用的，当前不会执行。
const isFpt = ref(false)
const pageId = ref(Number(route.params.id) || PAGE_ID)
const pageList = ref([])

async function loadPageList() {
  try {
    const r = await get('/api/pages?kind=scada&size=200')
    pageList.value = (r.items || []).filter(x => x.kind === 'scada')
  } catch (e) { pageList.value = [] }
}

function goPage(id) {
  if (dirty.value && !confirm('当前画面有未保存的修改，确定切换？')) return
  router.push('/scada/editor/' + id)
}

async function newPage() {
  if (dirty.value && !confirm('当前画面有未保存的修改，确定新建？')) return
  let name
  try {
    const r = await ElMessageBox.prompt('给新画面起个名字', '新建组态画面', {
      inputValue: '新画面 ' + (pageList.value.length + 1),
      confirmButtonText: '创建', cancelButtonText: '取消',
      inputValidator: v => (v && v.trim() ? true : '名称不能为空')
    })
    name = r.value.trim()
  } catch (e) { return }        // 取消
  try {
    const blank = {
      width: 1600, height: 900, bg: '#0b1622', items: [],
      currentSite: curSite.value || ''
    }
    const r = await post('/api/page', {
      name, kind: 'scada', site_id: curSite.value || null, json: blank
    })
    const nid = r && (r.id || (r.data && r.data.id))
    if (!nid) throw new Error('后端没返回画面 id')
    ElMessage.success('已创建「' + name + '」')
    await loadPageList()
    dirty.value = false
    router.push('/scada/editor/' + nid)
  } catch (e) {
    ElMessage.error((e && e.message) || '新建失败')
  }
}
const page = ref({})
const json = ref({ width: 1600, height: 900, bg: '#0b1622', items: [] })
const sites = ref([])
const curSite = ref('')
// 该站点的通道清单（给属性面板「视频通道」下拉用）
const channels = ref([])

// 所有组态画面（给属性面板「跳转画面」下拉用）
const pageOptions = ref([])
async function loadPageOptions() {
  try {
    const r = await get('/api/pages?kind=scada')
    pageOptions.value = r.items || []
  } catch (e) {
    pageOptions.value = []
  }
}

async function loadChannels() {
  if (!curSite.value) { channels.value = []; return }
  try {
    const r = await get(`/api/video/site-channels?site=${encodeURIComponent(curSite.value)}`)
    channels.value = r.items || []
  } catch (e) {
    channels.value = []
  }
}
// 编辑器里的「这个视频窗会连哪一路」：逻辑必须和运行态 ViewPage.pickCam 一致，
// 否则属性页诊断行显示的和实际播放的不是一回事。
function pickCamEditor(it) {
  const list = channels.value || []
  if (!list || !list.length) return null
  const wantSub = String(it.chStream || 'main') === 'sub'
  const manual = String(it.chManual || '').trim()
  if (manual) {
    const hit = list.find(c => c.stream === manual || c.stream_sub === manual)
    if (hit) {
      const st = wantSub ? (hit.stream_sub || hit.stream) : (hit.stream || hit.stream_sub)
      return { ...hit, stream: st, sub: wantSub, manual: true }
    }
    return { stream: manual, sub: wantSub, manual: true, browser_ok: true,
             browser_ok_sub: true, codec: '', codec_sub: '', name: '' }
  }
  const streamOf = (c) => (wantSub ? (c.stream_sub || '') : (c.stream || ''))
  const okOf = (c) => (wantSub ? (c.browser_ok_sub !== false) : (c.browser_ok !== false))
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
    return { ...hit, stream: hit.stream, sub: false, fellbackMain: wantSub }
  }
  const fb = list.find(c => okOf(c) && streamOf(c)) || list.find(c => okOf(c)) || list[0]
  if (!fb) return null
  return { ...fb, stream: streamOf(fb) || fb.stream, sub: wantSub && !!streamOf(fb) }
}

const selItems = ref([])
const saving = ref(false)
const dirty = ref(false)
const canUndo = ref(false)
const canRedo = ref(false)
const zoomPct = ref(100)
const pendingDef = ref(null)
// 网格默认开（WinCC 手感：拖拽自动吸附 20px），状态记在 localStorage
const grid = ref(localStorage.getItem('scada.grid') !== '0')
// P7：左栏页签（对象库 / 图层）、当前图层带、对齐基准、组内编辑提示
const leftTab = ref(localStorage.getItem('scada.leftTab') || 'palette')
const curLayer = ref(1)
const alignBase = ref(localStorage.getItem('scada.alignBase') || 'last')
const editGroupName = ref('')
// P8 组件模板：模板清单（对象库用）、接口变量、定义弹窗
const fptList = ref([])
const iface = ref([])
const ifaceDlg = ref(false)
const ifaceEdit = ref([])
const hasGroup = computed(() => (json.value.items || []).some(it => it.type === 'group'))

const edEl = ref(null)
const canvas = ref(null)
const canvasWrap = ref(null)
const gridEl = ref(null)
const readoutEl = ref(null)
const paletteRef = ref(null)

const leftW = ref(Number(localStorage.getItem('scada.leftW')) || 240)
const rightW = ref(Number(localStorage.getItem('scada.rightW')) || 300)
// 属性面板折叠：窄屏（<1400px）默认收起，画布撑满；用户手动选择后按选择来
const _fold = localStorage.getItem('scada.rightFold')
const rightFold = ref(_fold === null ? window.innerWidth < 1400 : _fold === '1')

let ci = null   // CanvasInteract 实例
let rt = null   // ScadaRuntime：实时值 + 动态化求值（P4）
const issueCount = ref(0)
const sseOk = ref(false)

// 10 §4.3 规则 3：绑了变量但点位不存在/已停用 → 属性面板标红 + 保存阻断
const ptIndex = ref({})        // { S001: Set(点位编码) }；null = 没查到（不误报）
const staleVars = ref([])      // [{ site, point, tag }]
const staleText = computed(() => staleVars.value.slice(0, 5).map(v => v.tag).join('、')
  + (staleVars.value.length > 5 ? ' 等 ' + staleVars.value.length + ' 个' : ''))
const staleTags = computed(() => staleVars.value.map(v => v.tag))

// 未选站点时的演示值：画布不能一片空白，但角标会明确写「演示数据」。
// 一旦选了 @CurrentSite，就全部走实时值，演示值不再参与。
const demoVals = {
  LEVEL: { val: 3.2 }, PUMP1_RUN: { val: 1 }, PUMP2_RUN: { val: 0 },
  PH: { val: 7.2 }, FLOW: { val: 320 }, DO: { val: 4.8 }, TEMP: { val: 23.5 }
}
const renderVals = () => (rt && rt.site ? rt.flat() : demoVals)

const ALIGN = [
  { k: 'l', t: '左对齐', svg: '<svg viewBox="0 0 16 16"><path d="M2 1v14" stroke="currentColor"/><rect x="5" y="3" width="8" height="3" fill="currentColor" opacity=".6"/><rect x="5" y="10" width="5" height="3" fill="currentColor" opacity=".6"/></svg>' },
  { k: 'hc', t: '水平居中', svg: '<svg viewBox="0 0 16 16"><path d="M8 1v14" stroke="currentColor"/><rect x="3" y="3" width="10" height="3" fill="currentColor" opacity=".6"/><rect x="5" y="10" width="6" height="3" fill="currentColor" opacity=".6"/></svg>' },
  { k: 'r', t: '右对齐', svg: '<svg viewBox="0 0 16 16"><path d="M14 1v14" stroke="currentColor"/><rect x="3" y="3" width="8" height="3" fill="currentColor" opacity=".6"/><rect x="6" y="10" width="5" height="3" fill="currentColor" opacity=".6"/></svg>' },
  { k: 't', t: '顶对齐', svg: '<svg viewBox="0 0 16 16"><path d="M1 2h14" stroke="currentColor"/><rect x="3" y="5" width="3" height="8" fill="currentColor" opacity=".6"/><rect x="10" y="5" width="3" height="5" fill="currentColor" opacity=".6"/></svg>' },
  { k: 'vc', t: '垂直居中', svg: '<svg viewBox="0 0 16 16"><path d="M1 8h14" stroke="currentColor"/><rect x="3" y="3" width="3" height="10" fill="currentColor" opacity=".6"/><rect x="10" y="5" width="3" height="6" fill="currentColor" opacity=".6"/></svg>' },
  { k: 'b', t: '底对齐', svg: '<svg viewBox="0 0 16 16"><path d="M1 14h14" stroke="currentColor"/><rect x="3" y="3" width="3" height="8" fill="currentColor" opacity=".6"/><rect x="10" y="6" width="3" height="5" fill="currentColor" opacity=".6"/></svg>' }
]

// 分布四件（多选、至少 3 个）
const DIST = [
  { k: 'x', t: '水平等距', svg: '<svg viewBox="0 0 16 16"><rect x="1" y="5" width="3" height="6" fill="currentColor" opacity=".6"/><rect x="6.5" y="5" width="3" height="6" fill="currentColor" opacity=".6"/><rect x="12" y="5" width="3" height="6" fill="currentColor" opacity=".6"/></svg>' },
  { k: 'y', t: '垂直等距', svg: '<svg viewBox="0 0 16 16"><rect x="5" y="1" width="6" height="3" fill="currentColor" opacity=".6"/><rect x="5" y="6.5" width="6" height="3" fill="currentColor" opacity=".6"/><rect x="5" y="12" width="6" height="3" fill="currentColor" opacity=".6"/></svg>' },
  { k: 'eqw', t: '等宽', svg: '<svg viewBox="0 0 16 16"><rect x="2" y="3" width="12" height="4" fill="currentColor" opacity=".6"/><rect x="2" y="9" width="12" height="4" fill="currentColor" opacity=".6"/></svg>' },
  { k: 'eqh', t: '等高', svg: '<svg viewBox="0 0 16 16"><rect x="2" y="2" width="4" height="12" fill="currentColor" opacity=".6"/><rect x="10" y="2" width="4" height="12" fill="currentColor" opacity=".6"/></svg>' }
]

const ICON = {
  group: '<svg viewBox="0 0 16 16"><rect x="1.5" y="1.5" width="13" height="13" fill="none" stroke="currentColor" stroke-dasharray="2 2"/><rect x="3.5" y="3.5" width="5" height="5" fill="currentColor" opacity=".6"/><rect x="7.5" y="7.5" width="5" height="5" fill="currentColor" opacity=".6"/></svg>',
  ungroup: '<svg viewBox="0 0 16 16"><rect x="2" y="2" width="5" height="5" fill="currentColor" opacity=".6"/><rect x="9" y="9" width="5" height="5" fill="currentColor" opacity=".6"/><path d="M8.5 4.5 12 8" stroke="currentColor" stroke-dasharray="2 2"/></svg>'
}

const typeName = typeLabel

// —— 加载 ——
async function loadSites() {
  try {
    // size 给足：现在 200 个站点，@CurrentSite 要能全列出来
    const r = await get('/api/sites?size=500')
    sites.value = r.items || []
  } catch (e) { /* 上面已提示 */ }
}

// —— 10 §4.3：变量有效性检查（点位被删/停用 → 标红 + 禁止保存）——
// 只查画面里真正用到的站点，每站查一次后缓存；查不到（网络/权限）不算失效，不误报。
async function ensurePointIndex(siteIds) {
  const need = (siteIds || []).filter(s => s && ptIndex.value[s] === undefined)
  await Promise.all(need.map(async (s) => {
    try {
      const r = await get('/api/points?site_id=' + encodeURIComponent(s) + '&size=2000')
      ptIndex.value[s] = new Set((r.items || []).filter(p => p.enabled !== 0).map(p => p.code))
    } catch (e) {
      ptIndex.value[s] = null
    }
  }))
}

async function checkStaleVars() {
  const found = []
  const walk = (arr) => {
    for (const it of arr || []) {
      if (it && it.var && typeof it.var === 'object' && !Array.isArray(it.var)) {
        const site = String(it.var.site || '').trim()
        const point = String(it.var.point || '').trim()
        if (site && point) found.push({ site, point, tag: site + '.' + point })
      }
      if (it && Array.isArray(it.items)) walk(it.items)
    }
  }
  walk(json.value.items)
  await ensurePointIndex([...new Set(found.map(v => v.site))])
  const known = new Set((sites.value || []).map(s => s.id))
  const bad = []
  const seen = new Set()
  for (const v of found) {
    if (seen.has(v.tag)) continue
    const set = ptIndex.value[v.site]
    // 站点表里没这个站 → 失效；站点存在但点位索引拿不到（null）→ 不判断
    const dead = known.size ? (!known.has(v.site) || (set && !set.has(v.point))) : (set && !set.has(v.point))
    if (dead) { bad.push(v); seen.add(v.tag) }
  }
  staleVars.value = bad
  return bad
}

async function loadPage(id, force) {
  if (!force && dirty.value) return
  // 多画面：按路由 id 加载；画面不存在时提示并回列表，不静默变成空画面
  if (!id) {
    ElMessage.warning('缺少画面编号')
    id = PAGE_ID
  }
  let d = {}
  let siteId = ''
  if (isFpt.value) {
    const f = await get('/api/fpt/' + id)
    page.value = { id: f.id, name: f.name, kind: 'fpt', site_id: '', locked: f.locked }
    d = (f.json && typeof f.json === 'object') ? f.json : {}
    iface.value = Array.isArray(f.iface) ? f.iface : []
    pageId.value = id
  } else {
    const p = await get('/api/page/' + id)
    page.value = p
    d = p.json && typeof p.json === 'object' ? p.json : {}
    siteId = p.site_id || ''
  }
  const W = isFpt.value ? 200 : 1600
  const H = isFpt.value ? 200 : 900
  json.value = {
    width: d.width || (isFpt.value ? (page.value.w || W) : W),
    height: d.height || (isFpt.value ? (page.value.h || H) : H),
    bg: d.bg || (isFpt.value ? 'transparent' : '#0b1622'),
    items: Array.isArray(d.items) ? d.items : [],
    // P7：图层带随画面一起存（官方 4.5.13 最多 32 层）
    layers: Array.isArray(d.layers) && d.layers.length ? d.layers : defaultLayers()
  }
  ensureLayers()
  // 老画面没有对象名：按类型编号补齐（保存时随 json 落库，P3 起画面内名称唯一）
  ensureNames(json.value.items)
  curSite.value = isFpt.value ? '' : (d.currentSite || siteId)
  if (rt) rt.setSite(curSite.value)
  // 提示词 11：画面里 {site,point} 变量涉及的站点全部订阅（跨站点画面编辑时也有实时值）
  if (rt) rt.watchSites(collectVarSites(json.value.items || []))
  dirty.value = false
  pageId.value = id
  if (ci) {
    ci.history.clear()
    ci.setSel([])
    canUndo.value = false
    canRedo.value = false
  }
  await nextTick()
  draw()
  // 4.3：打开画面就把「点位被删/停用」的绑定标出来，别等保存时才炸
  checkStaleVars()
}
// —— 渲染 ——
let stageRef = null
let stageRo = null

// P6 控件环境：编辑态 mode='edit' —— 控件照常显示数据，但内部交互按键不渲染
const ctrlEnv = makeEnv({ mode: 'edit', rt: null, site: '' })
const ctrlDlg = ref(false)
const ctrlItem = ref(null)

// 事件上下文（P5）：编辑态 interactive=false —— 点对象是选中，不能顺手写现场；
// 但右栏「测试」按钮走 testEvent，直接执行一次，不用切运行态。
const evCtx = {
  container: null,
  rt: null,                       // 下面 onMounted 里回填
  interactive: false,
  onToast: (text, type) => ElMessage({ message: text, type: type || 'info' }),
  resolveTags,
  rebind: () => { if (canvas.value) attachEvents(canvas.value, evCtx) }
}

function draw() {
  if (!canvas.value) return
  ensureScadaStyles()
  renderScada(canvas.value, json.value, renderVals(), {
    zoom: ci ? ci.zoom : 1,
    onFit: (s, base) => {
      if (ci) { ci.effScale = s; ci.baseScale = base }
      zoomPct.value = Math.round(s * 100)
    },
    // 按钮对象：写点位（走既有 /api/write，权限与审计都在后端）
    // 返回 Promise：I/O 域输入框要按成功/失败闪绿闪红，不能吞掉结果
    onWrite: (code, val) => {
      if (!rt || !rt.site) {
        ElMessage.warning('先选站点再下发')
        return Promise.reject(new Error('未选站点，不能下发'))
      }
      return rt.write(code, val).then((r) => { ElMessage.success('已下发'); return r })
    },
    // 修复 09：I/O 域输入态（编辑态只读，但 rw 判断与取值要一致）
    site: () => curSite.value,
    readValue: (t) => { const r = rt ? rt.read(t) : null; return r && r.found ? r.val : undefined },
    // 提示词 11：渲染器统一三态取值（q/ts 一起给，跨站点对象 var 走这里）
    readFull: (t) => (rt ? rt.read(t) : null),
    // 视频窗属性页诊断行用（和运行态同一套逻辑）
    resolveCam: (it) => pickCamEditor(it),
    // 编辑态：I/O 域可编辑（画布上另外用 inert 禁交互，避免点对象就进输入框）
    canWrite: true,
    kiosk: false,
    rwOf: (t) => (rt ? rt.rwOf(t) : null),
    // P6 控件：编辑态也照常显示数据，好让人看见"长什么样"再调尺寸
    mode: 'edit',
    ctrlEnv,
    // P8：组件模板实例渲染时实时取模板定义（改模板 → 所有实例同步变）
    fpt: rt ? rt.fpt : new Map(),
    onControlDblClick: (item) => openCtrlDlg(item)
  })
  if (rt) rt.attach(canvas.value)
  evCtx.container = canvas.value
  evCtx.rt = rt
  attachEvents(canvas.value, evCtx)
  const stage = canvas.value.querySelector('.scada-stage')
  if (stage !== stageRef) {
    stageRef = stage
    if (stageRo) { try { stageRo.disconnect() } catch (e) { /* 已断开 */ } }
    if (stage && typeof ResizeObserver !== 'undefined') {
      // 容器尺寸变化后选中框/控制点要重新贴位
      stageRo = new ResizeObserver(() => { syncGrid(); if (ci) ci.layoutSelection() })
      stageRo.observe(stage)
    }
  }
  syncGrid()
  if (ci) ci.layoutSelection()
}

function syncGrid() {
  const el = gridEl.value
  const st = canvas.value && canvas.value.querySelector('.scada-stage')
  if (!el || !st || !canvasWrap.value) return
  const r = st.getBoundingClientRect()
  const c = canvasWrap.value.getBoundingClientRect()
  el.style.left = (r.left - c.left) + 'px'
  el.style.top = (r.top - c.top) + 'px'
  el.style.width = r.width + 'px'
  el.style.height = r.height + 'px'
  const s = r.width / (json.value.width || 1600)
  el.style.backgroundSize = `${GRID_SIZE * s}px ${GRID_SIZE * s}px`
}

function toggleGrid() {
  grid.value = !grid.value
  localStorage.setItem('scada.grid', grid.value ? '1' : '0')
  if (grid.value) nextTick(syncGrid)
}

// —— 缩放 ——
async function setZoom(cmd) {
  if (!ci) return
  if (cmd === 'fit') { ci.fitWindow(); return }
  if (cmd === 'custom') {
    // 用户 2026-11-14：分辨率/显示比例的参数要能自定义，不再只有 50/75/100 三档。
    try {
      const { value } = await ElMessageBox.prompt('显示比例（百分比，10~800）', '自定义比例', {
        inputValue: String(Math.round((ci.effScale || 1) * 100)),
        inputPattern: /^\s*\d{1,3}(\.\d+)?\s*$/,
        inputErrorMessage: '请输入 10~800 之间的数字，例如 66 或 125',
        confirmButtonText: '确定', cancelButtonText: '取消'
      })
      const pct = Number(value)
      if (!isFinite(pct) || pct < 10 || pct > 800) {
        ElMessage.warning('比例范围 10~800')
        return
      }
      ci.setScalePct(pct)
    } catch (e) { /* 取消 */ }
    return
  }
  ci.setScalePct(Number(cmd))
}

// —— 插入对象（点选 → 画布单击落位；符号库支持拖放）——
function onPick(def) { pendingDef.value = def }

function posFromEvent(e) {
  const st = canvas.value && canvas.value.querySelector('.scada-stage')
  if (!st) return null
  const r = st.getBoundingClientRect()
  const W = json.value.width || 1600
  const s = r.width / W
  return { x: (e.clientX - r.left) / s, y: (e.clientY - r.top) / s }
}

function makeItem(def, cx, cy) {
  const W = json.value.width || 1600, H = json.value.height || 900
  const w = def.w || 120, h = def.h || 60
  const x = Math.max(0, Math.min(W - w, Math.round(cx - w / 2)))
  const y = Math.max(0, Math.min(H - h, Math.round(cy - h / 2)))
  // P6 控件：item 形态照任务书 { type:'control', control:'trend', props:{...} }
  if (def.type === 'control' && def.control) {
    const it = newControlItem(def.control, x, y)
    it.w = w; it.h = h
    it.layer = curLayer.value
    it.name = defaultName('control', json.value.items, null, controlDef(def.control).name)
    return it
  }
  // P8 组件模板实例：只存 fptId + bindings，不拷贝模板 json
  if (def.type === 'faceplate' && def.fptId) {
    const f = (rt && rt.fpt && rt.fpt.get(Number(def.fptId)))
      || fptList.value.find(x => Number(x.id) === Number(def.fptId)) || {}
    const fw = f.w || 200, fh = f.h || 200
    return {
      type: 'faceplate', fptId: Number(def.fptId),
      x: Math.max(0, Math.min(W - fw, Math.round(cx - fw / 2))),
      y: Math.max(0, Math.min(H - fh, Math.round(cy - fh / 2))),
      w: fw, h: fh, bindings: {}, layer: curLayer.value,
      name: defaultName('faceplate', json.value.items, null, f.name || '组件模板')
    }
  }
  // 符号库图元用图元自己的名字（格栅清污机1），不能回落到 typeLabel('symbol')='符号库'
  const nm = def.type === 'symbol' && def.symbol ? symbolName(def.symbol) : ''
  // 🔴 不要把 def.name（对象面板里的显示名，如「阀门」「液位罐」）写进 label：
  //    图元会在底部把 label 画出来，画布上就多出一堆「阀门」「液位罐」字样。
  //    name 只用于图层面板和选中提示；要显示文字请用文字标签，或手动填 label。
  const it = { type: def.type, x, y, w, h, layer: curLayer.value,
    name: defaultName(def.type, json.value.items, null, nm) }
  if (def.type === 'symbol' && def.symbol) it.symbol = def.symbol
  // 自定义图元：type=image + src（图片地址来自 /api/upload）
  if (def.src) it.src = def.src
  if (def.type === 'tank') Object.assign(it, { min: 0, max: 100 })
  if (def.type === 'value') {
    it.decimals = 2
    // 对象库入口带的初始模式（仅显示 / 可输入）
    if (def.mode) it.mode = def.mode
    if (def.mode && def.mode !== 'output') { it.submitBy = it.submitBy || 'both'; it.showUnit = true }
  }
  if (def.type === 'button') it.value = 1
  if (def.type === 'text') it.text = '静态文本'
  return it
}

function insertAt(def, cx, cy) {
  if (page.value.locked) { ElMessage.warning('画面已锁定，请先在画面树里解锁'); return }
  const it = makeItem(def, cx, cy)
  ci.add([it])          // 入撤销栈 + 重画 + 选中
  ElMessage.success('已插入「' + (def.name || typeName(def.type)) + '」')
}

function onCanvasClick(e) {
  if (!pendingDef.value) return
  const p = posFromEvent(e)
  if (!p) return
  const def = pendingDef.value
  pendingDef.value = null
  if (paletteRef.value) paletteRef.value.clear()
  insertAt(def, p.x, p.y)
}

function onDrop(e) {
  const raw = e.dataTransfer && e.dataTransfer.getData('text/scada-object')
  if (!raw) return
  let def
  try { def = JSON.parse(raw) } catch (err) { return }
  const p = posFromEvent(e)
  if (!p) return
  insertAt({ type: def.type, name: def.name, w: def.w, h: def.h, symbol: def.symbol,
             control: def.control, mode: def.mode, src: def.src }, p.x, p.y)
}

// —— 控件配置对话框（P6）——
function openCtrlDlg(item) {
  if (!item || item.type !== 'control') return
  if (page.value.locked) { ElMessage.warning('画面已锁定，请先在画面树里解锁'); return }
  ctrlItem.value = item
  ctrlDlg.value = true
}

function onCtrlSave(props) {
  const it = ctrlItem.value
  if (!it) return
  const from = JSON.parse(JSON.stringify(it.props || {}))
  // 走 applyProps 而不是直接赋值：整块 props 进撤销栈，Ctrl+Z 能撤回
  if (ci) ci.applyProps([{ item: it, key: 'props', from, to: props }])
  else it.props = props
  nextTick(() => { if (rt) rt.tick(true) })
  dirty.value = true
}

function doUndo() { if (ci) ci.undo() }
function doRedo() { if (ci) ci.redo() }

// —— P7 对齐 / 分布 / 层级 / 组合 ——
function setTab(t) {
  leftTab.value = t
  localStorage.setItem('scada.leftTab', t)
  if (t === 'layer') nextTick(() => { /* 面板自己按 items 渲染 */ })
}

// 对齐基准变化立即生效（下一刀对齐就用新基准）
watch(alignBase, (v) => {
  localStorage.setItem('scada.alignBase', v)
  if (ci) ci.alignBase = v
})

function doAlign(k) {
  if (!ci) return
  ci.alignBase = alignBase.value
  // 单选 → 相对画布；多选 → 相对基准
  ci.align(selItems.value.length > 1 ? k : 'canvas-' + k)
}
function doDistribute(k) { if (ci) ci.distribute(k === 'y' ? 'y' : 'x') }
function doZ(kind) { if (ci) ci.zOrder(kind) }
function doGroup() { if (ci) ci.group() }
function doUngroup() { if (ci) ci.ungroup() }
function exitGroup() { if (ci) ci.exitGroup() }

function onLayerSelect(item, e) {
  if (!ci) return
  if (e && (e.shiftKey || e.ctrlKey || e.metaKey)) {
    ci.setSel(ci.sel.includes(item) ? ci.sel.filter(x => x !== item) : [...ci.sel, item])
  } else {
    ci.setSel([item])
  }
}
function onToggleHidden(item) { if (ci) ci.setFlag(item, 'hidden', !item.hidden) }
function onToggleLock(item) { if (ci) ci.setFlag(item, 'locked', !item.locked) }
function onLayerReorder(from, to) { if (ci) ci.reorderByIndex(from, to) }

// 图层带：官方上限 32 层，满了给明确提示（不是静默失败）
function addLayer() {
  const L = json.value.layers || (json.value.layers = defaultLayers())
  if (L.length >= MAX_LAYERS) {
    ElMessage.warning('图层最多 ' + MAX_LAYERS + ' 层（官方限制），已经满了')
    return
  }
  const id = nextLayerId(L)
  L.push({ id, name: '第 ' + id + ' 层' })
  curLayer.value = id
  dirty.value = true
  ElMessage.success('已新建「第 ' + id + ' 层」，新对象将落在这一层')
}
function setLayer(id) { curLayer.value = id }

// 老画面没有 layers/item.layer：补默认值（只在内存里补，保存时落库）
function ensureLayers() {
  const d = json.value
  if (!Array.isArray(d.layers) || !d.layers.length) d.layers = defaultLayers()
  for (const it of d.items || []) if (!it.layer) it.layer = 1
  if (!d.layers.some(l => l.id === curLayer.value)) curLayer.value = d.layers[0].id
}

// —— 属性面板（P3）——
// 预览 = 拖动/输入过程中的实时效果（不写撤销栈）；提交 = 一次编辑落定（可 Ctrl+Z 撤回）
function onPropPreview(list) { if (ci) ci.previewProps(list) }
function onPropCommit(list) { if (ci) ci.applyProps(list) }

// 提示词 10 4.2：图层树双击改名——空名回落「类型+序号」，重名自动加 (2)。
// 走 applyProps 同一条通道：入撤销栈（Ctrl+Z 可回退）、置脏、发 object.change。
function onLayerRename(item, name) {
  if (!ci || !item) return
  let final = String(name || '').trim()
  if (!final) {
    final = defaultName(item.type, json.value.items, item)
  } else if (json.value.items.some(x => x !== item && x.name === final)) {
    let n = 2
    while (json.value.items.some(x => x !== item && x.name === `${final}(${n})`)) n++
    const nv = `${final}(${n})`
    ElMessage.info(`名称重复，已改为「${nv}」`)
    final = nv
  }
  if (final === item.name) return
  ci.applyProps([{ item, key: 'name', from: item.name, to: final }])
}

// 4.3 删除了「旧格式 → @CurrentSite 表达式」的批量升级：
// 变量只认 {site,point} 对象，表达式写法本身就是被禁掉的旧格式，
// 再提供一个“升级成表达式”的按钮会把人引到错误方向（面板里改为引导重新选点位）。

function toggleRight() {
  rightFold.value = !rightFold.value
  localStorage.setItem('scada.rightFold', rightFold.value ? '1' : '0')
  nextTick(() => { if (ci) ci.layoutSelection(); syncGrid() })
}

function onKey(e) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    e.preventDefault()
    save()
  }
  if (e.key === 'Escape' && pendingDef.value) {
    pendingDef.value = null
    if (paletteRef.value) paletteRef.value.clear()
  }
}

// —— 保存 ——
async function save(silent) {
  if (saving.value) return false
  // 10 §4.3 验收 5：绑定的点位被删/停用 → 保存被拒（不能把失效绑定写进库）
  const bad = await checkStaleVars()
  if (bad.length) {
    ElMessage.error('变量已失效：' + bad.slice(0, 5).map(v => v.tag).join('、')
      + (bad.length > 5 ? ' 等 ' + bad.length + ' 个' : '')
      + '。请在属性面板重新选点位后再保存')
    return false
  }
  saving.value = true
  try {
    if (isFpt.value) {
      // 组件模板单独一张表：接口变量与 json 一起存，实例只留 fptId + bindings
      await post('/api/fpt', {
        id: pageId.value, name: page.value.name,
        w: json.value.width, h: json.value.height,
        iface: iface.value, json: json.value
      })
      await refreshFptList()
    } else {
      // currentSite 只是"编辑器上次看哪个站点"，运行态以 site_id 为准
      json.value.currentSite = curSite.value || undefined
      // 10 §4.4：保存固定 PUT /api/page/{id}（同一个接口也负责改名/锁定，body 决定改什么）
      // site_id 必须一起写：这是画面归属的站点，画面列表/发布树/运行态三处都读它。
      // 以前不传，画面永远是 NULL，只能靠 json.currentSite 兜底 → 换画面就串站点。
      const r = await put('/api/page/' + pageId.value, {
        name: page.value.name || ('画面 ' + pageId.value),
        site_id: curSite.value || null,
        json: json.value
      })
      page.value.updated_at = r.updated_at || ''
      // P8：顺手生成并上传缩略图（400×225 PNG 存文件，不塞 json）；失败不影响保存
      uploadThumb()
    }
    dirty.value = false
    if (!silent) ElMessage.success('已保存')
    return true
  } catch (e) {
    return false
  } finally {
    saving.value = false
  }
}

// 10 §4.4：切换画面随画面列表一起去掉（只有一张画面，没有可切的目标）

async function renamePage() {
  try {
    const { value } = await ElMessageBox.prompt('画面名称', '重命名', {
      inputValue: page.value.name || '',
      inputPattern: /\S/, inputErrorMessage: '名称不能为空',
      confirmButtonText: '确定', cancelButtonText: '取消'
    })
    const name = value.trim()
    // 改名也走同一个 PUT：body 只带 name 时后端只动元数据，不碰 json
    const r = await put('/api/page/' + pageId.value, { name })
    page.value.name = r.name || name
    page.value.updated_at = r.updated_at || page.value.updated_at
    ElMessage.success('已改名')
  } catch (e) { /* 取消 */ }
}

// —— P8 缩略图 ——
function uploadThumb() {
  if (isFpt.value) return
  try {
    // 把模板表一起传进去：组件模板实例要展开模板才画得出内容
    const data = paintThumb(json.value, { fpt: rt ? rt.fpt : null })
    if (!data) return
    post('/api/page/' + pageId.value + '/thumb', { data }, { silent: true }).catch(() => {})
  } catch (e) { /* 缩略图只是列表页用，失败不能让保存失败 */ }
}

// —— P8 组件模板 ——
// 存完模板要立刻刷新内存里的模板表并重画：不然画布上的实例还是旧模板
async function refreshFptList() {
  if (!rt) return
  await rt.loadDefs(true)
  fptList.value = [...rt.fpt.values()]
  draw()
}

function openIface() {
  ifaceEdit.value = JSON.parse(JSON.stringify(iface.value || []))
  ifaceDlg.value = true
}

// 前端先校验一遍：后端还会再校验（403/400 也照实弹出来，不静默）
async function saveIface() {
  const names = new Set()
  for (const t of ifaceEdit.value) {
    const nm = String(t.name || '').trim()
    if (!/^[A-Za-z_][A-Za-z0-9_]{0,15}$/.test(nm)) {
      ElMessage.error('变量名「' + nm + '」不合法：字母或下划线开头，最长 16 位')
      return
    }
    if (nm === 'CurrentSite') { ElMessage.error('@CurrentSite 是运行时关键字，不能作接口变量名'); return }
    if (names.has(nm)) { ElMessage.error('变量名重复：' + nm); return }
    names.add(nm)
  }
  iface.value = ifaceEdit.value.map(t => ({
    name: String(t.name).trim(), type: t.type || 'real',
    default: t.default === '' || t.default === undefined ? 0 : t.default,
    desc: String(t.desc || '')
  }))
  ifaceDlg.value = false
  dirty.value = true
  const ok = await save(true)
  if (ok) ElMessage.success('接口变量已保存：' + iface.value.length + ' 个')
}

async function resizeFpt() {
  try {
    const { value } = await ElMessageBox.prompt('画布尺寸（宽x高，像素）', '画布尺寸', {
      inputValue: (json.value.width || 200) + 'x' + (json.value.height || 200),
      inputPattern: /^\s*\d{1,5}\s*[xX*×]\s*\d{1,5}\s*$/,
      inputErrorMessage: '格式：1280x720（宽高各 1~99999 像素）',
      confirmButtonText: '确定', cancelButtonText: '取消'
    })
    const m = String(value).match(/^\s*(\d{1,5})\s*[xX*×]\s*(\d{1,5})\s*$/)
    if (!m) return
    json.value.width = Number(m[1])
    json.value.height = Number(m[2])
    dirty.value = true
    // 尺寸变了必须让 renderScada 重建 DOM：舞台(stage)和内层画布(inner)的宽高
    // 只在建 DOM 时写进 style，走 patch 分支不会动它们。
    // 清掉 sig 强制下一次比较不相等 → 重建。不清的话还会被后面的 fitWindow()
    // 触发第二次渲染时"sig 已相等"而退回 patch，画布尺寸看起来没变。
    if (canvas.value && canvas.value.__scada) canvas.value.__scada.sig = ''
    await nextTick()
    draw()
    if (ci) ci.fitWindow()
  } catch (e) { /* 取消 */ }
}

function onSiteChange() {
  dirty.value = true
  // 间接变量连接全靠这一步：换站 → 整张画面重新求值（不重建 DOM、不刷新页面）
  if (curSite.value) localStorage.setItem('scada.currentSite', curSite.value)
  if (rt) rt.setSite(curSite.value)
  ctrlEnv.setSite(curSite.value)
}

// 4.3：点顶栏红色标签 → 列出全部失效变量，明确告诉是哪几个、去哪改
function onShowStale() {
  const lines = staleVars.value.map(v => '· ' + v.tag)
  ElMessageBox.alert(
    '以下变量绑定的点位在点位表里不存在或已停用，保存会被拒绝：\n\n' + lines.slice(0, 40).join('\n')
    + (lines.length > 40 ? '\n…' : '')
    + '\n\n处理方式：选中对应对象 → 属性 → 关联变量 → 重新选「站点 + 点位」。',
    '变量已失效（' + staleVars.value.length + ' 个）',
    { confirmButtonText: '知道了' }
  ).catch(() => {})
}

function preview() {
  if (dirty.value) { ElMessage.warning('先保存再预览，否则看到的是上次保存的内容'); return }
  window.open('/view/' + pageId.value, '_blank')
}

async function back() {
  if (dirty.value) {
    try {
      await ElMessageBox.confirm('有未保存的修改，确定离开？', '返回总览', {
        confirmButtonText: '离开', cancelButtonText: '留下', type: 'warning'
      })
    } catch (e) { return }
  }
  // 10 §4.4：没有画面列表页可回，返回入口直接回总览
  router.push('/dashboard')
}

// —— 三栏拖宽（宽度存 localStorage）——
let dragSide = null
function startDrag(side, e) {
  dragSide = side
  e.preventDefault()
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  window.addEventListener('mousemove', onDragMove)
  window.addEventListener('mouseup', onDragEnd)
}
function onDragMove(e) {
  const box = edEl.value ? edEl.value.getBoundingClientRect() : { left: 0, width: window.innerWidth }
  if (dragSide === 'left') {
    leftW.value = Math.max(180, Math.min(460, Math.round(e.clientX - box.left)))
  } else if (dragSide === 'right') {
    rightW.value = Math.max(220, Math.min(560, Math.round(box.left + box.width - e.clientX)))
  }
}
function onDragEnd() {
  localStorage.setItem('scada.leftW', leftW.value)
  localStorage.setItem('scada.rightW', rightW.value)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  window.removeEventListener('mousemove', onDragMove)
  window.removeEventListener('mouseup', onDragEnd)
  dragSide = null
  if (ci) ci.layoutSelection()
}

function onBeforeUnload(e) {
  if (!dirty.value) return
  e.preventDefault()
  e.returnValue = ''
}

onBeforeRouteLeave(async (to, from, next) => {
  if (!dirty.value) return next()
  try {
    await ElMessageBox.confirm('有未保存的修改，确定离开当前画面？', '未保存', {
      confirmButtonText: '离开', cancelButtonText: '留下', type: 'warning'
    })
    next()
  } catch (e) { next(false) }
})

watch(() => route.params.id, async (id) => {
  if (!id) return
  if (Number(id) !== Number(pageId.value)) await loadPage(Number(id), true)
})

// 落位模式要让交互层知道，否则 mousedown 会先开始框选
watch(pendingDef, (v) => { if (ci) ci.placing = !!v })


// 切站点时刷新通道清单（属性面板下拉要用）
watch(curSite, () => { loadChannels() })
onMounted(async () => {
  ensureScadaStyles()
  loadChannels()
  loadPageOptions()
  ci = new CanvasInteract({
    wrap: canvasWrap.value,
    getStage: () => canvas.value && canvas.value.querySelector('.scada-stage'),
    getItems: () => json.value.items,
    getSize: () => ({ W: json.value.width || 1600, H: json.value.height || 900 }),
    gridOn: () => grid.value,
    isLocked: () => !!page.value.locked,
    onDirty: () => { dirty.value = true },
    onSelection: (arr) => { selItems.value = arr },
    onRebuild: () => draw(),
    // 只改样式、不重建 DOM：改颜色/字号时视频不重连、面板输入焦点不丢
    onPropsChanged: (changes) => {
      // P5：属性真的变了才发 object.change / <attr>.change（一次改动里同一对象只发一轮）
      const c = canvas.value
      if (!c || !c.__scada) return
      const byItem = new Map()
      for (const ch of changes || []) {
        if (!byItem.has(ch.item)) byItem.set(ch.item, [])
        byItem.get(ch.item).push(ch.key)
      }
      for (const [item, keys] of byItem) fireAttrChange(evCtx, c.__scada, item, keys)
    },
    onRestyle: () => {
      const c = canvas.value
      if (c && c.__scada && c.__scada.restyle) c.__scada.restyle()
      if (ci) ci.layoutSelection()
      // 改了属性（尤其是 dyn）要立刻重算一次，不用等下一个 250ms 广播
      if (rt) rt.tick(true)
    },
    onZoom: (z) => {
      const c = canvas.value
      if (c && c.__scada && c.__scada.setZoom) c.__scada.setZoom(z)
      syncGrid()
    },
    onHistory: () => {
      canUndo.value = !!(ci && ci.history.canUndo)
      canRedo.value = !!(ci && ci.history.canRedo)
    },
    onMessage: (m) => ElMessage.info(m),
    // P7：图层/组合变化后，图层面板靠 items 的响应式自动刷新；这里只管提示条
    onLayers: () => { dirty.value = true },
    onEditGroup: (item) => { editGroupName.value = item ? (item.name || '组合') : '' },
    onReadout: (txt) => {
      const el = readoutEl.value
      if (!el) return
      el.textContent = txt
      el.style.display = txt ? 'block' : 'none'
    }
  })
  ci.attach()

  rt = new ScadaRuntime({
    site: '',
    onIssues: (list) => { issueCount.value = list.length },
    onSse: (ok) => { sseOk.value = ok }
  })
  rt.start()
  evCtx.rt = rt
  ctrlEnv.rt = rt
  ctrlEnv.setSite(curSite.value)
  // 控件靠版本号重算：runtime 每 250ms 广播一次，这里只递增一个数字
  rt.subscribe(() => ctrlEnv.bump())

  window.addEventListener('keydown', onKey)
  window.addEventListener('beforeunload', onBeforeUnload)
  await loadSites()
  // P8：模板与值列表要先到位，否则首帧实例渲染成「模板不存在」
  await rt.loadDefs()
  fptList.value = [...rt.fpt.values()]
  // 10 §4.4：库里只有 id=1，loadPage 内部会把其它 id 拉回 1 并提示
  await loadPage(pageId.value, true)
  loadPageList()      // 顶部【打开】下拉的画面清单
  if (ci) ci.alignBase = alignBase.value
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('beforeunload', onBeforeUnload)
  if (stageRo) { try { stageRo.disconnect() } catch (e) { /* 已断开 */ } }
  if (ci) { ci.detach(); ci = null }
  if (canvas.value) { try { firePictureClose(canvas.value, evCtx) } catch (e) { /* 忽略 */ } }
  if (rt) { rt.stop(); rt = null }
  if (canvas.value) destroyScada(canvas.value)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
})
</script>

<style scoped>
/* P8 接口变量弹窗 */
.ift-h { color: #6b8fb3; font-size: 12px; line-height: 1.7; margin-bottom: 8px; }
.ift-h code { background: #f1f5f9; padding: 0 3px; border-radius: 2px; color: #1d4ed8; }
.ift-t { width: 100%; border-collapse: collapse; font-size: 12px; }
.ift-t th { text-align: left; color: #64748b; font-weight: 500; padding: 4px 6px; border-bottom: 1px solid #e5e7eb; }
.ift-t td { padding: 3px 6px; }
.ift-in { width: 100%; box-sizing: border-box; height: 26px; padding: 0 6px; border: 1px solid #cbd5e1;
  border-radius: 3px; font-size: 12px; }
.ift-in.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
.ift-sel { height: 26px; border: 1px solid #cbd5e1; border-radius: 3px; font-size: 12px; padding: 0 4px; }
.ift-x { width: 22px; height: 22px; border: 1px solid #e5e7eb; background: #fff; color: #ef4444;
  border-radius: 3px; cursor: pointer; }
.ift-add { margin-top: 8px; height: 26px; padding: 0 10px; border: 1px dashed #cbd5e1; background: #fff;
  color: #475569; border-radius: 3px; cursor: pointer; font-size: 12px; }
.ed { height: calc(100vh - 68px); display: flex; flex-direction: column; background: #08111c;
      border-radius: 4px; overflow: hidden; box-sizing: border-box; }

/* 顶栏 */
.topbar { flex: 0 0 auto; display: flex; align-items: center; gap: 6px; padding: 6px 10px;
          background: #0b1622; border-bottom: 1px solid #16283d; color: #9fc3e8; }
.topbar :deep(.el-button + .el-button) { margin-left: 0; }
.pname { font-size: 14px; font-weight: 600; color: #e2e8f0; cursor: pointer; padding: 2px 6px;
         border-radius: 3px; max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pname:hover { background: #12233a; }
.pen { font-size: 11px; color: #5b82a8; margin-left: 4px; }
.dirty { color: #f59e0b; font-size: 12px; }
.stale-tag { cursor: pointer; }
.sep { width: 1px; height: 18px; background: #1e3a5f; margin: 0 2px; flex: 0 0 1px; }
.tools { display: inline-flex; gap: 1px; }
.ico { width: 22px; height: 22px; padding: 2px; background: #0e1f33; border: 1px solid #1e3a5f;
       border-radius: 3px; color: #5b82a8; display: inline-flex; align-items: center; justify-content: center; }
.ico[disabled] { opacity: .45; cursor: not-allowed; }
.ico:not([disabled]) { cursor: pointer; }
.ico:not([disabled]):hover { border-color: #1ec8ff; color: #cdeaff; background: #12233a; }
.base { width: 112px; }
.base :deep(.el-select__wrapper) { min-height: 22px; padding: 0 6px; background: #0e1f33;
  box-shadow: 0 0 0 1px #1e3a5f inset; }
.base :deep(.el-select__selected-item) { font-size: 11px; color: #9fc3e8; }
.ico :deep(svg) { width: 14px; height: 14px; }
.grow { flex: 1; }
.zoom { display: inline-flex; align-items: center; gap: 3px; font-size: 12px; color: #9fc3e8;
        cursor: pointer; padding: 2px 7px; border: 1px solid #1e3a5f; border-radius: 3px;
        background: #0e1f33; font-family: Consolas, monospace; }
.zoom:hover { border-color: #1ec8ff; color: #cdeaff; }
.caret { font-size: 10px; color: #5b82a8; }
.site-ctx { display: inline-flex; align-items: center; gap: 5px; flex: 0 0 auto; }
.at { color: #1ec8ff; font-family: Consolas, monospace; font-size: 12px; }
.warn { color: #f59e0b; font-size: 11px; }

/* 三栏 */
.main { flex: 1; display: flex; min-height: 0; }
.left { flex: 0 0 auto; display: flex; flex-direction: column; background: #0b1622; min-width: 0; }
.right { flex: 0 0 auto; display: flex; flex-direction: column; background: #0b1622; min-width: 0; }
.pane { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.pane-hd { flex: 0 0 auto; padding: 5px 8px; font-size: 11px; color: #7ba3c9; letter-spacing: .5px;
           background: #0e1f33; border-bottom: 1px solid #16283d; }
.pane-hd.tabs { display: flex; gap: 0; padding: 0; }
.tab { flex: 0 0 auto; padding: 5px 12px; font-size: 11px; color: #7ba3c9; cursor: pointer;
       border-bottom: 2px solid transparent; letter-spacing: .5px; }
.tab:hover { color: #cdeaff; }
.tab.on { color: #cdeaff; border-bottom-color: #1ec8ff; background: #12233a; }
.pane-bd { flex: 1; min-height: 0; overflow: auto; }

/* 画面信息面板（10 §4.4：单画面，左栏不再放画面树） */
.pane-info { flex: 0 0 auto; }
.info { padding: 4px 10px 10px; }
.ir { display: flex; align-items: baseline; gap: 8px; font-size: 12px; line-height: 21px; }
.ir span { flex: 0 0 40px; color: #5b82a8; }
.ir b { color: #dbeafe; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ir b.unsaved { color: #f59e0b; }
.ihint { margin-top: 8px; padding-top: 8px; border-top: 1px dashed #16283d;
  color: #4a6d92; font-size: 11px; line-height: 1.75; }
.ihint code { color: #1ec8ff; font-family: Consolas, monospace; }
.vbar { flex: 0 0 4px; cursor: col-resize; background: #0b1622; }
.vbar:hover { background: #1ec8ff; }

.center { flex: 1; min-width: 0; display: flex; }
/* 画布 1:1（画布尺寸 = 画面尺寸）后，画面可能比容器大，必须能滚动 */
.canvas-wrap { flex: 1; position: relative; overflow: auto; background: #060d16; min-width: 0; }
.canvas-wrap.placing { cursor: crosshair; }
.canvas { width: 100%; height: 100%; }
.grid-layer { position: absolute; pointer-events: none; z-index: 1;
  background-image: linear-gradient(to right, rgba(90,140,190,.22) 1px, transparent 1px),
                    linear-gradient(to bottom, rgba(90,140,190,.22) 1px, transparent 1px); }
.placing-tip { position: absolute; left: 50%; transform: translateX(-50%); top: 8px; z-index: 5;
  background: rgba(30,200,255,.14); border: 1px solid #1ec8ff; color: #cdeaff; font-size: 12px;
  padding: 3px 10px; border-radius: 3px; pointer-events: none; }
.grp-tip { position: absolute; left: 50%; transform: translateX(-50%); top: 8px; z-index: 6;
  background: rgba(245,158,11,.16); border: 1px solid #f59e0b; color: #fde68a; font-size: 12px;
  padding: 2px 8px; border-radius: 3px; display: flex; align-items: center; gap: 8px; }
.gt-x { background: #f59e0b; color: #1a1206; border: none; border-radius: 2px; font-size: 11px;
  padding: 1px 6px; cursor: pointer; }
.drag-readout { position: absolute; left: 8px; bottom: 6px; z-index: 9; display: none;
  font-family: Consolas, monospace; font-size: 12px; color: #cdeaff;
  background: rgba(11,22,34,.92); border: 1px solid #1ec8ff; border-radius: 3px;
  padding: 2px 8px; pointer-events: none; }
.preview-tag { position: absolute; right: 8px; bottom: 6px; z-index: 5; font-size: 11px;
  color: #5b82a8; background: rgba(11,22,34,.8); border: 1px solid #1e3a5f; border-radius: 3px;
  padding: 1px 6px; pointer-events: none; }
.preview-tag.live { color: #22c55e; border-color: #166534; }

.prop-empty { padding: 20px 14px; color: #5b82a8; font-size: 12px; line-height: 1.9; }
.prop-empty .sub { color: #3b5c82; font-size: 11px; }
.prop-empty .sel { margin-top: 2px; color: #1ec8ff; }
.prop-empty .sel.multi { font-size: 13px; font-weight: 600; }

/* 面板收起后的展开把手：竖排细条，不占画布宽度 */
.unfold { flex: 0 0 18px; width: 18px; border: none; border-left: 1px solid #16283d;
  background: #0e1f33; color: #7ba3c9; cursor: pointer; writing-mode: vertical-rl;
  font-size: 11px; letter-spacing: 2px; padding: 0; }
.unfold:hover { background: #12233a; color: #cdeaff; }
</style>
