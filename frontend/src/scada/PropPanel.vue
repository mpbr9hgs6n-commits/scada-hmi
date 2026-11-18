<template>
  <div class="pp">
    <div class="hd">
      <span class="ttl" :title="titleTip">{{ title }}</span>
      <span v-if="items.length > 1" class="badge">多选</span>
      <button class="fold" title="收起属性面板（画布自动撑满）" @click="$emit('collapse')">⟩</button>
    </div>

    <!-- 对象名：单选取独有；重名当场提示，不写回 -->
    <div v-if="single" class="nm">
      <label>名称</label>
      <input class="ntxt" :class="{ err: errs.__name }" :value="texts.__name"
             @input="nameType($event)" @blur="nameBlur" @keydown.enter.prevent="nameBlur">
      <div v-if="errs.__name" class="tip inline">{{ errs.__name }}</div>
    </div>

    <!-- P8 组件模板实例：接口变量绑定（官方 4.6.2.5） -->
    <div v-if="single && items[0].type === 'faceplate'" class="fptb">
      <div class="fptb-hd">
        接口变量绑定
        <span class="fptb-nm">{{ fptDef ? fptDef.name : ('模板 #' + items[0].fptId) }}</span>
        <span v-if="unbound.length" class="fptb-miss">{{ unbound.length }} 个未绑定</span>
      </div>
      <div v-if="!fptDef" class="fptb-empty">模板不存在（可能已被删除），画布上是红虚线占位</div>
      <div v-else-if="!iface.length" class="fptb-empty">这个模板没有定义接口变量</div>
      <div v-for="t in iface" :key="t.name" class="fptb-row">
        <label class="fptb-lb">
          <span class="mono">@{{ t.name }}</span>
          <span class="fptb-tp">{{ t.type }}</span>
        </label>
        <input class="txt mono fptb-in" :class="{ miss: !bindings[t.name] }"
               :value="bindings[t.name] || ''" placeholder="S001.LEVEL"
               @change="setBind(t.name, $event.target.value)">
        <button class="mini fptb-pick" @click="openPicker(t.name)">选择</button>
      </div>
      <div v-if="fptDef" class="fptb-tip">
        实例只存绑定，不拷贝模板：改模板里任何一个对象，所有实例都会跟着变。
      </div>
    </div>

    <!-- 10 §4.3 规则 3：绑了 {site,point} 但点位已被删/停用 → 红色提示，保存会被拒 -->
    <div v-if="staleSel" class="stalebar">
      <div class="sb-t">变量已失效：<b class="mono">{{ staleSel }}</b></div>
      <div class="sb-d">这个点位在点位表里不存在或已停用（enabled=0）。保存会被拒绝：请重新选一个点位。</div>
      <div class="sb-b"><button class="mini" @click="gotoVarTab">去重新选点位</button></div>
    </div>

    <div v-if="legacySel" class="legacybar">
      <div class="lb-t">该对象用的是旧格式变量：<b class="mono">{{ items[0].var }}</b>（4.3 起不再支持）</div>
      <div class="lb-d">变量只认「站点 + 点位」对象，不能写字符串或表达式。重新选一次点位，旧写法就被替换掉。</div>
      <div class="lb-b">
        <button class="mini" @click="gotoVarTab">去重新选点位</button>
      </div>
    </div>

    <div class="tabs" v-if="items.length">
      <span v-for="t in tabList" :key="t.key" class="tab" :class="{ on: tab === t.key }"
            @click="setTab(t.key)">{{ t.label }}</span>
    </div>

    <div class="bd">
      <div v-if="!items.length" class="empty">
        <div>选中对象后显示属性</div>
        <div class="sub">单击画布里的对象；Shift 加选；空白处拖框多选</div>
      </div>

      <div v-else-if="!tabList.length" class="empty">选中的对象类型没有共同属性</div>

      <div v-else-if="tab === 'dyn'" class="dynwrap">
        <DynPanel v-if="single" :item="items[0]" :sites="sites" :cur-site="curSite" :rt="rt"
                  :stale="stale" @commit="onDynCommit" @setvar="onSetVar"
                  @rules="onRulesCommit" />
        <div v-else class="ph">
          <div class="ph-t">动态化只支持单个对象</div>
          <div class="ph-d">官方限制：一个变量驱动多属性的「动画」、以及动态对话框，都只能配在单个对象上。
            多选时请先只选一个对象再配动态化（批量复制可用「复制动态化 / 粘贴动态化」）。</div>
        </div>
      </div>

      <div v-else-if="tab === 'event'" class="dynwrap">
        <EventPanel v-if="single" :item="items[0]" :all="all" :sites="sites" :cur-site="curSite"
                    :ev-ctx="evCtx" @commit="onEvCommit" />
        <div v-else class="ph">
          <div class="ph-t">事件只支持单个对象</div>
          <div class="ph-d">一个对象一张事件表。多选时请先只选一个对象再配事件（动作里可以指定"别的对象"作为目标）。</div>
        </div>
      </div>

      <template v-else>
        <div v-if="shared.readonly" class="ro-tip">该图元尺寸由图形决定，几何只读；可整体拖动</div>

        <div v-for="g in groups" :key="g.sec" class="grp">
          <div class="grp-hd">{{ g.sec }}</div>

          <div v-for="f in g.fields" :key="f" class="row" :class="{ bad: errs[f] }">
            <span class="dy" :class="{ on: meta(f).dyn }" :title="meta(f).dyn
              ? '可动态化（P4 接入变量绑定）' : '不可动态化：运行时改了没效果'">◈</span>
            <label class="lb" :title="label(f)">{{ label(f) }}</label>

            <div class="ctl">
              <!-- 数值：可输入，也可按住左右拖动 -->
              <template v-if="meta(f).type === 'num'">
                <input :ref="el => setInput(f, el)" class="num" :class="{ err: errs[f] }" type="text"
                       inputmode="decimal" :disabled="ro(f)" :value="texts[f]"
                       @mousedown="numDown($event, f)"
                       @focus="focusVal(f)"
                       @input="numType($event, f)"
                       @blur="numBlur(f)"
                       @keydown.enter.prevent="numBlur(f, true)">
                <span class="unit">{{ meta(f).unit }}</span>
              </template>

              <!-- 颜色：色板 + 十六进制输入双向同步 -->
              <template v-else-if="meta(f).type === 'color'">
                <span class="sw" :style="{ background: hexOf(f) }">
                  <input type="color" :disabled="ro(f)" :value="hexOf(f)"
                         @input="pickColor(f, $event.target.value)"
                         @change="pickColor(f, $event.target.value, true)">
                </span>
                <input :ref="el => setInput(f, el)" class="hex" :class="{ err: errs[f] }" type="text"
                       :disabled="ro(f)" :value="texts[f]" maxlength="7"
                       @focus="focusVal(f)" @input="hexType($event, f)" @blur="hexBlur(f)"
                       @keydown.enter.prevent="hexBlur(f, true)">
              </template>

              <template v-else-if="meta(f).type === 'select'">
                <select class="sel" :disabled="ro(f)" :value="str(f)" @change="pickOne(f, $event.target.value)">
                  <option v-for="o in optionsOf(meta(f))" :key="o.v" :value="o.v">{{ o.t }}</option>
                </select>
              </template>

              <template v-else-if="meta(f).type === 'bool'">
                <label class="sw-box" :class="{ dis: ro(f) }">
                  <input type="checkbox" :disabled="ro(f)" :checked="!!val(f)"
                         @change="pickOne(f, $event.target.checked)">
                  <span>{{ val(f) ? '是' : '否' }}</span>
                </label>
              </template>

              <template v-else-if="meta(f).type === 'image'">
                <button class="mini" :disabled="ro(f)" @click="pickFile(f)">上传</button>
                <button class="mini" v-if="val(f)" :disabled="ro(f)" @click="pickOne(f, '')">清除</button>
                <img v-if="val(f)" class="thumb" :src="val(f)" alt="">
                <input :ref="setFileEl" class="file" type="file" accept="image/png,image/jpeg,image/webp,image/gif"
                       @change="onFile($event, f)">
              </template>

              <template v-else>
                <input :ref="el => setInput(f, el)" class="txt" :class="{ err: errs[f] }" type="text"
                       :disabled="ro(f)" :value="texts[f]" :maxlength="meta(f).maxLen || 64"
                       @focus="focusVal(f)" @input="plainType($event, f)" @blur="plainBlur(f)"
                       @keydown.enter.prevent="plainBlur(f, true)">
              </template>
            </div>

            <div v-if="errs[f]" class="tip">{{ errs[f] }}</div>
          </div>
        </div>
      </template>
    </div>

    <!-- 视频窗诊断：当前实际连哪一路、什么码流、能不能播 -->
    <div v-if="videoDiag" class="vdiag" :class="videoDiag.level">{{ videoDiag.text }}</div>

    <!-- 保存栏：每个页签内容的下方都有，改完就地存，不用跑回顶部工具栏 -->
    <div class="save-bar">
      <button class="mini save-btn" :disabled="!items.length" @click="emit('save')">保存</button>
      <span class="save-hint">{{ items.length ? '保存当前画面（等同顶部【保存】）' : '先选一个对象' }}</span>
    </div>

    <VarPicker v-model="pickerOpen" :sites="sites" :site="curSite" @pick="onPickTag" />
  </div>
</template>

<script setup>
// 属性面板（P3）：按 WinCC 的「属性页签 + 分组」组织，按对象类型分支生成字段。
// 三种交互必须同时成立：①改字段立刻反映到画布 ②非法输入不写回数据 ③多选改一处全变
import { ref, reactive, computed, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import {
  TABS, FIELDS, typeLabel, effOf, defaultsOf, sharedSchema,
  isNameTaken, defaultName, isLegacyVar
} from './props'
import DynPanel from './DynPanel.vue'
import VarPicker from './VarPicker.vue'
import EventPanel from './EventPanel.vue'
import { tagOfVar } from './varbind'

const props = defineProps({
  items: { type: Array, default: () => [] },
  all: { type: Array, default: () => [] },
  pageW: { type: Number, default: 1600 },
  pageH: { type: Number, default: 900 },
  sites: { type: Array, default: () => [] },
  // 该站点的通道清单（给「视频通道」下拉用），由 ScadaEditor 预取后传入
  channels: { type: Array, default: () => [] },
  // 视频窗：由父组件传入「当前实际会连哪一路」的解析函数，用于诊断行
  resolveCam: { type: Function, default: null },
  // 所有组态画面（给「跳转画面」下拉用）
  pages: { type: Array, default: () => [] },
  curSite: { type: String, default: '' },
  rt: { type: Object, default: null },
  evCtx: { type: Object, default: null },
  // 编辑器算好的「失效变量」标签（如 S001.LEVEL），用于红色提示
  stale: { type: Array, default: () => [] }
})
const emit = defineEmits(['preview', 'commit', 'collapse', 'save'])

// P8 组件模板实例：模板定义从运行时缓存里取（rt.fpt 是 Map）
const fptDef = computed(() => {
  const it = props.items[0]
  if (!it || it.type !== 'faceplate' || !props.rt || !props.rt.fpt) return null
  return props.rt.fpt.get(Number(it.fptId)) || null
})
const iface = computed(() => (fptDef.value && fptDef.value.iface) || [])
const bindings = computed(() => (props.items[0] && props.items[0].bindings) || {})
const unbound = computed(() => iface.value.filter(t => !bindings.value[t.name]).map(t => t.name))

const pickerOpen = ref(false)
// 旧格式绑定（P1 的 var:'LEVEL'）：选中单个对象时给黄条 + 一键升级
const legacySel = computed(() => props.items.length === 1 && isLegacyVar(props.items[0])
  && !(props.items[0].dyn && props.items[0].dyn.value))

// 4.3：当前选中对象绑的 {site,point} 是否已失效（编辑器把失效清单传进来）
const staleSel = computed(() => {
  if (props.items.length !== 1) return ''
  const tag = tagOfVar(props.items[0] && props.items[0].var)
  return tag && (props.stale || []).includes(tag) ? tag : ''
})
function openVarForCurrent() { gotoVarTab() }
// 4.3：变量只能在「动态化」页签里用两个下拉选，这里把用户送过去并说清步骤
function gotoVarTab() {
  setTab('dyn')
  ElMessage.info('在「动态化」页签点「关联变量」：先选站点，再选点位（不用写表达式）')
}
const pickFor = ref('')
function openPicker(name) { pickFor.value = name; pickerOpen.value = true }
function onPickTag(v) {
  if (!pickFor.value) return
  // 选择器返回 { site, point }；组件模板的接口绑定仍存 "S001.LEVEL" 字符串
  const tag = (v && typeof v === 'object') ? `${v.site}.${v.point}` : v
  setBind(pickFor.value, tag)
}
function setBind(name, tag) {
  const it = props.items[0]
  if (!it) return
  const from = JSON.parse(JSON.stringify(it.bindings || {}))
  const to = Object.assign({}, from)
  if (tag) to[name] = String(tag).trim()
  else delete to[name]
  emit('commit', [{ item: it, key: 'bindings', from, to }])
}

const tab = ref('geom')
// 选中视频窗时自动切到「外观」：视频通道在「外观」页签下，
// 属性面板默认停在「几何」，用户经常找不到配视频的地方。
watch(() => props.items, (arr) => {
  const it = arr && arr[0]
  if (it && it.type === 'video' && (tab.value === 'geom' || tab.value === 'font')) {
    tab.value = 'look'
  }
})
const texts = ref({})
const errs = reactive({})
const inputs = {}
let fileEl = null
function setFileEl(el) { fileEl = el }

// 视频窗诊断行：当前实际连哪一路、什么码流、能不能播
const videoDiag = computed(() => {
  if (!single.value || props.items[0].type !== 'video') return null
  const it = props.items[0]
  const wantSub = String(it.chStream || 'main') === 'sub'
  const manual = String(it.chManual || '').trim()
  if (manual) {
    const hit = (props.channels || []).find(c => c.stream === manual || c.stream_sub === manual)
    return {
      level: hit ? 'ok' : 'warn',
      text: hit
        ? `当前实际：${manual}（${hit.name}）· ${wantSub ? '子码流' : '主码流'}`
        : `手动流名 ${manual} 不在通道列表里，将直接按此流名拉流`
    }
  }
  if (!props.resolveCam) return null
  const cam = props.resolveCam(it)
  if (!cam || !cam.stream) {
    return { level: 'err', text: '配置的通道在通道列表里找不到，运行时将回落到第一路可播' }
  }
  const codec = String((cam.sub ? cam.codec_sub : cam.codec) || '').toUpperCase()
  const ok = cam.sub ? (cam.browser_ok_sub !== false) : (cam.browser_ok !== false)
  const parts = [`当前实际：${cam.stream}`, cam.name ? `（${cam.name}）` : '',
                 ` · ${cam.sub ? '子码流' : '主码流'}`,
                 codec ? ` · ${codec === 'H264' ? 'H.264' : (codec === 'H265' ? 'H.265' : codec)}` : '',
                 ok ? ' · 可播' : ' · 浏览器播不了 → 试试切子码流']
  return {
    level: ok ? 'ok' : 'warn',
    text: parts.join('') + (cam.fellbackMain ? '（该通道未配子码流，已回落主码流）' : '')
  }
})

const meta = (f) => FIELDS[f] || { label: f, type: 'text', dyn: true }
const label = (f) => meta(f).label
const single = computed(() => props.items.length === 1)
const types = computed(() => [...new Set(props.items.map(i => i.type))])
const shared = computed(() => sharedSchema(types.value))

const tabList = computed(() => {
  const keys = shared.value.tabs || []
  // 2026-11-14 用户要求：对象库 / 工艺图元 / 符号库图元里的图元和控件，
  // 全部都要能在属性页配「动态化」和「条件规则」（值=x → 执行动作）。
  // 原来只有 SCHEMA 里声明了 dyn 的类型才出这个页签，标准图元（矩形/圆/多边形…）
  // 和工艺图元都没有，规则表根本够不着。这里统一补上。
  const withDyn = keys.includes('dyn') ? keys : [...keys, 'dyn']
  return TABS.filter(t => withDyn.includes(t.key))
})

const groups = computed(() => {
  if (tab.value === 'dyn' || tab.value === 'event') return []
  return (shared.value.groups && shared.value.groups[tab.value]) || []
})

const idx = computed(() => (single.value ? props.all.indexOf(props.items[0]) + 1 : 0))
const title = computed(() => {
  if (!props.items.length) return '属性'
  if (!single.value) return `已选中 ${props.items.length} 个对象`
  return `${typeLabel(types.value[0])} #${idx.value > 0 ? idx.value : '?'}`
})
const titleTip = computed(() => (single.value ? `画面内第 ${idx.value} 个对象（序号按当前图层顺序）` : '多选：只显示共同字段，修改作用于全部选中对象'))

const ro = () => !!shared.value.readonly

function setInput(f, el) { if (el) inputs[f] = el }

// —— 取值：多选时只有全部相同才显示值 ——
const realKey = (f) => (f === '__name' ? 'name' : (meta(f).key || f))
function val(f) {
  if (!props.items.length) return undefined
  const k = realKey(f)
  const v0 = effOf(props.items[0], k)
  for (const it of props.items.slice(1)) {
    if (String(effOf(it, k)) !== String(v0)) return undefined
  }
  return v0
}
function str(f) {
  const v = val(f)
  return v === undefined ? '' : String(v)
}
function hexOf(f) {
  const v = String(val(f) || '')
  if (/^#[0-9a-f]{3}$/i.test(v)) return ('#' + v[1] + v[1] + v[2] + v[2] + v[3] + v[3]).toLowerCase()
  if (/^#[0-9a-f]{6}/i.test(v)) return v.slice(0, 7).toLowerCase()
  return '#000000'
}

// —— 提交 / 预览 ——
function preview(f, to) {
  const k = realKey(f)
  emit('preview', props.items.map(it => ({ item: it, key: k, to })))
}
function commit(f, to, from) {
  const k = realKey(f)
  const entries = props.items.map(it => ({
    item: it,
    key: k,
    from: from === undefined ? effOf(it, k) : from,
    to
  }))
  emit('commit', entries)
  errs[f] = ''
}

// —— 数值校验：非法绝不写回 ——
function limitOf(f) {
  const m = meta(f)
  let max = m.max
  if (f === 'x' || f === 'w') max = Math.max(props.pageW, 0) || max
  if (f === 'y' || f === 'h') max = Math.max(props.pageH, 0) || max
  if (f === 'rot') { max = 360 }
  return { min: m.min === undefined ? -99999 : m.min, max: max === undefined ? 99999 : max }
}
function checkNum(f, raw) {
  const s = String(raw == null ? '' : raw).trim()
  // 可空字段（输入下限/上限）：留空 = 不限，写回 null
  if (!s && meta(f).nullable) return { val: null }
  if (!s) return { err: '不能为空' }
  if (!/^[-+]?\d*\.?\d+$/.test(s)) return { err: '只能填数字' }
  const n = Number(s)
  if (!isFinite(n)) return { err: '只能填数字' }
  const { min, max } = limitOf(f)
  if (n < min) return { err: `不能小于 ${min}` }
  if (n > max) return { err: `不能大于 ${max}` }
  return { val: Math.round(n * 1000) / 1000 }
}
const baseOf = {}

function numType(e, f) {
  const raw = e.target.value
  texts.value[f] = raw
  const r = checkNum(f, raw)
  if (r.err) { errs[f] = r.err; return }   // 非法：红框 + 提示，不动数据
  errs[f] = ''
  preview(f, r.val)
}
function numBlur(f, fromEnter) {
  const raw = texts.value[f]
  const r = checkNum(f, raw)
  if (r.err) {
    errs[f] = r.err
    // 保留红框和提示，但把输入框还原成数据里的真实值，避免用户以为已经改上了
    nextTick(() => { texts.value[f] = String(val(f) === undefined ? '' : val(f)) })
    return
  }
  errs[f] = ''
  const from = baseOf[f] === undefined ? val(f) : baseOf[f]
  if (Number(raw) !== Number(from)) commit(f, r.val, from)
  baseOf[f] = undefined
  if (fromEnter && inputs[f]) inputs[f].blur()
}

// 按住数值字段左右拖动：每像素 ±1，Shift ±10（WinCC 手感）
let nd = null
function numDown(e, f) {
  if (ro(f)) return
  e.preventDefault()                      // 不让浏览器抢焦点，拖动结束再决定是聚焦还是拖动
  const cur = checkNum(f, texts.value[f])
  nd = {
    f,
    x0: e.clientX,
    base: cur.err ? Number(val(f)) || 0 : cur.val,
    moved: false,
    last: null
  }
  baseOf[f] = nd.base
  window.addEventListener('mousemove', numMove)
  window.addEventListener('mouseup', numUp)
}
function numMove(e) {
  if (!nd) return
  const dx = e.clientX - nd.x0
  if (!nd.moved) {
    if (Math.abs(dx) < 3) return
    nd.moved = true
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'ew-resize'
  }
  const step = e.shiftKey ? 10 : 1
  const lim = limitOf(nd.f)
  let v = nd.base + Math.round(dx) * step
  v = Math.max(lim.min, Math.min(lim.max, v))
  nd.last = v
  texts.value[nd.f] = String(v)
  errs[nd.f] = ''
  preview(nd.f, v)
}
function numUp() {
  window.removeEventListener('mousemove', numMove)
  window.removeEventListener('mouseup', numUp)
  document.body.style.userSelect = ''
  document.body.style.cursor = ''
  const d = nd
  nd = null
  if (!d) return
  if (d.moved) {
    if (d.last != null) commit(d.f, d.last, d.base)
    // 拖完把焦点还给画布：否则焦点还停在面板输入框里，
    // Ctrl+Z / Delete 这些画布快捷键会被输入框吃掉，用户会以为撤销坏了
    if (inputs[d.f]) inputs[d.f].blur()
    const ae = document.activeElement
    if (ae && ae !== document.body && ae.blur) ae.blur()
  } else if (inputs[d.f]) {
    // 单击：进入键盘输入
    inputs[d.f].focus()
    inputs[d.f].select()
  }
}

// —— 颜色 ——
function pickColor(f, v, done) {
  const s = String(v || '').toLowerCase()
  texts.value[f] = s
  errs[f] = ''
  preview(f, s)
  if (done) commit(f, s)
}
function hexType(e, f) {
  const raw = e.target.value.trim()
  texts.value[f] = raw
  if (!/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(raw)) {
    errs[f] = '十六进制颜色要写成 #RGB 或 #RRGGBB'
    return
  }
  errs[f] = ''
  preview(f, raw.toLowerCase())
}
function hexBlur(f, fromEnter) {
  const raw = String(texts.value[f] || '').trim()
  if (!/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(raw)) {
    errs[f] = '十六进制颜色要写成 #RGB 或 #RRGGBB'
    nextTick(() => { texts.value[f] = hexOf(f) })
    return
  }
  errs[f] = ''
  const from = baseOf[f] === undefined ? val(f) : baseOf[f]
  commit(f, raw.toLowerCase(), from)
  baseOf[f] = undefined
  if (fromEnter && inputs[f]) inputs[f].blur()
}

// —— 下拉 / 开关 / 文本 ——
function pickOne(f, v) {
  const from = val(f)
  texts.value[f] = v === true || v === false ? (v ? '1' : '') : String(v)
  // 「视频通道」下拉的 value 是流名（S001-3）——拆成 ch 数字 + stream 流名一起写，
  // ch 给人看/给老逻辑用，stream 是真正取流用的（改名也不会错）
  if (f === 'ch' && typeof v === 'string' && v.includes('-')) {
    const seq = Number(v.split('-').pop())
    commit('ch', Number.isFinite(seq) ? seq : 0, from)
    commit('stream', v, val('stream'))
    return
  }
  commit(f, v, from)
}

// 视频通道下拉的选项：来自 props.channels
// 显示「3. 提升泵房(S001-3)」；H.265 标注不可播
function optionsOf(m) {
  if (m && m.optionsFrom === 'channels') {
    const list = props.channels || []
    if (!list.length) return [{ v: '', t: '（通道列表加载中…）' }]
    const out = [{ v: '', t: '（不指定，自动选第一路可播）' }]
    for (const c of list) {
      const bad = c.browser_ok === false
      // 存流名（主键派生，改通道顺序也不变），pickCam 第一优先级就是按流名精确匹配
      const codec = (c.codec || '').toUpperCase()
      const tag = codec === 'H264' ? 'H.264' : (codec === 'H265' ? 'H.265' : codec || '')
      out.push({
        v: c.stream,
        t: `${c.ch}. ${c.name}(${c.stream})${tag ? ' · ' + tag : ''}${bad ? ' — 浏览器不可播' : ''}`
      })
    }
    return out
  }
  if (m && m.optionsFrom === 'pages') {
    const list = props.pages || []
    if (!list.length) return [{ v: '', t: '（暂无组态画面）' }]
    const out = [{ v: '', t: '（不跳转）' }]
    for (const pg of list) {
      out.push({ v: String(pg.id), t: `${pg.name}${pg.published ? ' · 已发布' : ''}` })
    }
    return out
  }
  return (m && m.options) || []
}
function plainType(e, f) {
  texts.value[f] = e.target.value
  if (meta(f).type === 'text') {
    const max = meta(f).maxLen || 64
    if (e.target.value.length > max) { errs[f] = `最多 ${max} 个字符`; return }
    errs[f] = ''
    preview(f, e.target.value)
  }
}
function plainBlur(f, fromEnter) {
  const raw = String(texts.value[f] || '')
  const from = baseOf[f] === undefined ? val(f) : baseOf[f]
  commit(f, raw, from)
  baseOf[f] = undefined
  if (fromEnter && inputs[f]) inputs[f].blur()
}
function focusVal(f) { baseOf[f] = val(f) }

// —— 对象命名：同一画面内唯一，且不能只靠大小写区分 ——
function nameType(e) {
  const v = e.target.value
  texts.value.__name = v
  const t = v.trim()
  if (!t) { errs.__name = '名称不能为空'; return }
  if (isNameTaken(t, props.all, props.items[0])) { errs.__name = '名称已存在'; return }
  errs.__name = ''
}
function nameBlur() {
  const v = String(texts.value.__name || '').trim()
  if (!v) {
    // 清空视为恢复默认名（按类型编号）
    const def = defaultName(props.items[0].type, props.all, props.items[0])
    texts.value.__name = def
    commit('__name', def, props.items[0].name)
    errs.__name = ''
    return
  }
  if (isNameTaken(v, props.all, props.items[0])) {
    // 提示词 10 4.2 规则 3：重自动加后缀「名称(2)」，并提示
    let n = 2
    while (isNameTaken(`${v}(${n})`, props.all, props.items[0])) n++
    const nv = `${v}(${n})`
    ElMessage.info(`名称重复，已改为「${nv}」`)
    texts.value.__name = nv
    errs.__name = ''
    commit('__name', nv, props.items[0].name)
    return
  }
  errs.__name = ''
  if (v !== props.items[0].name) commit('__name', v, props.items[0].name)
}

// —— 背景图上传（P3 唯一需要后端的属性）——
function pickFile() { if (fileEl) fileEl.click() }
async function onFile(e, f) {
  const file = e.target.files && e.target.files[0]
  e.target.value = ''
  if (!file) return
  if (file.size > 5 * 1024 * 1024) { ElMessage.error('图片超过 5MB，请先压缩'); return }
  try {
    // 直接以文件本体做请求体（不走 multipart）：后端按 Content-Type 认格式、按长度限大小
    const res = await fetch('/api/upload', {
      method: 'POST',
      headers: {
        Authorization: 'Bearer ' + (localStorage.getItem('token') || ''),
        'Content-Type': file.type || 'application/octet-stream'
      },
      body: file
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || ('上传失败 ' + res.status))
    commit(f, data.url, val(f))
    texts.value[f] = data.url
    ElMessage.success('背景图已上传')
  } catch (err) {
    ElMessage.error(err.message || '上传失败')
  }
}

// —— 动态化（P4）：整块 dyn 一次提交，可 Ctrl+Z 撤回 ——
function onRulesCommit(entry) {
  // 条件规则表存在 item.rules，和 dyn 是两个独立字段
  commit('rules', entry.to, entry.from)
}
function onDynCommit(entry) {
  if (!props.items.length) return
  commit('dyn', entry.to, entry.from)
}

// 提示词 10 4.3：变量统一存 { site, point } 对象（不再写字符串表达式）
function onSetVar(v) {
  if (!props.items.length) return
  const it = props.items[0]
  const from = it.var ? JSON.parse(JSON.stringify(it.var)) : (it.var ?? null)
  // v=null 表示「解除绑定」（4.3：解除后对象就没有变量了，不能留空对象）
  if (!v) { commit('var', undefined, from); return }
  if (!v.site || !v.point) return
  commit('var', { site: String(v.site), point: String(v.point) }, from)
}

// —— 事件（P5）：整块 events 一次提交，可 Ctrl+Z 撤回 ——
function onEvCommit(entry) {
  if (!props.items.length) return
  commit('events', entry.to, entry.from)
  // 配完事件立刻重新绑定一次：不然要点一下别处才生效
  if (props.evCtx && props.evCtx.rebind) props.evCtx.rebind()
}

// —— 页签与同步 ——
function setTab(k) { tab.value = k; nextTick(syncTexts) }

function syncTexts() {
  const t = {}
  if (props.items.length === 1) t.__name = props.items[0].name || ''
  for (const tb of ['geom', 'look', 'font']) {
    const gs = (shared.value.groups && shared.value.groups[tb]) || []
    for (const g of gs) {
      for (const f of g.fields) {
        const m = meta(f)
        const v = val(f)
        if (m.type === 'color') t[f] = v === undefined ? '' : hexOf(f)
        else t[f] = v === undefined ? '' : String(v)
      }
    }
  }
  texts.value = t
  for (const k of Object.keys(errs)) delete errs[k]
}

watch(() => props.items, () => { nextTick(syncTexts) }, { immediate: true })
watch(() => props.all.length, () => { /* 增删对象后重算序号 */ })

const allFields = computed(() => {
  const s = []
  for (const tb of ['geom', 'look', 'font']) {
    for (const g of ((shared.value.groups && shared.value.groups[tb]) || [])) {
      for (const f of g.fields) if (!s.includes(f)) s.push(f)
    }
  }
  return s
})
const dynFields = computed(() => allFields.value.filter(f => meta(f).dyn))
const noDynFields = computed(() => allFields.value.filter(f => !meta(f).dyn))
const noDyn = computed(() => noDynFields.value.length)

</script>

<style scoped>
/* P8 组件模板实例：接口变量绑定 */
.fptb { margin: 6px 8px 8px; border: 1px solid #1e3a5f; border-radius: 4px; background: #0e1f33; }
.fptb-hd { display: flex; align-items: center; gap: 6px; padding: 6px 8px; font-size: 12px; color: #c3ddf5;
  border-bottom: 1px solid #16283d; font-weight: 600; }
.fptb-nm { color: #1ec8ff; font-weight: 400; }
.fptb-miss { margin-left: auto; color: #f1c40f; font-weight: 400; font-size: 11px; }
.fptb-empty { padding: 8px; color: #6b8fb3; font-size: 11px; }
.fptb-row { display: flex; align-items: center; gap: 5px; padding: 4px 8px; }
.fptb-lb { width: 92px; flex: 0 0 92px; display: flex; align-items: center; gap: 4px; font-size: 11px; color: #9fc3e8; }
.fptb-tp { color: #4a6d92; font-size: 10px; }
.fptb-in { flex: 1; min-width: 0; }
.fptb-in.miss { border-color: #f1c40f; }
.fptb-pick { flex: 0 0 auto; }
.fptb-tip { padding: 4px 8px 8px; color: #4a6d92; font-size: 10px; line-height: 1.5; }
.pp { display: flex; flex-direction: column; height: 100%; min-height: 0; color: #9fc3e8; font-size: 12px; }
.hd { flex: 0 0 auto; display: flex; align-items: center; gap: 6px; padding: 5px 8px;
      background: #0e1f33; border-bottom: 1px solid #16283d; }
.ttl { flex: 1; font-size: 12px; color: #cdeaff; font-weight: 600; overflow: hidden;
       text-overflow: ellipsis; white-space: nowrap; }
.badge { font-size: 10px; padding: 0 5px; border-radius: 8px; background: #1a3550; color: #7cc4ff; }
.fold { background: transparent; border: 1px solid #1e3a5f; color: #7ba3c9; cursor: pointer;
        width: 20px; height: 20px; line-height: 1; border-radius: 3px; padding: 0; }
.fold:hover { border-color: #1ec8ff; color: #cdeaff; }

.nm { display: flex; align-items: center; gap: 6px; padding: 5px 8px; border-bottom: 1px solid #16283d;
      flex-wrap: wrap; }
.nm label { width: 52px; flex: 0 0 52px; color: #7ba3c9; }
.ntxt { flex: 1; min-width: 0; background: #0a1626; border: 1px solid #1e3a5f; color: #e2e8f0;
        border-radius: 3px; padding: 2px 6px; font-size: 12px; }
.ntxt:focus { outline: none; border-color: #1ec8ff; }
.ntxt.err { border-color: #ef4444; box-shadow: 0 0 0 1px rgba(239,68,68,.35); }

/* 4.3：变量已失效（点位被删/停用）——红色，跟黄条区分开 */
.stalebar { flex: 0 0 auto; background: #3b1418; border-bottom: 1px solid #7f1d1d; padding: 7px 9px; }
.sb-t { font-size: 12px; color: #fca5a5; }
.sb-d { font-size: 11px; color: #c98a8a; margin-top: 3px; line-height: 1.5; }
.sb-b { margin-top: 5px; display: flex; gap: 6px; }

.legacybar { flex: 0 0 auto; background: #3a2f12; border-bottom: 1px solid #6b5320; padding: 7px 9px; }.lb-t { font-size: 12px; color: #f5c344; }
.lb-d { font-size: 11px; color: #b9a06a; margin-top: 3px; line-height: 1.5; }
.lb-b { margin-top: 5px; display: flex; gap: 6px; }
.tabs { flex: 0 0 auto; display: flex; border-bottom: 1px solid #16283d; background: #0b1622; }
.tab { flex: 1; text-align: center; padding: 5px 0; cursor: pointer; color: #6b8fb5; font-size: 11px;
       border-bottom: 2px solid transparent; user-select: none; }
.tab:hover { color: #cdeaff; }
.tab.on { color: #1ec8ff; border-bottom-color: #1ec8ff; background: #0e1f33; }

.bd { flex: 1; min-height: 0; overflow: auto; padding-bottom: 12px; }
.empty { padding: 22px 14px; color: #5b82a8; line-height: 1.9; }
.empty .sub { color: #3b5c82; font-size: 11px; }
.ro-tip { margin: 8px; padding: 5px 8px; background: rgba(245,158,11,.1); border: 1px solid #a16207;
          color: #fbbf24; font-size: 11px; border-radius: 3px; }

.grp { border-bottom: 1px solid #12233a; }
.grp-hd { padding: 4px 8px; color: #7ba3c9; font-size: 11px; background: #0c1a2b; letter-spacing: .3px; }
.row { display: flex; align-items: center; gap: 4px; padding: 3px 8px 3px 4px; position: relative;
       flex-wrap: wrap; }
.row:hover { background: #0c1a2b; }
.row.bad { background: rgba(239,68,68,.06); }
.dy { width: 12px; flex: 0 0 12px; text-align: center; font-size: 9px; color: #22384f; cursor: default; }
.dy.on { color: #2f6f96; }
.lb { flex: 0 0 62px; width: 62px; color: #8fb3d4; overflow: hidden; text-overflow: ellipsis;
      white-space: nowrap; }
.ctl { flex: 1; min-width: 0; display: flex; align-items: center; gap: 4px; }

.num, .hex, .txt, .sel {
  flex: 1; min-width: 0; width: 100%; background: #0a1626; border: 1px solid #1e3a5f; color: #e2e8f0;
  border-radius: 3px; padding: 2px 5px; font-size: 12px; font-family: Consolas, monospace;
}
.num { cursor: ew-resize; }
.num:focus, .hex:focus, .txt:focus, .sel:focus { outline: none; border-color: #1ec8ff; cursor: text; }
.num:disabled, .hex:disabled, .txt:disabled, .sel:disabled {
  background: #08111c; color: #4b6a8a; cursor: not-allowed;
}
.num.err, .hex.err, .txt.err { border-color: #ef4444; box-shadow: 0 0 0 1px rgba(239,68,68,.35); }
.unit { flex: 0 0 auto; color: #4b6a8a; font-size: 10px; width: 16px; }

.sw { position: relative; flex: 0 0 26px; width: 26px; height: 20px; border: 1px solid #1e3a5f;
      border-radius: 3px; overflow: hidden; cursor: pointer; }
.sw input { position: absolute; inset: -4px; width: 40px; height: 30px; opacity: 0; cursor: pointer; }
.hex { flex: 1; text-transform: lowercase; }

.sel { cursor: pointer; font-family: inherit; }
.sw-box { display: inline-flex; align-items: center; gap: 5px; cursor: pointer; color: #8fb3d4; }
.sw-box input { accent-color: #1ec8ff; }

.mini { background: #12233a; border: 1px solid #1e3a5f; color: #9fc3e8; border-radius: 3px;
        padding: 1px 7px; font-size: 11px; cursor: pointer; }
.mini:hover:not(:disabled) { border-color: #1ec8ff; color: #cdeaff; }
.mini:disabled { opacity: .45; cursor: not-allowed; }
.thumb { width: 30px; height: 20px; object-fit: cover; border: 1px solid #1e3a5f; border-radius: 2px; }
.file { display: none; }

.tip { width: 100%; padding-left: 78px; color: #f87171; font-size: 10px; line-height: 1.5; }
.tip.inline { width: auto; padding-left: 0; }

.dynwrap { padding-bottom: 8px; }
.ph { padding: 14px; line-height: 1.9; color: #5b82a8; }
.ph-t { color: #cdeaff; font-weight: 600; margin-bottom: 6px; }
.ph-d { font-size: 11px; color: #6b8fb5; }
.ph-l { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; }
.chip { font-size: 10px; padding: 1px 6px; border-radius: 8px; background: #12233a;
        border: 1px solid #1e3a5f; color: #8fb3d4; }
.chip.off { color: #43607f; text-decoration: line-through; }

/* 保存栏：每个页签内容的下方 */
.save-bar { display: flex; align-items: center; gap: 10px; padding: 10px 12px;
  border-top: 1px solid #22364a; margin-top: 10px; }
.save-btn { min-width: 80px; height: 26px; font-size: 12px; cursor: pointer;
  background: #2f6fb3; color: #fff; border: 1px solid #3b83cc; border-radius: 3px; }
.save-btn:hover:not(:disabled) { background: #3884cf; }
.save-btn:disabled { background: #2a3b4c; color: #6b8299; border-color: #34495e; cursor: not-allowed; }
.save-hint { font-size: 11px; color: #5b82a8; }

/* 视频窗诊断行 */
.vdiag { margin: 8px 12px 0; padding: 6px 10px; border-radius: 3px; font-size: 11px;
  line-height: 1.5; font-family: Consolas, monospace; }
.vdiag.ok   { background: #0f2a1c; color: #6ee7a0; border: 1px solid #1d5033; }
.vdiag.warn { background: #2e2410; color: #f5c451; border: 1px solid #5c4515; }
.vdiag.err  { background: #2e1414; color: #f88;    border: 1px solid #5c2020; }
</style>
