<template>
  <div class="palette">
    <div v-for="g in groups" :key="g.key" class="grp">
      <div class="grp-hd" @click="toggle(g.key)">
        <span class="caret" :class="{ open: !collapsed[g.key] }">▶</span>
        <span class="ttl">{{ g.title }}</span>
        <span class="cnt">{{ g.items.length }}</span>
        <button class="addbtn" :title="'添加自定义图元到「' + g.title + '」'"
                @click.stop="openAdd(g)">＋</button>
      </div>
      <div v-show="!collapsed[g.key]" class="grid">
        <div v-for="it in g.items" :key="it.key" class="item"
             :class="{ active: picked && picked.key === it.key, grab: it.drag }"
             :title="it.tip"
             :draggable="!!it.drag"
             @click="pick(it)"
             @dragstart="onDragStart($event, it)">
          <img v-if="it.img" class="ic-img" :src="it.img" alt="">
          <svg v-else class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"
               v-html="it.icon"></svg>
          <span class="nm">{{ it.name }}</span>
          <span v-if="it.cid" class="del" title="从对象库删除（已拖到画面的不受影响）"
                @click.stop="removeObj(it)">×</span>
        </div>
      </div>
    </div>
    <div class="hint">
      标准对象/智能对象/工艺图元/大屏组件/控件：点选后在画布单击一次落位<br>
      符号库图元 / 组件模板 / 自定义图元：可拖放到画布（也可点选落位）<br>
      <b>每组右上角「＋」可添加自己做的图</b>——先用「对象图元转换器」把白底图转成透明 PNG
    </div>

    <!-- 添加自定义图元 -->
    <div v-if="addOpen" class="mask" @click.self="addOpen = false">
      <div class="dlg">
        <div class="dlg-hd">添加自定义图元 → 「{{ addGroupTitle }}」</div>
        <div class="row">
          <label>名称</label>
          <input v-model="addName" maxlength="64" placeholder="如：粗格栅除污机">
        </div>
        <div class="row">
          <label>图片</label>
          <button class="mini" @click="pickImg">{{ addUrl ? '重新选择…' : '选择图片…' }}</button>
          <span v-if="uploading" class="mut">上传中…</span>
          <img v-if="addUrl" :src="addUrl" class="prev" alt="">
          <input ref="fileEl" type="file" accept="image/png,image/jpeg,image/webp,image/gif"
                 style="display:none" @change="onFile">
        </div>
        <div class="row">
          <label>显示尺寸</label>
          <input v-model.number="addW" type="number" min="8" max="2000" class="num"> ×
          <input v-model.number="addH" type="number" min="8" max="2000" class="num"> px
          <span class="mut">拖到画布后的默认大小</span>
        </div>
        <div v-if="addErr" class="err">{{ addErr }}</div>
        <div class="dlg-ft">
          <button class="mini" @click="addOpen = false">取消</button>
          <button class="mini primary" :disabled="!addName.trim() || !addUrl || uploading"
                  @click="doAdd">确定添加</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
// 对象库（WinCC Graphics Designer 的「对象选项板 + 库」二合一）
// 两套插入交互按官方区分：
//   选项板（标准/智能/工艺图元）—— 点选 → 画布单击落位，不能拖放
//   库（符号库）—— 可拖放
import { computed, onMounted, reactive, ref } from 'vue'
import { get, post, del } from '../utils/request'
import { CONTROL_TYPES, CONTROL_GROUPS } from './controls/registry'
import { ALL_SYMBOLS, symbolSvg } from './controls/symbols'

const props = defineProps({
  // P8：组件模板列表（编辑器从 /api/fpt 拉，注入到「组件模板」组）
  faceplates: { type: Array, default: () => [] }
})
const emit = defineEmits(['pick', 'drop'])

const collapsed = reactive({ std: false, smart: false, craft: false, deck: false, ctrl: false, fpt: false, sym: true })
const picked = ref(null)

function toggle(k) { collapsed[k] = !collapsed[k] }

const c = 'currentColor'
const ICON = {
  line: `<line x1="3" y1="12" x2="21" y2="12" stroke="${c}"/>`,
  polyline: `<polyline points="3,17 9,7 15,17 21,9" stroke="${c}"/>`,
  polygon: `<polygon points="12,4 21,20 3,20" stroke="${c}"/>`,
  rect: `<rect x="3" y="6" width="18" height="12" stroke="${c}"/>`,
  circle: `<circle cx="12" cy="12" r="8" stroke="${c}"/>`,
  ellipse: `<ellipse cx="12" cy="12" rx="9" ry="6" stroke="${c}"/>`,
  arc: `<path d="M3 18 A 9 9 0 0 1 21 18" stroke="${c}"/>`,
  text: `<path d="M5 6h14M12 6v13M9 19h6" stroke="${c}"/>`,
  value: `<rect x="2" y="7" width="20" height="10" rx="1" stroke="${c}"/><path d="M6 12h6M16 12h3" stroke="${c}"/>`,
  input: `<rect x="2" y="7" width="20" height="10" rx="1" stroke="${c}"/><rect x="16" y="7" width="6" height="10" fill="${c}" opacity=".35" stroke="none"/><path d="M6 12h5" stroke="${c}"/>`,
  button: `<rect x="3" y="7" width="18" height="10" rx="2" stroke="${c}"/><path d="M8 12h8" stroke="${c}"/>`,
  trendico: `<rect x="2" y="4" width="20" height="16" rx="1" stroke="${c}"/><polyline points="4,16 9,9 13,13 20,6" stroke="${c}"/>`,
  alarmico: `<rect x="2" y="4" width="20" height="16" rx="1" stroke="${c}"/><path d="M5 9h9M5 13h13M5 17h7" stroke="${c}"/>`,
  image: `<rect x="3" y="5" width="18" height="14" rx="1" stroke="${c}"/><circle cx="8" cy="10" r="1.6" stroke="${c}"/><path d="M4 17l5-5 4 4 3-3 4 4" stroke="${c}"/>`,
  fpt: `<rect x="2.5" y="3.5" width="19" height="17" rx="2" stroke="${c}" stroke-dasharray="3 2"/><rect x="6" y="7" width="6" height="6" stroke="${c}"/><circle cx="16.5" cy="10" r="2" stroke="${c}"/><path d="M6 17h12" stroke="${c}"/>`,
  tank: `<path d="M6 4h12v13a6 6 0 0 1-12 0z" stroke="${c}"/><path d="M6 13h12" stroke="${c}"/>`,
  pumpv: `<circle cx="12" cy="12" r="5" stroke="${c}"/><path d="M12 2v5M12 17v5" stroke="${c}"/>`,
  pumph: `<circle cx="12" cy="12" r="5" stroke="${c}"/><path d="M2 12h5M17 12h5" stroke="${c}"/>`,
  valve: `<path d="M12 3v18" stroke="${c}"/><path d="M6 7v10l6-5zM18 7v10l-6-5z" stroke="${c}"/>`,
  pipeh: `<rect x="2" y="9" width="20" height="6" stroke="${c}"/>`,
  pipev: `<rect x="9" y="2" width="6" height="20" stroke="${c}"/>`,
  pipet: `<path d="M2 6h20M12 6v16" stroke="${c}" stroke-width="3"/>`,
  elbow: `<path d="M6 3v15h15" stroke="${c}" stroke-width="3"/>`,
  fan: `<circle cx="12" cy="12" r="8" stroke="${c}"/><path d="M12 12l5-3-1 5zM12 12l-4 4-1-5zM12 12l-1-5 5 2z" stroke="${c}"/>`,
  grill: `<rect x="3" y="4" width="18" height="16" stroke="${c}"/><path d="M8 4v16M12 4v16M16 4v16" stroke="${c}"/>`,
  conveyor: `<rect x="2" y="9" width="20" height="5" stroke="${c}"/><circle cx="5" cy="16" r="2" stroke="${c}"/><circle cx="19" cy="16" r="2" stroke="${c}"/>`,
  tableico: `<rect x="2" y="4" width="20" height="16" stroke="${c}"/><path d="M2 9h20M2 14h20M9 9v11M15 9v11" stroke="${c}"/>`,
  xyico: `<path d="M4 3v17h17" stroke="${c}"/><path d="M6 17c4-10 8 2 14-8" stroke="${c}"/>`,
  gaugeico: `<path d="M4 18a8 8 0 0 1 16 0" stroke="${c}"/><path d="M12 18l5-6" stroke="${c}"/><path d="M5 14l1 1M12 10v2M19 14l-1 1" stroke="${c}"/>`,
  clockico: `<circle cx="12" cy="12" r="8" stroke="${c}"/><path d="M12 7v5l4 2" stroke="${c}"/>`,
  videoico: `<rect x="2" y="6" width="14" height="12" rx="1" stroke="${c}"/><path d="M16 11l6-3v8l-6-3z" stroke="${c}"/>`,
  symbolico: `<rect x="2" y="2" width="20" height="20" stroke="${c}"/><rect x="5" y="5" width="5" height="5" stroke="${c}"/><rect x="14" y="5" width="5" height="5" stroke="${c}"/><rect x="5" y="14" width="5" height="5" stroke="${c}"/><rect x="14" y="14" width="5" height="5" stroke="${c}"/>`,
  // 提示词 11：scada-deck 大屏组件
  kpi: `<rect x="3" y="5" width="18" height="14" rx="2" stroke="${c}"/><path d="M6 5v14" stroke="${c}" stroke-width="2.5"/><path d="M9 10h6M9 14h9" stroke="${c}"/>`,
  progress: `<rect x="2" y="10" width="20" height="4" rx="2" stroke="${c}"/><rect x="2" y="10" width="9" height="4" rx="2" fill="${c}" stroke="none" opacity=".6"/>`,
  ring: `<circle cx="12" cy="12" r="8" stroke="${c}"/><path d="M12 4a8 8 0 0 1 8 8" stroke="${c}" stroke-width="2.5"/>`,
  statusbadge: `<circle cx="7" cy="12" r="2.5" fill="${c}" stroke="none"/><path d="M12 12h8" stroke="${c}"/>`,
  panel: `<rect x="2.5" y="4.5" width="19" height="15" rx="2" stroke="${c}"/><path d="M2.5 9h19" stroke="${c}"/>`
}

// 每项：type 对应 render.js 的渲染分支；w/h 是插入默认尺寸
function d(type, name, icon, w, h, extra = {}) {
  // icon 可以是 ICON 的键，也可以直接给一段 svg（符号库图元用真实形状做缩略图）
  const svg = typeof icon === 'string' && icon.trim().startsWith('<') ? icon : ICON[icon]
  return { key: type + '|' + name + '|' + (extra.control || extra.symbol || extra.fptId || ''), type, name, icon: svg, w, h, tip: `${name}（${w}×${h}）`, ...extra }
}

// 控件分组：直接由注册表生成，别再手写一份（写两份就会漂）
const CTRL_ITEMS = Object.keys(CONTROL_TYPES).map(k => {
  const c = CONTROL_TYPES[k]
  return d('control', c.name, c.icon, c.w, c.h, { control: k })
})

// 符号库图元：14 个工艺符号，缩略图用图元自己的形状
const SYM_ITEMS = ALL_SYMBOLS.map(s => d('symbol', s.name, symbolSvg(s.id, 24, 24,
  { stroke: 'currentColor', accent: 'currentColor', text: 'currentColor', bg: 'transparent', sw: 4 }),
  80, 80, { symbol: s.id, drag: true }))

const baseGroups = [
  {
    key: 'std', title: '标准对象', items: [
      d('line', '线', 'line', 200, 8),
      d('polyline', '折线', 'polyline', 200, 100),
      d('polygon', '多边形', 'polygon', 160, 120),
      d('rect', '矩形', 'rect', 160, 100),
      d('circle', '圆', 'circle', 100, 100),
      d('ellipse', '椭圆', 'ellipse', 160, 100),
      d('arc', '圆弧', 'arc', 160, 80),
      d('text', '静态文本', 'text', 160, 40)
    ]
  },
  {
    key: 'smart', title: '智能对象', items: [
      // 修复 09：两个入口，靠属性面板的「类型」切三种模式（不要三个入口，用户会困惑）
      d('value', 'I/O 域（仅显示）', 'value', 180, 36, { mode: 'output' }),
      d('value', 'I/O 域（可输入）', 'value', 180, 36, { mode: 'inputoutput' }),
      d('button', '按钮', 'button', 120, 44),
      d('trend', '趋势曲线', 'trendico', 400, 240),
      d('alarm_list', '报警窗口', 'alarmico', 400, 240),
      d('image', '图形对象（图片）', 'image', 200, 150)
    ]
  },
  {
    key: 'craft', title: '工艺图元', items: [
      d('tank', '液位罐', 'tank', 160, 260),
      d('pump_v', '立式泵', 'pumpv', 90, 120),
      d('pump_h', '卧式泵', 'pumph', 120, 90),
      d('valve', '阀门', 'valve', 60, 60),
      d('pipe', '管道（水平）', 'pipeh', 200, 20),
      d('pipe_v', '管道（垂直）', 'pipev', 20, 200),
      d('pipe_t', '管道（T 形）', 'pipet', 120, 100),
      d('pipe_elbow', '管道（弯头）', 'elbow', 100, 100),
      d('fan', '风机', 'fan', 100, 100),
      d('grill', '格栅', 'grill', 160, 100),
      d('conveyor', '皮带输送机', 'conveyor', 240, 80)
    ]
  },
  {
    key: 'deck', title: '大屏组件（scada-deck）', items: [
      d('kpi', 'KPI 卡', 'kpi', 200, 90, { text: '指标' }),
      d('progress', '进度条', 'progress', 220, 44),
      d('ring', '环形进度', 'ring', 120, 130),
      d('statusbadge', '状态徽章', 'statusbadge', 180, 34, { text: '状态' }),
      d('panel', '面板卡', 'panel', 300, 200, { text: '面板' })
    ]
  },
  {
    key: 'ctrl', title: '控件（P6 八件套）', items: CTRL_ITEMS
  },
  {
    key: 'sym', title: '符号库图元', items: SYM_ITEMS
  }
]

function pick(it) {
  // 两种插入方式都支持：点选 → 画布单击落位；可拖的（符号库/组件模板/自定义图元）也能直接拖。
  // 原来这里 `if (it.drag) return` 把可拖项的「点选落位」也挡掉了，
  // 导致自定义图元点了没反应。
  picked.value = picked.value && picked.value.key === it.key ? null : it
  emit('pick', picked.value)
}

function onDragStart(e, it) {
  if (!it.drag) { e.preventDefault(); return }
  e.dataTransfer.effectAllowed = 'copy'
  e.dataTransfer.setData('text/scada-object',
    JSON.stringify({ type: it.type, w: it.w, h: it.h, name: it.name, symbol: it.symbol, control: it.control, fptId: it.fptId }))
}

// 组件模板组：有模板才显示（空组不占地方）
const FPT_ITEMS = computed(() => (props.faceplates || []).map(f =>
  d('faceplate', f.name, 'fpt', f.w || 200, f.h || 200, { fptId: f.id, drag: true })))

const groups = computed(() => {
  // 浅拷贝一层，避免往静态 baseGroups 里 push 自定义项（重算会翻倍）
  const gs = baseGroups.map(g => ({ ...g, items: g.items.slice() }))
  // 自定义图元按 group_key 归到对应组末尾
  for (const o of customObjs.value) {
    const g = gs.find(x => x.key === o.group_key)
    if (!g) continue
    g.items.push({
      key: 'custom|' + o.id, type: 'image', name: o.name,
      w: o.w, h: o.h, src: o.image_url, img: o.image_url,
      tip: `${o.name} · 自定义图元 ${o.w}×${o.h}（可拖放 / 点选落位）`,
      drag: true, cid: o.id
    })
  }
  if (FPT_ITEMS.value.length) {
    // 放在控件之后、符号库之前（模板是"复合对象"，跟符号库一样能拖）
    const at = gs.findIndex(g => g.key === 'sym')
    gs.splice(at < 0 ? gs.length : at, 0, { key: 'fpt', title: '组件模板', items: FPT_ITEMS.value })
  }
  return gs
})

// 外部（编辑器）落位完成后清掉选中态
defineExpose({ clear: () => { picked.value = null } })

// ================= 自定义图元（每组可加自己做的图） =================
// 图元存库（custom_object 表）而不是塞进画面 json：做一次，所有画面都能拖。
// 图片走既有的 /api/upload（PNG/JPEG/WebP/GIF，≤5MB，不收 SVG）。
const customObjs = ref([])
const addOpen = ref(false)
const addGroup = ref('craft')
const addGroupTitle = ref('')
const addName = ref('')
const addUrl = ref('')
const addW = ref(120)
const addH = ref(60)
const addErr = ref('')
const uploading = ref(false)
const fileEl = ref(null)

async function loadCustom() {
  try {
    const r = await get('/api/custom-objects')
    customObjs.value = r.items || []
  } catch (e) {
    customObjs.value = []
  }
}

function openAdd(g) {
  addGroup.value = g.key
  addGroupTitle.value = g.title
  addName.value = ''
  addUrl.value = ''
  addW.value = 120
  addH.value = 60
  addErr.value = ''
  addOpen.value = true
}

function pickImg() {
  if (fileEl.value) fileEl.value.click()
}

async function onFile(e) {
  const f = e.target.files && e.target.files[0]
  e.target.value = ''
  if (!f) return
  if (f.size > 5 * 1024 * 1024) {
    addErr.value = '图片超过 5MB，请先用「对象图元转换器」压缩'
    return
  }
  uploading.value = true
  addErr.value = ''
  try {
    const res = await fetch('/api/upload', {
      method: 'POST',
      headers: {
        Authorization: 'Bearer ' + (localStorage.getItem('token') || ''),
        'Content-Type': f.type || 'application/octet-stream'
      },
      body: f
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || ('上传失败 ' + res.status))
    addUrl.value = data.url
    // 按原图比例给个合适的默认尺寸（长边不超过 160）
    const im = new Image()
    im.onload = () => {
      const k = Math.min(1, 160 / Math.max(im.width, im.height))
      addW.value = Math.max(8, Math.round(im.width * k))
      addH.value = Math.max(8, Math.round(im.height * k))
    }
    im.src = data.url
  } catch (err) {
    addErr.value = (err && err.message) || '上传失败'
  } finally {
    uploading.value = false
  }
}

async function doAdd() {
  addErr.value = ''
  try {
    await post('/api/custom-object', {
      group_key: addGroup.value,
      name: addName.value.trim(),
      image_url: addUrl.value,
      w: addW.value,
      h: addH.value
    })
    addOpen.value = false
    await loadCustom()
  } catch (e) {
    addErr.value = (e && e.message) || '添加失败'
  }
}

async function removeObj(it) {
  if (!confirm('从对象库删除「' + it.name + '」？\n（已经拖到画面上的不受影响）')) return
  try {
    await del('/api/custom-object/' + it.cid)
    await loadCustom()
  } catch (e) {
    alert((e && e.message) || '删除失败')
  }
}

onMounted(loadCustom)

</script>

<style scoped>
.palette { font-size: 12px; color: #9fc3e8; padding-bottom: 8px; }
.grp { border-bottom: 1px solid #16283d; }
.grp-hd { display: flex; align-items: center; gap: 6px; padding: 7px 8px; cursor: pointer; user-select: none; }
.grp-hd:hover { background: #12233a; }
.caret { font-size: 9px; transition: transform .15s; color: #5b82a8; }
.caret.open { transform: rotate(90deg); }
.ttl { flex: 1; font-weight: 600; color: #c3ddf5; }
.cnt { color: #4a6d92; font-size: 11px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; padding: 0 6px 8px; }
.item { display: flex; align-items: center; gap: 5px; padding: 5px 6px; border: 1px solid transparent; border-radius: 3px; cursor: pointer; }
.item:hover { background: #12233a; border-color: #1e3a5f; }
.item.active { background: #123a5c; border-color: #1ec8ff; color: #fff; }
.item.grab { cursor: grab; }
.item.grab:active { cursor: grabbing; }
.ic { width: 18px; height: 18px; flex: 0 0 18px; color: #6fa8d8; }
.item.active .ic { color: #1ec8ff; }
.nm { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.hint { padding: 8px 10px; color: #4a6d92; line-height: 1.6; font-size: 11px; }

/* ===== 自定义图元 ===== */
.addbtn { width: 18px; height: 18px; line-height: 16px; border: 1px solid #2c4a6e;
          background: #12233a; color: #7cc4ff; border-radius: 3px; cursor: pointer;
          font-size: 13px; padding: 0; flex: 0 0 18px; }
.addbtn:hover { background: #1a3350; border-color: #1ec8ff; color: #fff; }
.item { position: relative; }
.ic-img { width: 18px; height: 18px; flex: 0 0 18px; object-fit: contain; }
.del { position: absolute; right: 1px; top: 1px; width: 14px; height: 14px; line-height: 12px;
       text-align: center; border-radius: 50%; background: #7f1d1d; color: #fff;
       font-size: 11px; cursor: pointer; opacity: 0; transition: opacity .12s; }
.item:hover .del { opacity: 1; }
.mask { position: fixed; inset: 0; background: rgba(0,0,0,.55); z-index: 3000;
        display: flex; align-items: center; justify-content: center; }
.dlg { background: #0f2238; border: 1px solid #2c4a6e; border-radius: 8px; padding: 16px;
       width: 430px; box-shadow: 0 20px 60px rgba(0,0,0,.5); color: #9fc3e8; }
.dlg-hd { font-weight: 600; color: #c3ddf5; margin-bottom: 14px; font-size: 13px; }
.row { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.row label { width: 64px; color: #7ea7cc; flex: 0 0 64px; }
.row input { flex: 1; background: #0a1826; border: 1px solid #24405c; color: #e2e8f0;
             border-radius: 4px; padding: 5px 8px; font-size: 12px; }
.row input.num { flex: 0 0 70px; }
.mini { background: #12233a; border: 1px solid #24405c; color: #9fc3e8; border-radius: 4px;
        padding: 5px 10px; font-size: 12px; cursor: pointer; }
.mini:hover { border-color: #1ec8ff; }
.mini.primary { background: #1f6feb; border-color: #1f6feb; color: #fff; }
.mini:disabled { opacity: .45; cursor: not-allowed; }
.prev { width: 46px; height: 46px; object-fit: contain; background: #0a1826;
        border: 1px solid #24405c; border-radius: 4px; }
.mut { color: #5b82a8; font-size: 11px; }
.err { color: #f87171; font-size: 12px; margin-bottom: 8px; }
.dlg-ft { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
</style>
