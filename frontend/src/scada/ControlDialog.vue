<template>
  <el-dialog v-model="open" :title="'配置 ' + def.name" width="720px" append-to-body
             :close-on-click-modal="false" class="cdlg" @open="reset">
    <div class="cd">
      <div class="hd">
        <span class="nm">{{ def.name }}</span>
        <span class="tip">{{ def.tip }}</span>
        <span class="sp" />
        <span class="sz">最小 {{ def.minW }}×{{ def.minH }}</span>
      </div>

      <div class="body">
        <div v-for="f in form" :key="f.k" class="row" :class="{ wide: f.t === 'vars' || f.t === 'ranges' || f.t === 'cols' }">
          <label class="lb">{{ f.label }}<i v-if="f.hint" class="hint">{{ f.hint }}</i></label>

          <template v-if="f.t === 'text'">
            <el-input v-model="draft[f.k]" size="small" :placeholder="f.ph || ''" />
          </template>

          <template v-else-if="f.t === 'num'">
            <el-input-number v-model="draft[f.k]" size="small" :min="f.min" :max="f.max" :step="f.step || 1"
                             :controls="false" style="width:120px" />
          </template>

          <template v-else-if="f.t === 'bool'">
            <el-switch v-model="draft[f.k]" size="small" />
          </template>

          <template v-else-if="f.t === 'select'">
            <el-select v-model="draft[f.k]" size="small" style="width:240px">
              <el-option v-for="o in optsOf(f)" :key="o.v" :label="o.t" :value="o.v" />
            </el-select>
          </template>

          <template v-else-if="f.t === 'color'">
            <div class="cr">
              <input type="color" v-model="draft[f.k]" class="cp" />
              <span class="hex">{{ draft[f.k] }}</span>
            </div>
          </template>

          <template v-else-if="f.t === 'expr'">
            <div class="ex">
              <el-input v-model="draft[f.k]" size="small" placeholder="如 S001.LEVEL 或 @CurrentSite + '.LEVEL'" />
              <button class="pb" @click="pickVar(f.k, null, null)">选变量</button>
            </div>
          </template>

          <!-- 变量列表（趋势/表格） -->
          <template v-else-if="f.t === 'vars'">
            <div class="vlist">
              <div v-for="(v, i) in draft[f.k]" :key="i" class="vrow">
                <el-input v-model="v.expr" size="small" placeholder="变量表达式（S001.LEVEL）" class="vi" />
                <button class="pb" @click="pickVar(f.k, i, 'expr')">选</button>
                <template v-if="f.color">
                  <input type="color" v-model="v.color" class="cp sm" />
                </template>
                <template v-if="f.width">
                  <el-input-number v-model="v.width" size="small" :min="1" :max="6" :controls="false" style="width:52px" />
                </template>
                <template v-if="f.label">
                  <el-input v-model="v.label" size="small" placeholder="列名" style="width:90px" />
                </template>
                <template v-if="f.decimals">
                  <el-input-number v-model="v.decimals" size="small" :min="0" :max="6" :controls="false"
                                   style="width:52px" />
                </template>
                <el-checkbox v-if="f.visible" v-model="v.visible" size="small" title="显示" />
                <button class="xb" title="删除" @click="draft[f.k].splice(i, 1)">×</button>
              </div>
              <button class="ab" @click="addVar(f)">+ 增加一条</button>
            </div>
          </template>

          <!-- 分区色（仪表盘） -->
          <template v-else-if="f.t === 'ranges'">
            <div class="vlist">
              <div v-for="(r, i) in draft[f.k]" :key="i" class="vrow">
                <el-input-number v-model="r.from" size="small" :controls="false" style="width:64px" />
                <span class="dash">~</span>
                <el-input-number v-model="r.to" size="small" :controls="false" style="width:64px" />
                <input type="color" v-model="r.color" class="cp sm" />
                <span class="hex">{{ r.color }}</span>
                <button class="xb" @click="draft[f.k].splice(i, 1)">×</button>
              </div>
              <button class="ab" @click="draft[f.k].push({ from: 0, to: 100, color: '#22c55e' })">+ 增加一段</button>
            </div>
          </template>

          <!-- 列选择（报警窗） -->
          <template v-else-if="f.t === 'cols'">
            <div class="cols">
              <label v-for="o in f.opts" :key="o.v" class="cb">
                <input type="checkbox" :value="o.v" v-model="draft[f.k]" /> {{ o.t }}
              </label>
            </div>
          </template>
        </div>
      </div>
    </div>

    <template #footer>
      <button class="ft-b ghost" @click="open = false">取消</button>
      <button class="ft-b" @click="save">确定</button>
    </template>

    <VarPicker v-model="pickerOpen" :sites="sites" :site="curSite" :writable="false"
               @pick="onPick" />
  </el-dialog>
</template>

<script setup>
// 控件配置对话框（P6）——双击控件打开
// 为什么不做在属性面板里：趋势有曲线列表、报警窗有列选择、仪表盘有分区色，
// 塞进 280px 宽的面板里就没法用了（任务书：双击控件打开配置对话框）。
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { get } from '../utils/request'
import { controlDef } from './controls/registry'
import VarPicker from './VarPicker.vue'
// 变量在数据里是 {site,point} 对象，但 el-input 只能显示字符串：
// 载入/选取时 tagText 拍平，保存时 toVar 还原。否则输入框显示 [object Object]。
import { tagText, toVar } from './varbind'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  item: { type: Object, default: null },
  sites: { type: Array, default: () => [] },
  curSite: { type: String, default: '' }
})
const emit = defineEmits(['update:modelValue', 'save'])

const open = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v)
})
const def = computed(() => controlDef(props.item && props.item.control))
// 打开弹窗就拉一次通道清单：视频控件的「视频通道」下拉要用
watch(() => props.modelValue, (v) => { if (v && props.item && props.item.control === 'video') loadChannels() })
// 视频通道下拉：选项来自 /api/video/cameras，
// 顺序和 VideoControl 取路的 items 下标完全一致（channel = 下标+1）。
const channels = ref([])

function optsOf(f) {
  if (f && f.optsFrom === 'channels') {
    const out = channels.value.map((c, i) => {
      const codec = String(c.codec || '').toUpperCase()
      const tag = codec === 'H264' ? 'H.264' : (codec === 'H265' ? 'H.265 · 浏览器不可播' : '')
      return { v: String(i + 1), t: `${i + 1}. ${c.name || c.stream}（${c.stream}）${tag ? ' · ' + tag : ''}` }
    })
    return out.length ? out : [{ v: '1', t: '（当前站点还没有视频通道）' }]
  }
  return (f && f.opts) || []
}

async function loadChannels() {
  try {
    const site = props.curSite || ''
    if (!site) { channels.value = []; return }
    const r = await get('/api/video/cameras?site=' + encodeURIComponent(site), { silent: true })
    channels.value = r.items || []
  } catch (e) { channels.value = [] }
}

const draft = ref({})

const pickerOpen = ref(false)
const target = ref(null)

const TIME_SPANS = [
  { v: '5m', t: '5 分钟（实时）' }, { v: '30m', t: '30 分钟' }, { v: '1h', t: '1 小时' },
  { v: '8h', t: '8 小时' }, { v: '24h', t: '24 小时' }, { v: 'custom', t: '自定义（分钟）' }
]
const COLS = [
  { v: 'time', t: '时间' }, { v: 'site', t: '站点' }, { v: 'point', t: '点位' },
  { v: 'msg', t: '内容' }, { v: 'level', t: '级别' }, { v: 'state', t: '状态' }, { v: 'count', t: '次数' }
]

const FORM = {
  alarm: [
    { k: 'title', label: '标题', t: 'text' },
    { k: 'source', label: '数据源', t: 'select', opts: [{ v: 'current', t: '当前站点（@CurrentSite）' }, { v: 'global', t: '全部站点' }] },
    { k: 'vars', label: '只显示这些变量（空=全部）', t: 'vars' },
    { k: 'maxRows', label: '最多显示行数', t: 'num', min: 1, max: 500 },
    { k: 'onlyUnacked', label: '只显示未确认', t: 'bool' },
    { k: 'blinkNew', label: '新报警闪烁 3 次', t: 'bool' },
    { k: 'autoScroll', label: '自动滚动到最新', t: 'bool' },
    { k: 'columns', label: '显示列', t: 'cols', opts: COLS }
  ],
  trend: [
    { k: 'title', label: '标题', t: 'text' },
    { k: 'vars', label: '曲线', t: 'vars', color: true, width: true, visible: true },
    { k: 'timeSpan', label: '时间跨度', t: 'select', opts: TIME_SPANS },
    { k: 'customMinutes', label: '自定义跨度', t: 'num', min: 1, max: 43200, hint: '仅“自定义”时生效，单位分钟' },
    { k: 'refresh', label: '刷新周期', t: 'select', opts: [{ v: 1, t: '1 秒' }, { v: 5, t: '5 秒（推荐）' }, { v: 10, t: '10 秒' }] },
    { k: 'yMode', label: 'Y 轴', t: 'select', opts: [{ v: 'auto', t: '自动量程' }, { v: 'fixed', t: '固定量程' }] },
    { k: 'yMin', label: '下限', t: 'num', min: -1e9, max: 1e9 },
    { k: 'yMax', label: '上限', t: 'num', min: -1e9, max: 1e9 },
    { k: 'legend', label: '图例位置', t: 'select', opts: [{ v: 'top', t: '顶部' }, { v: 'right', t: '右侧' }, { v: 'hidden', t: '不显示' }] },
    { k: 'grid', label: '网格', t: 'bool' },
    { k: 'crosshair', label: '十字线 + 悬停数值', t: 'bool' }
  ],
  table: [
    { k: 'title', label: '标题', t: 'text' },
    { k: 'vars', label: '列', t: 'vars', label: true, decimals: true },
    { k: 'pageSize', label: '每页行数', t: 'num', min: 1, max: 200 },
    { k: 'showTime', label: '显示时间列', t: 'bool' },
    { k: 'exportCsv', label: '允许导出 CSV', t: 'bool', hint: '导出带 BOM，Excel 打开不乱码' }
  ],
  xyTrend: [
    { k: 'title', label: '标题', t: 'text' },
    { k: 'xVar', label: 'X 轴变量', t: 'expr' },
    { k: 'yVars', label: 'Y 轴曲线', t: 'vars', color: true },
    { k: 'minutes', label: '取数时间窗', t: 'num', min: 1, max: 43200, hint: '分钟' },
    { k: 'grid', label: '网格', t: 'bool' },
    { k: 'pointSize', label: '点大小', t: 'num', min: 1, max: 8 }
  ],
  gauge: [
    { k: 'title', label: '标题', t: 'text' },
    { k: 'var', label: '绑定变量', t: 'expr' },
    { k: 'min', label: '量程下限', t: 'num', min: -1e9, max: 1e9 },
    { k: 'max', label: '量程上限', t: 'num', min: -1e9, max: 1e9 },
    { k: 'unit', label: '单位', t: 'text' },
    { k: 'decimals', label: '小数位', t: 'num', min: 0, max: 6 },
    { k: 'ranges', label: '分区颜色', t: 'ranges' },
    { k: 'needleColor', label: '指针颜色', t: 'color' },
    { k: 'showValue', label: '下方显示数值', t: 'bool' }
  ],
  clock: [
    { k: 'format', label: '格式', t: 'select', opts: [
      { v: 'HH:mm:ss', t: 'HH:mm:ss' }, { v: 'yyyy-MM-dd HH:mm:ss', t: 'yyyy-MM-dd HH:mm:ss' },
      { v: 'HH:mm', t: 'HH:mm' }
    ] },
    { k: 'showDate', label: '显示日期', t: 'bool' },
    { k: 'tz', label: '时区', t: 'select', opts: [
      { v: 'Asia/Shanghai', t: 'Asia/Shanghai（北京时间）' }, { v: 'UTC', t: 'UTC' }
    ] }
  ],
  video: [
    { k: 'title', label: '标题', t: 'text' },
    { k: 'channel', label: '视频通道', t: 'select', optsFrom: 'channels',
      hint: '下拉选这一路；顺序按「能播的优先」，所以不是 NVR 通道号顺序' },
    { k: 'stream', label: '码流', t: 'select', opts: [{ v: 'main', t: '主码流' }, { v: 'sub', t: '辅码流' }] },
    { k: 'fit', label: '画面适配', t: 'select', opts: [{ v: 'contain', t: '等比完整（contain）' }, { v: 'cover', t: '等比裁切（cover）' }, { v: 'fill', t: '拉伸（fill）' }] }
  ],
  symbolLib: [
    { k: 'group', label: '分组', t: 'select', opts: [
      { v: '全部', t: '全部' }, { v: '泵类', t: '泵类' }, { v: '阀门', t: '阀门' },
      { v: '罐体', t: '罐体' }, { v: '输送', t: '输送' }, { v: '风机', t: '风机' }
    ] }
  ]
}

const form = computed(() => (props.item && FORM[props.item.control]) || [])

function reset() {
  // 深拷贝：对话框里改到一半点取消，画布上的对象不能跟着变
  draft.value = JSON.parse(JSON.stringify((props.item && props.item.props) || {}))
  // 对象变量拍平成 "S001.V300" 给输入框
  for (const f of form.value) {
    if (f.t === 'vars' && Array.isArray(draft.value[f.k])) {
      for (const v of draft.value[f.k]) {
        if (v && v.expr) v.expr = tagText(v.expr)
      }
    }
  }
  if (draft.value.xVar) draft.value.xVar = tagText(draft.value.xVar)
  for (const f of form.value) {
    if (f.t === 'vars' && !Array.isArray(draft.value[f.k])) draft.value[f.k] = []
    if (f.t === 'ranges' && !Array.isArray(draft.value[f.k])) draft.value[f.k] = []
    if (f.t === 'cols' && !Array.isArray(draft.value[f.k])) draft.value[f.k] = []
  }
}

function addVar(f) {
  if (!Array.isArray(draft.value[f.k])) draft.value[f.k] = []
  draft.value[f.k].push(f.color
    ? { expr: '', color: '#2ecc71', width: 2, visible: true }
    : (f.label ? { expr: '', label: '', decimals: 2 } : { expr: '', color: '#2ecc71' }))
}

function pickVar(k, i, field) {
  target.value = { k, i, field }
  pickerOpen.value = true
}

function onPick(ex) {
  const t = target.value
  if (!t) return
  // VarPicker 给的是 {site, point} 对象；输入框要字符串，拍平后再写
  const t2 = tagText(ex)
  if (t.i == null) draft.value[t.k] = t2
  else if (draft.value[t.k] && draft.value[t.k][t.i]) draft.value[t.k][t.i][t.field || 'expr'] = t2
  pickerOpen.value = false
}

function save() {
  // 变量列表里空表达式的行去掉（配了一半的残留）
  const out = JSON.parse(JSON.stringify(draft.value))
  for (const f of form.value) {
    if (f.t === 'vars' && Array.isArray(out[f.k])) {
      // 丢掉配了一半的空行；顺便把 "S001.V300" 还原成 {site,point}（4.3 规范）
      out[f.k] = out[f.k]
        .filter(v => tagText(v && v.expr))
        .map(v => ({ ...v, expr: toVar(v.expr) || v.expr }))
    }
  }
  if (out.xVar) out.xVar = toVar(out.xVar) || out.xVar
  emit('save', out)
  open.value = false
  ElMessage.success('已应用（记得保存画面）')
}
</script>

<style scoped>
.cd { font-size: 12px; color: #334155; }
.hd { display: flex; align-items: center; gap: 8px; padding-bottom: 8px; border-bottom: 1px solid #e2e8f0; margin-bottom: 8px; }
.nm { font-weight: 600; color: #0f172a; }
.tip { color: #64748b; font-size: 11px; }
.sp { flex: 1 1 auto; }
.sz { color: #94a3b8; font-size: 11px; }
.body { max-height: 62vh; overflow: auto; padding-right: 4px; }
.row { display: flex; align-items: center; gap: 10px; padding: 5px 0; border-bottom: 1px dashed #eef2f7; }
.row:last-child { border-bottom: none; }
.row.wide { align-items: flex-start; flex-direction: column; gap: 4px; }
.lb { width: 132px; flex: 0 0 132px; color: #475569; }
.row.wide .lb { width: auto; flex: none; padding-top: 4px; }
.hint { display: block; color: #94a3b8; font-size: 10px; font-style: normal; }
.cr { display: flex; align-items: center; gap: 6px; }
.cp { width: 30px; height: 22px; padding: 0; border: 1px solid #cbd5e1; background: none; cursor: pointer; }
.cp.sm { width: 24px; height: 20px; }
.hex { color: #64748b; font-family: monospace; font-size: 11px; }
.ex { display: flex; gap: 6px; width: 100%; }
.ex :deep(.el-input) { flex: 1 1 auto; }
.pb { font-size: 11px; padding: 2px 8px; border: 1px solid #cbd5e1; background: #f8fafc; border-radius: 3px;
  cursor: pointer; white-space: nowrap; color: #334155; }
.pb:hover { background: #eef4fb; border-color: #93c5fd; }
.vlist { width: 100%; display: flex; flex-direction: column; gap: 4px; }
.vrow { display: flex; align-items: center; gap: 5px; }
.vi { flex: 1 1 auto; }
.xb { width: 20px; height: 20px; line-height: 1; border: 1px solid #e2e8f0; background: #fff; border-radius: 3px;
  cursor: pointer; color: #94a3b8; padding: 0; }
.xb:hover { color: #ef4444; border-color: #fca5a5; }
.ab { align-self: flex-start; font-size: 11px; padding: 2px 8px; border: 1px dashed #cbd5e1; background: none;
  border-radius: 3px; cursor: pointer; color: #3b82f6; }
.dash { color: #94a3b8; }
.cols { display: flex; flex-wrap: wrap; gap: 4px 12px; }
.cb { display: inline-flex; align-items: center; gap: 3px; color: #475569; }
.ft-b { padding: 5px 16px; border-radius: 4px; border: 1px solid #2563eb; background: #2563eb; color: #fff;
  font-size: 12px; cursor: pointer; margin-left: 8px; }
.ft-b.ghost { background: #fff; color: #475569; border-color: #cbd5e1; }
</style>
