<template>
  <div class="dp">
    <!-- 目标属性 -->
    <div class="grp">
      <div class="gh">动态化属性</div>
      <div class="row">
        <label class="lb">属性</label>
        <select class="sel attr-sel" v-model="attr" @change="onAttr">
          <option v-for="a in attrs" :key="a.key" :value="a.key">
            {{ a.label }}{{ boundOf(a.key) ? ' · 已绑定' : '' }}
          </option>
        </select>
      </div>
      <div class="row">
        <label class="lb">类型</label>
        <select class="sel mode-sel" v-model="mode" @change="onMode">
          <option v-for="m in DYN_MODES" :key="m.v" :value="m.v">{{ m.t }}</option>
        </select>
      </div>
      <div v-if="!mode" class="hint">该属性没有动态化：运行时恒为属性面板里设的值。</div>
    </div>

    <!-- ① 直接变量连接（提示词 10 4.3：只认 {site, point}，不给手写表达式） -->
    <div v-if="mode === 'tag'" class="grp">
      <div class="gh">直接变量连接</div>
      <div class="row">
        <label class="lb">变量</label>
        <span class="bound mono" :class="{ unbound: !varTag }">{{ varTag || '未绑定' }}</span>
        <button class="mini btn-picker" @click="openVarPicker">关联变量</button>
        <button v-if="varTag" class="mini btn-unbind" @click="unbindVar">解除</button>
      </div>
      <div v-if="staleTag" class="tip bad">变量已失效：{{ staleTag }}（点位不存在或已停用，保存会被拒绝）</div>
      <div v-else-if="!varTag" class="hint">点「关联变量」→ 先选站点，再选点位；两个下拉，不写表达式。</div>

      <!-- 颜色类属性：变量值 → 颜色档位（最多 10 档） -->
      <template v-if="attrKind === 'color'">
        <div class="sub">颜色档位（按变量值取色，最多 10 档）</div>
        <RangeTable :rows="f.ranges" kind="color" @change="commitForm" />
        <div class="row">
          <label class="lb">其他</label>
          <input class="txt other-in" v-model="f.other"
                 :placeholder="'没匹配到档位时用的颜色，如 #64748b'" @blur="commitForm">
          <span v-if="f.other" class="sw" :style="{ background: f.other }"></span>
        </div>
        <div class="hint" v-if="!f.ranges.length">
          还没配档位：变量的值会直接当作颜色用（布尔量 0/1 会走「其他」默认色）。
          要按值取色就选个档位数，再填每档的区间和颜色。
        </div>
      </template>
      <div v-else class="hint" v-if="attrKind !== 'num' && attrKind !== 'pct'">
        该属性不做值域映射，变量的值直接赋给属性。
      </div>
    </div>

    <!-- ② 间接变量连接 -->
    <div v-if="mode === 'indirect'" class="grp">
      <div class="gh">间接变量连接（变量值 = 变量名）</div>
      <div class="row">
        <label class="lb">名称表达式</label>
        <input class="txt mono nameexpr-in" v-model="f.nameExpr" :class="{ err: invalid }"
               placeholder="@CurrentSite + '.LEVEL'" @blur="commitForm">
        <button class="mini btn-picker" @click="openPicker('nameExpr')">选择</button>
      </div>
      <div class="row">
        <label class="lb"></label>
        <button class="mini wide btn-preview200" @click="preview200">200 站点求值预览</button>
      </div>
      <div class="hint">@CurrentSite 优先级：URL 参数 &gt; 画面默认站点 &gt; 全局当前站点。切换站点时整张画面重新求值，不刷新页面。</div>
      <div v-if="checkMsg" class="tip" :class="{ ok: checkOk }">{{ checkMsg }}</div>
    </div>

    <!-- ⑥ 文本列表 / 图形列表（P8，官方 4.7）-->
    <div v-if="mode === 'textlist' || mode === 'graphlist'" class="grp">
      <div class="gh">{{ mode === 'textlist' ? '文本列表（数值 → 文字）' : '图形列表（数值 → 图片）' }}</div>
      <div class="row">
        <label class="lb">列表</label>
        <select class="sel list-sel" v-model="f.listId" @change="commitForm">
          <option value="">（请选择）</option>
          <option v-for="l in listOptions" :key="l.name" :value="l.name">
            {{ l.name }}（{{ l.kind === 'text' ? '文本' : '图形' }}）
          </option>
        </select>
        <button class="mini" @click="reloadLists">刷新</button>
      </div>
      <div class="row">
        <label class="lb">表达式</label>
        <input class="txt mono expr-in" v-model="f.expr" @blur="commitForm" placeholder="S001.PUMP1_RUN">
        <button class="mini btn-picker" @click="openPicker('expr')">选择</button>
      </div>
      <div class="hint">值不在列表里时对象标黄、保留上一次显示；列表在侧边栏「列表管理」里维护。</div>
    </div>

    <!-- ③ 动态对话框 -->
    <div v-if="mode === 'dialog'" class="grp">
      <div class="gh">动态对话框</div>

      <div class="row">
        <label class="lb">事件名称</label>
        <select class="sel evt-sel" v-model="f.triggerType" @change="commitForm">
          <option v-for="e in EVENT_NAMES" :key="e.v" :value="e.v">{{ e.t }}</option>
        </select>
      </div>
      <div v-if="f.triggerType === 'tag'" class="row">
        <label class="lb">触发变量</label>
        <input class="txt mono" v-model="f.triggerTag" placeholder="S001.LEVEL" @blur="commitForm">
        <button class="mini" @click="openPicker('triggerTag')">选择</button>
      </div>

      <div class="row">
        <label class="lb">表达式</label>
        <input class="txt mono formula-in" v-model="f.formula" :class="{ err: invalid }"
               placeholder="S001.LEVEL * 100" @blur="commitForm">
        <button class="mini btn-check" @click="check">检查</button>
      </div>
      <div v-if="checkMsg" class="tip" :class="{ ok: checkOk }">{{ checkMsg }}</div>

      <div class="row">
        <label class="lb">数据类型</label>
        <select class="sel dtype-sel" v-model="f.dataType" @change="onDataType">
          <option v-for="d in DATA_TYPES" :key="d.v" :value="d.v">{{ d.t }}</option>
        </select>
      </div>
      <div v-if="f.dataType === 'Bit'" class="row">
        <label class="lb">取第几位</label>
        <input class="num" type="number" min="0" max="15" v-model.number="f.bit" @change="commitForm">
        <span class="u">bit</span>
      </div>

      <div class="row chk">
        <label class="cb"><input type="checkbox" v-model="f.evalTagStatus" @change="commitForm"> 评估变量状态</label>
        <label class="cb"><input type="checkbox" v-model="f.evalQuality" @change="commitForm"> 评估质量码</label>
      </div>

      <template v-if="f.dataType !== 'Direct'">
        <div class="sub">值域（to 留空 = 以上全部）</div>
        <RangeTable :rows="f.ranges" :kind="attrKind" @change="commitForm" />
        <div class="row">
          <label class="lb">其他</label>
          <input class="txt other-in" v-model="f.other" :class="{ err: !f.other }"
                 :placeholder="otherHint" @blur="commitForm">
          <span v-if="attrKind === 'color' && f.other" class="sw" :style="{ background: f.other }"></span>
        </div>
        <div class="hint warn" v-if="!f.other">官方要求必须给「其他」默认值：没匹配到值时属性就取它，不能省（省了会表现为超量程时数字消失/颜色变黑）。</div>
      </template>
      <div v-else class="hint">Direct：不做值域映射，变量的值直接赋给属性。</div>
    </div>

    <!-- ④ 动画 -->
    <div v-if="mode === 'animation'" class="grp">
      <div class="gh">动画（一个变量驱动多属性）</div>
      <div class="row">
        <label class="lb">触发变量</label>
        <input class="txt mono" v-model="f.expr" placeholder="S001.LEVEL" @blur="commitForm">
        <button class="mini" @click="openPicker('expr')">选择</button>
      </div>
      <div class="row">
        <label class="lb">数据类型</label>
        <select class="sel" v-model="f.dataType" @change="commitForm">
          <option v-for="d in DATA_TYPES" :key="d.v" :value="d.v">{{ d.t }}</option>
        </select>
      </div>

      <div v-for="(t, i) in f.tracks" :key="i" class="track">
        <div class="row">
          <label class="lb">属性 {{ i + 1 }}</label>
          <select class="sel" v-model="t.attr" @change="commitForm">
            <option v-for="a in attrs" :key="a.key" :value="a.key">{{ a.label }}</option>
          </select>
          <button class="mini" title="删除这条" @click="delTrack(i)">−</button>
        </div>
        <RangeTable :rows="t.ranges" :kind="kindOf(t.attr)" @change="commitForm" />
      </div>
      <div class="row">
        <label class="lb"></label>
        <button class="mini wide" @click="addTrack">+ 增加一条属性</button>
      </div>
      <div class="row">
        <label class="lb">其他</label>
        <input class="txt" v-model="f.other" :placeholder="otherHint" @blur="commitForm">
      </div>
      <div class="hint">官方限制：动画只能配在单个对象上（多选时禁用）。高度这类属性可以用 [起, 止] 做线性映射，如 [&quot;0%&quot;,&quot;100%&quot;]。</div>
    </div>

    <!-- 结果与工具 -->
    <div class="grp">
      <div class="gh">结果</div>
      <div class="res">
        <span class="rl">当前求值</span>
        <span class="rv" :class="{ bad: resBad }">{{ resText }}</span>
      </div>
      <div class="row">
        <label class="lb"></label>
        <button class="mini btn-copy" @click="copyDyn">复制动态化</button>
        <button class="mini btn-paste" :disabled="!clip" @click="pasteDyn">粘贴动态化</button>
        <button class="mini" :disabled="!Object.keys(dyn).length" @click="clearAll">清除全部</button>
      </div>
    </div>

    <VarPicker v-model="pickerOpen" :sites="sites" :site="curSite"
               :writable="false" @pick="onPick" @insert-site="onInsertSite" />

    <el-dialog v-model="pvOpen" title="200 站点求值预览" width="720px" append-to-body>
      <div class="pv">
        <div class="pv-h">
          <span class="mono">{{ f.nameExpr }}</span>
          <span class="stat" v-if="pvList.length">
            <b class="good">{{ pvList.filter(x => x.found).length }}</b> 个站点有点位 ｜
            <b class="bad">{{ pvList.filter(x => !x.found).length }}</b> 个站点缺点位
          </span>
        </div>
        <div class="pv-b">
          <div v-for="x in pvList" :key="x.site" class="pv-r" :class="{ bad: !x.found }">
            <span class="s">{{ x.site }}</span>
            <span class="t mono">{{ x.tag }}</span>
            <span class="v">
              <template v-if="x.found">
                <span v-if="x.q === 1" class="qb">⚠ 坏值</span>
                {{ x.value === null ? '—' : x.value }} <em>{{ x.unit || '' }}</em>
              </template>
              <template v-else>❌ {{ x.msg || '点位不存在' }}</template>
            </span>
          </div>
          <div v-if="!pvList.length" class="pv-empty">{{ pvLoading ? '求值中…' : '没有站点' }}</div>
        </div>
      </div>
    </el-dialog>
  
    <!-- ⑤ 条件规则表（2026-11-14 新增）：当前值 = x 则执行动作，可挂多条 -->
    <div class="grp rk-grp">
      <div class="gh">条件规则（当前值 = x → 执行动作）</div>
      <!-- 用户 2026-11-14：规则的变量统一取上方「直接变量连接」里选的那个，
           不再每行各填一份点位 -->
      <div class="rk-var" :class="{ flash: addRuleBlocked }">
        当前变量：
        <b class="mono" v-if="ruleVarText">{{ ruleVarText }}</b>
        <i class="rk-warn" v-else>请先在上方「直接变量连接」里选择变量</i>
      </div>
      <div class="rk-hd">
        <span class="rk-c2">条件</span><span class="rk-c3">值</span>
        <span class="rk-c4">动作</span><span class="rk-c5">动作值</span><span class="rk-c6"></span>
      </div>
      <div v-for="(r, i) in ruleList" :key="i" class="rk-row"
           :class="{ incomplete: ruleBad(r) }">
        <select class="sel rk-c2" v-model="r.op" @change="onRuleEdit">
          <option value="eq">等于 =</option><option value="ne">不等于 ≠</option>
          <option value="gt">大于 &gt;</option><option value="ge">大于等于 ≥</option>
          <option value="lt">小于 &lt;</option><option value="le">小于等于 ≤</option>
        </select>
        <input class="rk-in rk-c3" v-model="r.value" @blur="onRuleEdit" placeholder="74" title="比较值" />
        <select class="sel rk-c4" v-model="r.action" @change="onRuleAction(r)">
          <option value="fillColor">填充色</option><option value="strokeColor">边框色</option>
          <option value="fontColor">文字颜色</option><option value="text">输出文字</option>
          <option value="visible">显示/隐藏</option><option value="blink">闪烁</option>
        </select>
        <input v-if="r.action === 'visible'" class="rk-in rk-c5" v-model="r.actionValue"
               @blur="onRuleEdit" placeholder="1=显示 0=隐藏" title="1 显示 / 0 隐藏" />
        <input v-else-if="r.action === 'blink'" class="rk-in rk-c5" v-model="r.actionValue"
               @blur="onRuleEdit" placeholder="1=闪 0=不闪" title="1 闪烁 / 0 不闪" />
        <input v-else-if="r.action === 'fillColor' || r.action === 'strokeColor' || r.action === 'fontColor'"
               class="rk-color rk-c5" type="color" v-model="r.actionValue" @change="onRuleEdit" title="选颜色" />
        <input v-else class="rk-in rk-c5" v-model="r.actionValue" @blur="onRuleEdit" placeholder="要输出的文字" />
        <button class="rk-del rk-c6" title="删除这条规则" @click="delRule(i)">×</button>
      </div>
      <div v-if="!ruleList.length" class="hint">还没有规则。规则和上面的「动态化属性」互不影响，可同时使用。</div>
      <div v-else-if="ruleList.some(r => ruleBad(r))" class="rk-err">
        ⚠ {{ ruleBadSummary }}
      </div>
      <button class="rk-add" @click="addRule">+ 添加规则</button>
    </div>
</div>
</template>

<script setup>
// 动态化页签（P4）
// 字段顺序严格照官方 4.8.4.4：Event Name → Expression → Result → Data type →
// Evaluate tag status / Evaluate quality → 值域表 → Other
import { ref, reactive, computed, watch, onMounted, onUnmounted, defineComponent, h } from 'vue'
import { ElMessage } from 'element-plus'
import {
  DYN_MODES, DATA_TYPES, EVENT_NAMES, dynAttrsOf, dynAttrLabel, normDyn, resolveOne
} from './dyn'
import { validate, evaluate } from './expr'
import { resolveTags } from './runtime'
import { tagOfVar } from './varbind'
import VarPicker from './VarPicker.vue'
import { tagText, toVar } from './varbind'

const props = defineProps({
  item: { type: Object, default: null },
  sites: { type: Array, default: () => [] },
  curSite: { type: String, default: '' },
  rt: { type: Object, default: null },
  // 编辑器算出的失效变量标签（S001.LEVEL），用于红色提示
  stale: { type: Array, default: () => [] }
})
const emit = defineEmits(['commit', 'setvar', 'rules'])

// 4.3：变量只认 {site, point} 对象；这里显示的永远是从 item.var 推出来的 tag
const varTag = computed(() => tagOfVar(props.item && props.item.var))
const staleTag = computed(() => (varTag.value && (props.stale || []).includes(varTag.value))
  ? varTag.value : '')
function openVarPicker() { pickFor.value = 'var'; pickerOpen.value = true }
function unbindVar() { emit('setvar', null) }

// P8 值列表：文本列表只列 kind=text、图形列表只列 kind=graph（选错了运行时会报「不是文本列表」）
const listVer = ref(0)
const listOptions = computed(() => {
  void listVer.value                       // rt.lists 不是响应式的，靠这个版本号触发重算
  const m = props.rt && props.rt.lists
  if (!m || !m.size) return []
  const want = mode.value === 'graphlist' ? 'graph' : 'text'
  return [...m.values()].filter(x => x.kind === want)
})

function reloadLists() {
  if (props.rt && props.rt.loadDefs) {
    props.rt.loadDefs(true).then(() => { listVer.value++ })
  } else {
    listVer.value++
  }
}
onMounted(() => { if (props.rt && props.rt.loadDefs && !props.rt.lists.size) reloadLists() })

// 值域表：dialog 与 animation 共用（输入后 @change 提交）
const RangeTable = defineComponent({
  props: { rows: { type: Array, default: () => [] }, kind: { type: String, default: 'num' } },
  emits: ['change'],
  setup(p, { emit }) {
    // 最多 10 档（用户 2026-11-12 定）。三档颜色映射（填充/边框/文字）共用这套表。
    const MAX_TIERS = 10
    const blankRow = () => ({
      from: 0, to: null,
      value: p.kind === 'color' ? '#22c55e' : '',
      blink: 0
    })
    // 先选档数再填：多则补空行、少则裁尾部，已填的内容原样保留
    const setCount = (n) => {
      const want = Math.max(1, Math.min(MAX_TIERS, Number(n) || 1))
      while (p.rows.length < want) p.rows.push(blankRow())
      while (p.rows.length > want) p.rows.pop()
      emit('change')
    }
    const add = () => {
      if (p.rows.length >= MAX_TIERS) return
      p.rows.push(blankRow())
      emit('change')
    }
    const del = (i) => { p.rows.splice(i, 1); emit('change') }
    // 提交前整理：按「数值」升序排，to 自动取下一档的数值，最后一档 = 以上全部。
    // 这样面板上只要填一个数值，区间由系统推导，mapRange 那边一行都不用动。
    const normalize = () => {
      const rows = p.rows.filter(r => r.from !== '' && r.from !== null && r.from !== undefined)
      rows.sort((a, b) => Number(a.from) - Number(b.from))
      rows.forEach((r, i) => {
        r.to = (i < rows.length - 1) ? Number(rows[i + 1].from) : null
      })
      emit('change')
    }

    return () => h('div', { class: 'rt' }, [
      // 档位数选择器（方案 B：先定几档，自动生成对应行数）
      h('div', { class: 'rt-cnt' }, [
        h('span', { class: 'lb' }, '档位数'),
        h('select', {
          class: 'sel rt-cnt-sel',
          value: p.rows.length ? String(p.rows.length) : '',
          onChange: (e) => setCount(e.target.value)
        }, [
          h('option', { value: '' }, '请选择'),
          ...Array.from({ length: MAX_TIERS }, (_, i) => i + 1).map((n) =>
            h('option', { value: String(n) }, n + ' 档'))
        ]),
        h('span', { class: 'rt-cnt-hint' },
          p.rows.length ? ('已配 ' + p.rows.length + ' 档 / 最多 ' + MAX_TIERS + ' 档')
                        : ('最多 ' + MAX_TIERS + ' 档，先选档数再填'))
      ]),
      h('div', { class: 'rt-h' }, [
        h('span', { class: 'cn' }, '数值'),
        h('span', { class: 'cv' }, p.kind === 'color' ? '颜色' : '值'),
        h('span', { class: 'cb' }, '闪烁'),
        h('span', { class: 'cx' })
      ]),
      ...p.rows.map((r, i) => h('div', { class: 'rt-r' }, [
        // 数值 = 这一档的起始值（区间结束由下一档决定）
        h('input', {
          class: 'num cn', type: 'number', value: r.from,
          placeholder: '数值',
          onInput: (e) => {
            r.from = e.target.value === '' ? '' : Number(e.target.value)
            normalize()
          }
        }),
        // 颜色：原生取色器，点开自己选；也允许直接粘色号
        p.kind === 'color'
          ? h('input', {
              class: 'clr cv', type: 'color',
              value: /^#[0-9a-fA-F]{6}$/.test(r.value || '') ? r.value : '#22c55e',
              onInput: (e) => { r.value = e.target.value; emit('change') }
            })
          : h('input', {
              class: 'txt cv mono',
              value: r.value === undefined ? '' : (Array.isArray(r.value) ? r.value.join(',') : r.value),
              placeholder: '值',
              onInput: (e) => {
                const t = e.target.value
                r.value = t.includes(',') ? t.split(',') : t
                emit('change')
              }
            }),
        // 闪烁：是/否，是 = 500ms 一闪
        h('select', {
          class: 'sel cb',
          value: r.blink ? '1' : '0',
          onChange: (e) => { r.blink = e.target.value === '1' ? 500 : 0; emit('change') }
        }, [
          h('option', { value: '0' }, '否'),
          h('option', { value: '1' }, '是')
        ]),
        h('button', { class: 'mini cx', onClick: () => del(i) }, '−')
      ])),
      h('button', {
        class: 'mini wide',
        disabled: p.rows.length >= MAX_TIERS,
        title: p.rows.length >= MAX_TIERS ? '最多 ' + MAX_TIERS + ' 档' : '加一档',
        onClick: add
      }, p.rows.length >= MAX_TIERS ? '已到上限（' + MAX_TIERS + ' 档）' : '+ 增加一档')
    ])
  }
})

const attrs = computed(() => (props.item ? dynAttrsOf(props.item.type) : []))
const dyn = ref({})
const attr = ref('')
const mode = ref('')
const f = reactive(blankForm())
const checkMsg = ref('')
const checkOk = ref(false)
const invalid = ref(false)
const pickerOpen = ref(false)
const pickFor = ref('expr')
const pvOpen = ref(false)
const pvList = ref([])
const pvLoading = ref(false)
const resText = ref('—')
const resBad = ref(false)
let clip = null
let resTimer = null

function blankForm() {
  return {
    expr: '', nameExpr: '', triggerType: 'tag', triggerTag: '',
    formula: '', dataType: 'Analog', bit: 0,
    ranges: [], other: '', evalTagStatus: true, evalQuality: true,
    tracks: [], listId: ''
  }
}

const attrKind = computed(() => {
  const a = attrs.value.find(x => x.key === attr.value)
  return a ? a.kind : 'num'
})
function kindOf(k) {
  const a = attrs.value.find(x => x.key === k)
  return a ? a.kind : 'num'
}
const otherHint = computed(() => (attrKind.value === 'color' ? '#7f8c8d' : attrKind.value === 'text' ? '默认文字' : '0'))

function load() {
  dyn.value = props.item ? JSON.parse(JSON.stringify(normDyn(props.item))) : {}
  // 打开时优先跳到「已经配了动态化」的属性上，其次才用第一个。
  // 原来无条件用第一个：按钮1 的第一个属性是「可见」，而实际配的是「背景色」，
  // 打开就是「无」+ 空变量 —— 看着像配置丢了，条件规则表也因此取不到变量。
  if (!attr.value || !dyn.value[attr.value]) {
    const bound = attrs.value.find(a => dyn.value[a.key])
    attr.value = bound ? bound.key : (attrs.value.length ? attrs.value[0].key : '')
  }
  syncForm()
}

function boundOf(k) { return !!dyn.value[k] }

function syncForm() {
  const b = dyn.value[attr.value]
  Object.assign(f, blankForm())
  if (!b) { mode.value = ''; return }
  mode.value = b.mode || ''
  if (b.mode === 'tag') {
    f.expr = tagText(b.expr)
    // 颜色类属性必须把档位读回来。原来只读 expr，导致存进去的档位
    // 一重选对象就在界面上消失（看着像"保存没生效"，其实是根本没加载）。
    f.dataType = b.dataType || 'Analog'
    f.ranges = (b.ranges || []).map(r => ({ ...r }))
    f.other = b.other === undefined ? '' : b.other
  }
  if (b.mode === 'textlist' || b.mode === 'graphlist') { f.expr = tagText(b.expr); f.listId = b.listId || '' }
  if (b.mode === 'indirect') f.nameExpr = b.nameExpr || ''
  if (b.mode === 'dialog') {
    f.triggerType = (b.trigger && b.trigger.type) || 'tag'
    f.triggerTag = (b.trigger && b.trigger.tag) || ''
    f.formula = b.formula || ''
    f.dataType = b.dataType || 'Analog'
    f.bit = b.bit || 0
    f.ranges = (b.ranges || []).map(r => ({ ...r }))
    f.other = b.other === undefined ? '' : b.other
    f.evalTagStatus = b.evalTagStatus !== false
    f.evalQuality = b.evalQuality !== false
  }
  if (b.mode === 'animation') {
    f.expr = tagText(b.expr || (b.trigger && b.trigger.tag) || '')
    f.dataType = b.dataType || 'Analog'
    f.other = b.other === undefined ? '' : b.other
    f.tracks = (b.tracks || []).map(t => ({ attr: t.attr, ranges: (t.ranges || []).map(r => ({ ...r })) }))
  }
}

function onAttr() { checkMsg.value = ''; syncForm() }

function onMode() {
  // 文本列表写的是文字、图形列表换的是图片：切模式就把目标属性拨到能生效的那个
  if (mode.value === 'textlist' && attr.value !== 'text') attr.value = 'text'
  if (mode.value === 'graphlist' && attr.value !== 'image') attr.value = 'image'
  if (!mode.value) {
    delete dyn.value[attr.value]
    commitDyn()
    return
  }
  if (mode.value === 'dialog' && !f.ranges.length) {
    f.ranges = [
      { from: 0, to: 2, value: attrKind.value === 'color' ? '#2ecc71' : '' },
      { from: 2, to: 3, value: attrKind.value === 'color' ? '#f1c40f' : '' },
      { from: 3, to: 3.5, value: attrKind.value === 'color' ? '#e67e22' : '' },
      { from: 3.5, to: null, value: attrKind.value === 'color' ? '#e74c3c' : '', blink: 1000 }
    ]
    if (!f.other) f.other = attrKind.value === 'color' ? '#7f8c8d' : ''
  }
  if (mode.value === 'animation' && !f.tracks.length) {
    f.tracks = [{ attr: attr.value, ranges: [{ from: 0, to: null, value: '' }] }]
  }
  commitForm()
}

function onDataType() {
  if (f.dataType === 'Bool' || f.dataType === 'Bit') {
    // Bool / Bit 只有两组值：0 与 1
    const v0 = (f.ranges[0] && f.ranges[0].value) || (attrKind.value === 'color' ? '#334155' : '0')
    const v1 = (f.ranges[1] && f.ranges[1].value) || (attrKind.value === 'color' ? '#22c55e' : '1')
    f.ranges = [{ from: 0, to: 1, value: v0 }, { from: 1, to: 2, value: v1 }]
  }
  commitForm()
}

function buildBinding() {
  if (mode.value === 'tag') {
    const b = { mode: 'tag', expr: toVar(f.expr) || f.expr }
    // 颜色类属性必须把档位一起存下来。原来这里只存 expr，
    // 导致界面上配好的档位和「其他」默认色一保存就被丢掉 —— 配了等于没配。
    if (attrKind.value === 'color') {
      b.dataType = f.dataType || 'Analog'
      b.ranges = f.ranges.map(r => ({ ...r }))
      if (f.other !== '' && f.other !== undefined && f.other !== null) b.other = f.other
    }
    return b
  }
  if (mode.value === 'textlist' || mode.value === 'graphlist') {
    return { mode: mode.value, expr: toVar(f.expr) || f.expr, listId: f.listId }
  }
  if (mode.value === 'indirect') return { mode: 'indirect', nameExpr: f.nameExpr }
  if (mode.value === 'dialog') {
    return {
      mode: 'dialog',
      trigger: { type: f.triggerType, tag: f.triggerTag || undefined },
      formula: f.formula,
      dataType: f.dataType,
      bit: f.dataType === 'Bit' ? Number(f.bit) : undefined,
      ranges: f.ranges.map(r => ({ ...r })),
      other: f.other === '' ? undefined : f.other,
      evalTagStatus: !!f.evalTagStatus,
      evalQuality: !!f.evalQuality
    }
  }
  if (mode.value === 'animation') {
    return {
      mode: 'animation',
      trigger: { type: 'tag', tag: toVar(f.expr) || f.expr },
      expr: toVar(f.expr) || f.expr,
      dataType: f.dataType,
      other: f.other === '' ? undefined : f.other,
      tracks: f.tracks.map(t => ({ attr: t.attr, ranges: t.ranges.map(r => ({ ...r })) }))
    }
  }
  return null
}

let pending = false
function commitForm() {
  if (!props.item) return false
  const b = buildBinding()
  const next = JSON.parse(JSON.stringify(dyn.value))
  if (b) next[attr.value] = b
  else delete next[attr.value]
  dyn.value = next
  return commitDyn()
}

function commitDyn() {
  if (!props.item) return
  const from = props.item.dyn ? JSON.parse(JSON.stringify(props.item.dyn)) : undefined
  const to = Object.keys(dyn.value).length ? JSON.parse(JSON.stringify(dyn.value)) : undefined
  emit('commit', { from, to })
}

// —— ⑤ 条件规则表（2026-11-14 新增，存 item.rules，不动 dyn）——
let addRuleBlocked = false   // 保留占位（不再用于拦截）
const RULE_ACTION_DEFAULT = { fillColor: '#ef4444', strokeColor: '#ef4444', fontColor: '#ef4444',
                              text: '', visible: '1', blink: '1' }
const ruleList = computed(() => {
  const rs = (props.item && props.item.rules) || []
  return rs.map(r => {
    return { ...r, op: r.op || 'eq', action: r.action || 'fillColor',
             actionValue: r.actionValue === undefined ? (RULE_ACTION_DEFAULT[r.action || 'fillColor'] || '') : r.actionValue }
  })
})
function commitRules(next) {
  if (!props.item) return
  const from = props.item.rules ? JSON.parse(JSON.stringify(props.item.rules)) : undefined
  // 不过滤空 tag 的行：过滤掉就等于「点添加没反应」。空 tag 由运行时回落处理。
  const clean = (next || []).filter(Boolean)
  emit('rules', { from, to: clean.length ? clean : undefined })
}
// 规则统一用上方「直接变量连接」里选的那个变量（f.expr），不再每行单独填。
const ruleVarText = computed(() => {
  const e = f.expr
  if (e == null || e === '') return ''
  if (typeof e === 'string') return e.trim()
  return tagOfVar(e) || ''
})
function ruleToStore(r) {
  // 允许 tag 为空（先加规则后绑变量的场景），运行时回落
  const tag = ruleVarText.value || ''
  return { tag, op: r.op, value: String(r.value ?? ''), action: r.action,
           actionValue: r.actionValue === undefined ? '' : String(r.actionValue) }
}
// 一条规则要能生效，必须同时有：比较值、动作值（visible/blink 用 1/0）
function ruleBad(r) {
  if (!String(r.value ?? '').trim()) return true
  const a = r.action
  if (a === 'visible' || a === 'blink') return !String(r.actionValue ?? '').trim()
  return !String(r.actionValue ?? '').trim()
}
const ruleBadSummary = computed(() => {
  const rs = ruleList.value
  const nv = rs.filter(r => !String(r.value ?? '').trim()).length
  const na = rs.filter(r => String(r.value ?? '').trim() && !String(r.actionValue ?? '').trim()).length
  const parts = []
  if (nv) parts.push(nv + ' 条没填「值」（不会命中）')
  if (na) parts.push(na + ' 条没填「动作值」（动作没有目标值）')
  return parts.join('；')
})
function onRuleEdit() {
  const next = ruleList.value.map(ruleToStore).filter(Boolean)
  commitRules(next)
}
function onRuleAction(r) {
  r.actionValue = RULE_ACTION_DEFAULT[r.action] ?? ''
  onRuleEdit()
}
function addRule() {
  // 允许先加规则再补变量：tag 为空时运行时由 applyRules 回落
  // （item.var → item.dyn 里第一个 expr）。上一版在这里硬拦，
  // 结果在“变量还没选”的状态下点添加完全没反应，等于加不了规则。
  addRuleBlocked = false
  const tag = ruleVarText.value || ''
  const next = ruleList.value.map(ruleToStore).filter(Boolean)
  next.push({ tag, op: 'eq', value: '', action: 'fillColor', actionValue: '#ef4444' })
  commitRules(next)
}
function delRule(i) {
  const next = ruleList.value.map(ruleToStore)
  next.splice(i, 1)
  commitRules(next.filter(Boolean))
}

// —— 表达式检查 ——
function check() {
  const expr = mode.value === 'indirect' ? f.nameExpr : (f.formula || f.triggerTag)
  const r = validate(expr)
  checkOk.value = r.ok
  invalid.value = !r.ok
  if (r.ok) { checkMsg.value = '语法正确'; return }
  const pos = r.pos || 0
  const s = String(expr || '')
  checkMsg.value = `${r.msg}（位置 ${pos + 1}：…${s.slice(Math.max(0, pos - 8), pos)}⟦${s.slice(pos, pos + 8) || '末尾'}⟧）`
}

// —— 变量选择器 ——
function openPicker(which) { pickFor.value = which; pickerOpen.value = true }
function onPick(v) {
  // 选择器只产出 { site, point }（4.3）；tag 字符串仅供内部表达式使用，不进 page.json 的 var
  const isObj = v && typeof v === 'object'
  const tag = isObj ? `${v.site}.${v.point}` : String(v || '')
  if (isObj && pickFor.value === 'var') emit('setvar', { site: v.site, point: v.point })
  if (pickFor.value === 'triggerTag') f.triggerTag = tag
  else if (pickFor.value === 'nameExpr') f.nameExpr = tag
  else if (pickFor.value !== 'var') f.expr = tagText(tag)
  if (mode.value === 'dialog' && !f.formula && pickFor.value !== 'var') f.formula = tag
  commitForm()
}
function onInsertSite(txt) {
  const add = (v) => (v ? v + ' + ' + txt : txt)
  if (pickFor.value === 'nameExpr') f.nameExpr = add(f.nameExpr)
  else f.expr = add(tagText(f.expr))
  commitForm()
}

// —— 200 站点预览 ——
async function preview200() {
  pvOpen.value = true
  pvLoading.value = true
  pvList.value = []
  const expr = f.nameExpr
  const sites = props.sites || []
  const ctx = (site) => ({ site, read: () => ({ found: false }) })
  const pairs = []
  for (const s of sites) {
    const r = evaluate(expr, ctx(s.id))
    if (!r.ok) continue
    pairs.push({ site: s.id, tag: String(r.value) })
  }
  const res = await resolveTags(pairs.map(p => p.tag))
  pvList.value = pairs.map((p, i) => {
    const x = res[i] || {}
    return { site: p.site, tag: p.tag, found: !!x.found, value: x.value, q: x.q, unit: x.unit, msg: x.msg }
  })
  pvLoading.value = false
}

// —— 复制 / 粘贴 / 清除 ——
function copyDyn() {
  clip = JSON.parse(JSON.stringify(dyn.value))
  ElMessage.success('已复制该对象的动态化（共 ' + Object.keys(clip).length + ' 条）')
}
function pasteDyn() {
  if (!clip) return
  dyn.value = JSON.parse(JSON.stringify(clip))
  commitDyn()
  attr.value = Object.keys(dyn.value)[0] || attr.value
  syncForm()
  ElMessage.success('已粘贴动态化')
}
function clearAll() {
  dyn.value = {}
  commitDyn()
  syncForm()
}

// —— 结果实时显示 ——
function refreshResult() {
  if (!props.item || !props.rt || !mode.value) { resText.value = mode.value ? '—' : '无动态化'; resBad.value = false; return }
  const b = buildBinding()
  if (!b) { resText.value = '—'; return }
  const r = resolveOne(attr.value, b, props.item, props.rt)
  if (r.ok) {
    resText.value = String(r.value) + (r.blink ? `（闪烁 ${r.blink}ms）` : '') + (r.quality === 'bad' ? '  ⚠ 质量差' : '')
    resBad.value = r.quality === 'bad'
  } else {
    resText.value = (r.msg || r.reason) + ''
    resBad.value = true
  }
}

watch(() => props.item, () => { load(); refreshResult() }, { immediate: true })
resTimer = setInterval(refreshResult, 500)
onUnmounted(() => { if (resTimer) clearInterval(resTimer) })
</script>

<style scoped>
.dp { font-size: 12px; color: #9fc3e8; }
.grp { border-bottom: 1px solid #12233a; padding-bottom: 4px; }
.gh { padding: 4px 8px; color: #7ba3c9; font-size: 11px; background: #0c1a2b; letter-spacing: .3px; }
.row { display: flex; align-items: center; gap: 4px; padding: 3px 8px; flex-wrap: wrap; }
.lb { flex: 0 0 62px; width: 62px; color: #8fb3d4; }
.sel, .txt, .num { background: #0a1626; border: 1px solid #1e3a5f; color: #e2e8f0;
  border-radius: 3px; padding: 2px 5px; font-size: 12px; min-width: 0; }
.sel { flex: 1; cursor: pointer; }
.txt { flex: 1; }
.num { width: 76px; flex: 0 0 76px; font-family: Consolas, monospace; }
.mono { font-family: Consolas, monospace; }
.txt:focus, .sel:focus, .num:focus { outline: none; border-color: #1ec8ff; }
.txt.err { border-color: #ef4444; }
.mini { background: #12233a; border: 1px solid #1e3a5f; color: #9fc3e8; border-radius: 3px;
  padding: 1px 7px; font-size: 11px; cursor: pointer; }
.mini:hover:not(:disabled) { border-color: #1ec8ff; color: #cdeaff; }
.mini:disabled { opacity: .45; cursor: not-allowed; }
.mini.wide { flex: 1; }
.hint { padding: 2px 8px 4px 70px; color: #5b82a8; font-size: 11px; line-height: 1.6; }
.hint.warn { color: #f59e0b; }
.tip { padding: 2px 8px 4px 70px; color: #f87171; font-size: 11px; }
.tip.ok { color: #22c55e; }
/* 4.3：变量只显示不手输 —— 绑定值用等宽只读文本，未绑定写「未绑定」 */
.bound { flex: 1; min-width: 0; font-size: 12px; color: #cdeaff; padding: 3px 6px;
  background: #0e1f33; border: 1px solid #1e3a5f; border-radius: 3px; word-break: break-all; }
.bound.unbound { color: #5b82a8; font-style: italic; }
.mini.btn-unbind { color: #fca5a5; border-color: #7f1d1d; }
.u { color: #4b6a8a; font-size: 10px; }
.chk { gap: 12px; padding-left: 70px; }
.cb { display: inline-flex; align-items: center; gap: 4px; color: #8fb3d4; }
.cb input { accent-color: #1ec8ff; }
.sw { width: 16px; height: 16px; border: 1px solid #1e3a5f; border-radius: 3px; }
.sub { padding: 4px 8px 2px 70px; color: #6b8fb5; font-size: 11px; }
.track { border-top: 1px dashed #16283d; margin-top: 3px; }
.res { display: flex; align-items: center; gap: 8px; padding: 4px 8px; }
.rl { color: #7ba3c9; }
.rv { color: #22c55e; font-family: Consolas, monospace; }
.rv.bad { color: #f87171; }

:deep(.rt) { padding: 0 8px 2px 70px; }
/* 档位数选择器：先定几档，自动生成对应行数（最多 10 档） */
:deep(.rt-cnt) { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
:deep(.rt-cnt .lb) { flex: 0 0 48px; color: #8fb4d4; font-size: 11px; }
:deep(.rt-cnt-sel) { width: 96px; }
:deep(.rt-cnt-hint) { font-size: 11px; color: #5b82a8; }
:deep(.rt-h), :deep(.rt-r) { display: flex; gap: 3px; align-items: center; margin-bottom: 2px; }
:deep(.rt-h) { color: #5b82a8; font-size: 10px; }
:deep(.rt-h .cn), :deep(.rt-r .cn) { flex: 0 0 74px; width: 74px; }
:deep(.rt-h .cv) { flex: 1; }
:deep(.rt-h .cb) { flex: 0 0 56px; }
:deep(.rt-h .cx) { flex: 0 0 20px; }
:deep(.rt-r .cv) { flex: 1; min-width: 0; }
:deep(.rt-r .cv-wrap) { flex: 1; min-width: 0; display: flex; gap: 4px; align-items: center; }
:deep(.rt-r .clr) { flex: 0 0 30px; width: 30px; height: 22px; padding: 0; border: 1px solid #35506c; border-radius: 3px; background: none; cursor: pointer; }
:deep(.rt-r .clr::-webkit-color-swatch-wrapper) { padding: 1px; }
:deep(.rt-r .clr::-webkit-color-swatch) { border: none; border-radius: 2px; }
:deep(.rt-r .cb) { flex: 0 0 56px; width: 56px; }
:deep(.rt-r .cx) { flex: 0 0 20px; padding: 0 4px; }

.pv { color: #9fc3e8; font-size: 12px; }
.pv-h { display: flex; justify-content: space-between; align-items: center; padding: 0 2px 6px; }
.stat b { font-family: Consolas, monospace; }
.stat .good { color: #22c55e; }
.stat .bad { color: #f87171; }
.pv-b { max-height: 420px; overflow: auto; border: 1px solid #1e3a5f; border-radius: 4px; background: #08111c; }
.pv-r { display: flex; gap: 8px; padding: 3px 8px; border-bottom: 1px solid #10202f; }
.pv-r.bad { color: #f87171; }
.pv-r .s { flex: 0 0 56px; color: #7ba3c9; }
.pv-r .t { flex: 0 0 150px; }
.pv-r .v { flex: 1; }
.pv-r em { color: #5b82a8; font-style: normal; }
.qb { color: #f59e0b; margin-right: 4px; }
.pv-empty { padding: 18px; text-align: center; color: #3b5c82; }
/* ⑤ 条件规则表 */
.rk-grp { border-top: 1px solid #1b3149; padding-top: 8px; }
.rk-var { font-size: 11px; color: #7cc4ff; padding: 0 0 4px; border-radius: 3px; }
.rk-var.flash { animation: rk-flash .5s ease 2; }
@keyframes rk-flash { 0%,100%{background:transparent} 50%{background:rgba(239,68,68,.28)} }
.rk-row.incomplete .rk-c3, .rk-row.incomplete .rk-c5 { border-color: #ef4444 !important; }
.rk-err { font-size: 11px; color: #f87171; padding: 2px 0 4px; }
.rk-var b { color: #cdeaff; }
.rk-warn { color: #f87171; font-style: normal; }
.rk-hd, .rk-row { display: flex; gap: 4px; align-items: center; }
.rk-hd { font-size: 11px; color: #5f7f9f; padding: 2px 0 4px; }
.rk-row { margin-bottom: 4px; }
.rk-c1 { flex: 1.4; min-width: 0; } .rk-c2 { flex: 0 0 84px; }
.rk-c3 { flex: 0 0 54px; } .rk-c4 { flex: 0 0 82px; }
.rk-c5 { flex: 1; min-width: 54px; } .rk-c6 { flex: 0 0 20px; }
.rk-in { background: #0b1a29; border: 1px solid #24405c; color: #cfe4f7;
         border-radius: 3px; padding: 1px 4px; font-size: 12px; height: 22px; }
.rk-in:focus { border-color: #1ec8ff; outline: none; }
.rk-color { height: 22px; padding: 0; border: 1px solid #24405c; border-radius: 3px; background: #0b1a29; }
.rk-del { background: transparent; border: 1px solid #7f1d1d; color: #f87171;
          border-radius: 3px; width: 20px; height: 20px; line-height: 1; cursor: pointer; padding: 0; }
.rk-del:hover { background: #7f1d1d; color: #fff; }
.rk-add { margin-top: 4px; width: 100%; background: #16283c; border: 1px dashed #24405c;
          color: #7cc4ff; border-radius: 3px; padding: 3px; font-size: 12px; cursor: pointer; }
.rk-add:hover { border-color: #1ec8ff; color: #cdeaff; }
</style>
