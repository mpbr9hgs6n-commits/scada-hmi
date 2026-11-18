<template>
  <div class="ep">
    <!-- 左树：五组事件（照官方 4.11 的事件清单分组） -->
    <div class="ep-tree">
      <div v-for="g in groups" :key="g.key" class="g" :class="{ on: cur === g.key }"
           @click="pick(g.key)">
        <span class="gm">{{ g.label }}</span>
        <b v-if="countOf(g.key)" class="n">{{ countOf(g.key) }}</b>
      </div>
      <div class="legend">
        <span>◈</span> 双击「动作」列配置
      </div>
    </div>

    <!-- 右表：事件名 ｜ 动作 ｜ 参数 ｜ 测试 -->
    <div class="ep-tbl">
      <div class="tr hd">
        <span>事件名</span><span>动作</span><span>参数</span><span></span>
      </div>
      <div v-for="e in rows" :key="e.key" class="tr" :class="{ has: !!actOf(e.key) }">
        <span class="nm" :title="e.d">
          {{ e.cn || e.key }}<i v-if="e.ours" class="ours" title="官方事件表里没有，本平台补的">补</i>
          <i v-if="isLocked(e.key)" class="lk" title="瞬时动作必带，不能删">锁</i>
        </span>
        <span class="ac" :title="actOf(e.key) ? human(actOf(e.key)) : '（无动作，双击配置）'"
              @dblclick="edit(e.key)">
          <b v-if="actOf(e.key)">●</b>{{ actOf(e.key) ? short(actOf(e.key)) : '—' }}
        </span>
        <span class="pm">
          <select v-if="e.key === 'gesture'" class="sel mini" :value="evOf(e.key).gesture || ''"
                  @change="setParam(e.key, 'gesture', $event.target.value)">
            <option value="">任意</option>
            <option v-for="x in GESTURES" :key="x.v" :value="x.v">{{ x.t }}</option>
          </select>
          <span v-else class="dash">—</span>
        </span>
        <button class="mini tst" title="不切运行态直接触发一次，看效果"
                :disabled="!actOf(e.key)" @click="test(e.key)">测试</button>
      </div>
      <div v-if="!rows.length" class="empty">这组没有事件</div>
    </div>

    <div class="hint">
      一期只做<b>直接连接</b>（官方定位：画面内最快）；VBS / C 动作二期支持。
      瞬时动作会给<b>按下 / 松开 / 移出</b>各绑一条，「移出」不允许删——少了它，按住拖出按钮再松手，线圈会永远停在 1。
    </div>

    <!-- 动作配置：双击「动作」列弹出 -->
    <el-dialog v-model="open" title="动作配置" width="600px" append-to-body :close-on-click-modal="false">
      <div class="ae" v-if="editing">
        <div class="row">
          <label>事件</label>
          <span class="mono ev">{{ (EVENTS[editing] && EVENTS[editing].cn) || editing }}</span>
          <span class="sub">{{ EVENTS[editing] ? EVENTS[editing].d : '属性变化事件' }}</span>
        </div>

        <div class="row">
          <label>动作类型</label>
          <select class="sel atype" v-model="form.type" @change="onType">
            <option value="direct">直接连接（Direct Connection）</option>
            <option value="vbs">VBS 动作（二期支持）</option>
            <option value="c">C 动作（二期支持）</option>
          </select>
        </div>
        <div v-if="form.type !== 'direct'" class="warn">
          当前版本请用直接连接：脚本动作二期支持（脚本一旦跑飞会把整个画面卡死，需要先做沙箱）。
        </div>

        <template v-if="form.type === 'direct'">
          <div class="row">
            <label>预设</label>
            <select class="sel preset" v-model="form.preset" @change="onPreset">
              <option v-for="p in PRESETS" :key="p.v" :value="p.v">{{ p.t }}</option>
            </select>
          </div>

          <div class="sec">Source（数据源）</div>
          <div class="row">
            <label>类型</label>
            <select class="sel s-kind" v-model="form.src.kind">
              <option value="constant">常量</option>
              <option value="attr">对象属性</option>
              <option value="tag">变量</option>
            </select>
          </div>
          <div class="row" v-if="form.src.kind === 'constant'">
            <label>值</label>
            <input class="txt src-val" v-model="form.src.value" placeholder="1" />
            <span class="sub">写点位用 0/1；打开画面填画面 id</span>
          </div>
          <div class="row" v-if="form.src.kind === 'attr'">
            <label>对象</label>
            <select class="sel" v-model="form.src.objectName">
              <option v-for="o in objects" :key="o.name" :value="o.name">{{ o.name }}</option>
            </select>
            <select class="sel" v-model="form.src.attr">
              <option v-for="a in attrOf(form.src.objectName)" :key="a.key" :value="a.key">{{ a.label }}</option>
            </select>
          </div>
          <div class="row" v-if="form.src.kind === 'tag'">
            <label>变量</label>
            <input class="txt mono src-expr" v-model="form.src.expr" placeholder="S001.PUMP1_RUN" />
            <button class="mini" @click="pickTag('src')">选择</button>
          </div>

          <div class="sec">Objective（目标）</div>
          <div class="row">
            <label>类型</label>
            <select class="sel d-kind" v-model="form.dst.kind" @change="onDstKind">
              <option value="tag">变量</option>
              <option value="attr">对象属性</option>
              <option value="window">当前画面</option>
            </select>
          </div>
          <div class="row" v-if="form.dst.kind === 'tag'">
            <label>变量</label>
            <input class="txt mono dst-expr" v-model="form.dst.expr" placeholder="S001.PUMP1_RUN" />
            <button class="mini" @click="pickTag('dst')">选择</button>
          </div>
          <div class="row" v-if="form.dst.kind === 'attr'">
            <label>对象</label>
            <select class="sel" v-model="form.dst.objectName">
              <option v-for="o in objects" :key="o.name" :value="o.name">{{ o.name }}</option>
            </select>
            <select class="sel" v-model="form.dst.attr">
              <option v-for="a in attrOf(form.dst.objectName)" :key="a.key" :value="a.key">{{ a.label }}</option>
            </select>
          </div>
          <div class="row" v-if="form.dst.kind === 'window'">
            <label>画面属性</label>
            <select class="sel" v-model="form.dst.attr">
              <option value="openPicture">打开画面（值=画面 id）</option>
              <option value="closePicture">关闭当前画面</option>
              <option value="bg">画面背景色</option>
            </select>
          </div>

          <div class="row">
            <label></label>
            <label class="cb"><input type="checkbox" v-model="form.msgOn" /> 输出操作员消息（写审计日志）</label>
          </div>
          <div class="row" v-if="form.msgOn">
            <label>消息</label>
            <input class="txt msg" v-model="form.msg" placeholder="如：1号泵启动" />
          </div>

          <div class="pv">
            <span class="lb">这条动作</span>
            <span class="mono">{{ human(form) }}</span>
          </div>
        </template>
      </div>

      <template #footer>
        <button class="mini del" v-if="!isLocked(editing)" @click="removeAction">删除该动作</button>
        <button class="mini" @click="open = false">取消</button>
        <button class="mini ok" @click="save">确定</button>
      </template>
    </el-dialog>

    <VarPicker v-model="pickerOpen" :sites="sites" :site="curSite" :writable="true"
               @pick="onPickTag" @insert-site="onPickTag" />
  </div>
</template>

<script setup>
// 事件页签（P5）
// 官方依据：4.11 Events 页签（左侧事件组树 + 右侧事件清单表）、4.8.4.11 直接连接（源三选一 → 目标三选一）
import { ref, reactive, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  EVENTS, EVENT_GROUPS, GESTURES, PRESETS,
  blankAction, actionFromPreset, humanAction, eventLabel,
  testEvent
} from './events'
import { dynAttrsOf } from './dyn'
import VarPicker from './VarPicker.vue'
// 4.3 变量是 {site,point} 对象，但 <input v-model> 只能显示字符串。
// 载入时用 tagText 拍平，保存时用 toVar 还原，避免输入框显示 [object Object]。
import { tagText, toVar } from './varbind'

const props = defineProps({
  item: { type: Object, default: null },
  all: { type: Array, default: () => [] },
  sites: { type: Array, default: () => [] },
  curSite: { type: String, default: '' },
  evCtx: { type: Object, default: null }
})
const emit = defineEmits(['commit'])

const cur = ref('mouse')
const editing = ref('')
const open = ref(false)
const pickerOpen = ref(false)
const pickFor = ref('dst')
const form = reactive(blankAction())
const msgOn = ref(false)

const groups = EVENT_GROUPS
const events = ref({})

const objects = computed(() => (props.all || []).filter(o => o && o.name))

function load() {
  events.value = props.item && props.item.events ? JSON.parse(JSON.stringify(props.item.events)) : {}
}
watch(() => props.item, load, { immediate: true })

function evOf(k) { return events.value[k] || {} }
function actOf(k) { return evOf(k).action || null }
function isLocked(k) { return evOf(k).locked === 'momentary' }

const dynAttrs = computed(() => (props.item ? dynAttrsOf(props.item.type) : []))

function rowsOf(groupKey) {
  if (groupKey === 'attr') {
    return dynAttrs.value.map(a => ({ key: a.key + '.change', g: 'attr', d: '属性「' + a.label + '」变化时' }))
  }
  return Object.entries(EVENTS).filter(([, v]) => v.g === groupKey).map(([k, v]) => ({ key: k, ...v }))
}
const rows = computed(() => rowsOf(cur.value))
function countOf(g) { return rowsOf(g).filter(r => actOf(r.key)).length }
function pick(g) { cur.value = g }

function short(a) {
  const h = humanAction(a)
  return h.length > 26 ? h.slice(0, 25) + '…' : h
}
const human = humanAction

function attrOf(name) {
  const o = (props.all || []).find(x => x && x.name === name)
  return o ? dynAttrsOf(o.type) : []
}

// —— 提交（走 PropPanel 的 commit，进撤销栈）——
function commitEvents(next) {
  const from = props.item && props.item.events ? JSON.parse(JSON.stringify(props.item.events)) : undefined
  const to = Object.keys(next).length ? next : undefined
  events.value = next
  emit('commit', { from, to })
}

function setParam(key, field, val) {
  const next = JSON.parse(JSON.stringify(events.value))
  next[key] = Object.assign({}, next[key], { [field]: val })
  commitEvents(next)
}

function edit(key) {
  editing.value = key
  const a = actOf(key)
  Object.assign(form, blankAction())
  if (a) Object.assign(form, JSON.parse(JSON.stringify(a)))
  // 把对象变量拍平成 "S001.V300" 给输入框；不拍平的话 v-model 会显示 [object Object]
  if (form.src && form.src.expr) form.src.expr = tagText(form.src.expr)
  if (form.dst && form.dst.expr) form.dst.expr = tagText(form.dst.expr)
  msgOn.value = !!(a && a.msg)
  open.value = true
}

function onType() {
  if (form.type !== 'direct') return
}
function onPreset() {
  const prev = form.dst && form.dst.expr ? { dst: form.dst } : null
  const next = actionFromPreset(form.preset, prev)
  Object.assign(form, next)
  msgOn.value = !!form.msg
}
function onDstKind() {
  if (form.dst.kind === 'window' && !form.dst.attr) form.dst.attr = 'openPicture'
  if (form.dst.kind === 'tag' && !form.dst.expr) form.dst.expr = ''
}

function pickTag(which) { pickFor.value = which; pickerOpen.value = true }
function onPickTag(txt) {
  // VarPicker emit 的是 {site, point} 对象；输入框要字符串，这里拍平
  const t = tagText(txt)
  if (pickFor.value === 'src') form.src.expr = t
  else form.dst.expr = t
}

function save() {
  if (form.type === 'direct') {
    if (form.dst.kind === 'tag' && !String(form.dst.expr || '').trim()) {
      ElMessage.warning('目标变量没填：动作写了也没地方去')
      return
    }
    if (form.dst.kind === 'window' && form.dst.attr === 'openPicture' && !String(form.src.value || '').trim()) {
      ElMessage.warning('打开画面要在 Source 的常量里填画面 id')
      return
    }
  }
  const act = JSON.parse(JSON.stringify(form))
  // 输入框里是 "S001.V300"，落库统一还原成 {site, point}（4.3 规范）
  if (act.src && act.src.expr) act.src.expr = toVar(act.src.expr)
  if (act.dst && act.dst.expr) act.dst.expr = toVar(act.dst.expr)
  act.msg = msgOn.value ? (form.msg || '') : ''
  const next = JSON.parse(JSON.stringify(events.value))

  // 瞬时：一次生成三条（press 写 A、release 写 B、leave 写 B），leave 锁定
  if (act.type === 'direct' && act.preset === 'momentary') {
    const on = { kind: 'constant', value: act.src && act.src.value !== undefined ? act.src.value : 1 }
    const off = { kind: 'constant', value: act.off !== undefined ? act.off : 0 }
    const mk = (src) => Object.assign(JSON.parse(JSON.stringify(act)), { src })
    next['mouse.press.left'] = { action: mk(on), locked: 'momentary' }
    next['mouse.release.left'] = { action: mk(off), locked: 'momentary' }
    next['mouse.leave'] = { action: mk(off), locked: 'momentary' }
    ElMessage.success('瞬时动作已绑三条：按下写 ' + on.value + '、松开写 ' + off.value + '、移出写 ' + off.value)
  } else if (editing.value === 'mouse.leave' && isLocked('mouse.leave')) {
    ElMessage.warning('瞬时动作的 mouse.leave 不能改（少了它线圈会停在 1）')
    return
  } else {
    next[editing.value] = Object.assign({}, next[editing.value], { action: act })
  }
  commitEvents(next)
  open.value = false
}

function removeAction() {
  if (isLocked(editing.value)) {
    ElMessage.warning('瞬时动作的 mouse.leave 不能删（少了它线圈会停在 1）')
    return
  }
  const next = JSON.parse(JSON.stringify(events.value))
  delete next[editing.value]
  commitEvents(next)
  open.value = false
}

// —— 测试：不切运行态直接触发一次 ——
function test(key) {
  if (!props.evCtx) { ElMessage.warning('画布还没准备好'); return }
  const ok = testEvent(props.item, key, props.evCtx)
  if (ok) ElMessage.success('已触发 ' + key)
  else ElMessage.warning('这条事件还没配动作')
}
</script>

<style scoped>
.ep { font-size: 11px; color: #9fc3e8; display: flex; flex-wrap: wrap; }
.ep-tree { flex: 0 0 78px; border-right: 1px solid #12233a; padding: 2px 0; }
.ep-tree .g { display: flex; align-items: center; gap: 3px; padding: 4px 6px; cursor: pointer; color: #8fb3d4; }
.ep-tree .g:hover { background: #0e1f33; }
.ep-tree .g.on { background: #12233a; color: #cdeaff; border-left: 2px solid #1ec8ff; }
.ep-tree .gm { flex: 1; font-size: 10px; line-height: 1.2; }
.ep-tree .n { font-size: 9px; color: #22c55e; }
.legend { padding: 6px; color: #4b6a8a; font-size: 9px; line-height: 1.5; }
.legend span { color: #1ec8ff; }

.ep-tbl { flex: 1; min-width: 0; }
.ep-tbl .tr { display: flex; align-items: center; gap: 3px; padding: 2px 4px; border-bottom: 1px solid #0d1b2b; }
.ep-tbl .tr.hd { color: #5b82a8; font-size: 9px; border-bottom: 1px solid #12233a; }
.ep-tbl .tr.has { background: rgba(30, 200, 255, .04); }
.ep-tbl .tr > span:nth-child(1) { flex: 1.25; min-width: 0; }
.ep-tbl .tr > span:nth-child(2) { flex: 1.05; min-width: 0; }
.ep-tbl .tr > span:nth-child(3) { flex: 0 0 62px; }
.ep-tbl .tr.hd > span:nth-child(4) { flex: 0 0 32px; }
.nm { font-family: Consolas, monospace; font-size: 9.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nm .ours, .nm .lk { font-style: normal; font-size: 8px; padding: 0 2px; border-radius: 2px; margin-left: 2px; }
.nm .ours { color: #0b1622; background: #f59e0b; }
.nm .lk { color: #0b1622; background: #22c55e; }
.ac { color: #8fb3d4; font-size: 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: pointer; }
.ac b { color: #22c55e; margin-right: 2px; }
.pm .sel { width: 100%; font-size: 10px; }
.dash { color: #365a80; }
.tst { flex: 0 0 32px; padding: 0; font-size: 9px; }
.empty { padding: 12px; color: #3b5c82; }
.hint { flex: 0 0 100%; padding: 6px 8px; color: #5b82a8; font-size: 10px; line-height: 1.6; border-top: 1px solid #12233a; }
.hint b { color: #f59e0b; }

/* —— 动作配置面板 —— */
.ae { font-size: 12px; color: #cfe3f5; }
.ae .row { display: flex; align-items: center; gap: 6px; padding: 3px 0; }
.ae .row > label:first-child { flex: 0 0 70px; color: #8fb3d4; font-size: 11px; }
.ae .sel, .ae .txt { background: #0a1626; border: 1px solid #1e3a5f; color: #e2e8f0;
  border-radius: 3px; padding: 3px 6px; font-size: 12px; min-width: 0; }
.ae .sel { flex: 1; }
.ae .txt { flex: 1; }
.ae .mono { font-family: Consolas, monospace; }
.ae .ev { color: #1ec8ff; }
.ae .sub { color: #5b82a8; font-size: 10px; }
.ae .sec { margin: 8px 0 2px; padding: 3px 6px; background: #0c1a2b; color: #7ba3c9;
  font-size: 11px; border-left: 2px solid #1ec8ff; }
.ae .cb { color: #8fb3d4; font-size: 11px; display: inline-flex; align-items: center; gap: 4px; }
.ae .cb input { accent-color: #1ec8ff; }
.ae .warn { margin: 4px 0; padding: 4px 8px; color: #f59e0b; background: rgba(245,158,11,.08);
  border: 1px solid rgba(245,158,11,.35); border-radius: 3px; font-size: 11px; line-height: 1.6; }
.ae .pv { margin-top: 8px; padding: 5px 8px; background: #08111c; border: 1px solid #1e3a5f; border-radius: 3px; }
.ae .pv .lb { color: #7ba3c9; margin-right: 8px; }
.ae .pv .mono { color: #22c55e; }
.mini { background: #12233a; border: 1px solid #1e3a5f; color: #9fc3e8; border-radius: 3px;
  padding: 2px 8px; font-size: 11px; cursor: pointer; }
.mini:hover:not(:disabled) { border-color: #1ec8ff; color: #cdeaff; }
.mini:disabled { opacity: .4; cursor: not-allowed; }
.mini.ok { border-color: #22c55e; color: #22c55e; }
.mini.del { float: left; border-color: #ef4444; color: #f87171; }
</style>
