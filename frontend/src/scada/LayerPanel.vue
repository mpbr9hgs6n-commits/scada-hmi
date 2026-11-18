<template>
  <div class="lp">
    <!-- 图层带：官方 4.5.13 最多 32 层 -->
    <div class="hd">
      <span class="ttl">图层</span>
      <el-select :model-value="curLayer" size="small" class="band" @change="(v) => emit('setLayer', v)">
        <el-option v-for="l in layers" :key="l.id" :value="l.id" :label="l.name" />
      </el-select>
      <button class="mini" :class="{ full: layers.length >= MAX_LAYERS }" :title="layers.length >= MAX_LAYERS
        ? ('官方上限 ' + MAX_LAYERS + ' 层已满，再点会给出提示')
        : ('新建一层（当前 ' + layers.length + '/' + MAX_LAYERS + '）')" @click="emit('addLayer')">＋</button>
      <span class="cnt">{{ layers.length }}/{{ MAX_LAYERS }}</span>
    </div>

    <!-- 层级动作 -->
    <div class="ops">
      <button class="op" :disabled="!sel.length" title="上移一层（Ctrl+]）" @click="emit('zorder', 'up')">↑</button>
      <button class="op" :disabled="!sel.length" title="下移一层（Ctrl+[）" @click="emit('zorder', 'down')">↓</button>
      <button class="op" :disabled="!sel.length" title="置顶" @click="emit('zorder', 'front')">⇧</button>
      <button class="op" :disabled="!sel.length" title="置底" @click="emit('zorder', 'back')">⇩</button>
      <span class="tip">共 {{ items.length }} 个对象，本层 {{ rows.length }}</span>
    </div>

    <div class="list" @dragover.prevent @drop="onDropWrap">
      <div v-for="(r, i) in rows" :key="r.item.name + '#' + r.idx"
           class="row" :class="{ on: sel.includes(r.item), hide: r.item.hidden, lock: r.item.locked, grp: r.item.type === 'group' }"
           draggable="true" :data-idx="r.idx" :data-name="r.item.name"
           @click="emit('select', r.item, $event)"
           @dragstart="onDragStart($event, i, r)"
           @dragover.prevent="onDragOver($event, i)"
           @drop.stop="onRowDrop($event, r)"
           @dragend="dragFrom = -1; dropAt = -1"
           :title="(r.item.name || '') + ' · ' + typeLabel(r.item.type) + (r.item.type === 'group' ? ('（' + (r.item.items || []).length + ' 个子对象）') : '')">
        <span class="ic" v-html="iconOf(r.item)"></span>
        <input v-if="editIdx === r.idx" class="nm-inp" v-model="draft" @click.stop
               @keydown.enter.prevent="commitName(r)" @keydown.esc.stop="cancelEdit"
               @blur="commitName(r)" ref="inpEl">
        <span v-else class="nm" title="双击改名" @dblclick.stop="startEdit(r)">{{ r.item.name || typeLabel(r.item.type) }}</span>
        <span class="ty">{{ typeLabel(r.item.type) }}</span>
        <button class="eye" :title="r.item.hidden ? '已隐藏：画布不渲染，数据保留' : '可见'"
                @click.stop="emit('toggleHidden', r.item)">
          <svg v-if="!r.item.hidden" viewBox="0 0 16 16" width="12" height="12"><path d="M1 8s2.6-4.2 7-4.2S15 8 15 8s-2.6 4.2-7 4.2S1 8 1 8z" fill="none" stroke="currentColor" stroke-width="1.3"/><circle cx="8" cy="8" r="1.9" fill="currentColor"/></svg>
          <svg v-else viewBox="0 0 16 16" width="12" height="12"><path d="M1 8s2.6-4.2 7-4.2S15 8 15 8" fill="none" stroke="currentColor" stroke-width="1.3" opacity=".35"/><path d="M2 14 14 2" stroke="currentColor" stroke-width="1.3"/></svg>
        </button>
        <button class="lk" :title="r.item.locked ? '已锁定：画布上选不中（仍可见）' : '未锁定'"
                @click.stop="emit('toggleLock', r.item)">
          <svg v-if="r.item.locked" viewBox="0 0 16 16" width="12" height="12"><rect x="3.5" y="7" width="9" height="6.5" rx="1" fill="currentColor"/><path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0V7" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>
          <svg v-else viewBox="0 0 16 16" width="12" height="12" opacity=".45"><rect x="3.5" y="7" width="9" height="6.5" rx="1" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>
        </button>
      </div>
      <div v-if="!rows.length" class="empty">本层没有对象</div>
    </div>
  </div>
</template>

<script setup>
// 图层页签（P7）：列表顺序 = z-index 倒序（顶层在最上）。
// 不单独存层级字段——items 数组的顺序就是 z-index，排序就改数组顺序，
// 否则保存/加载时两份数据必然不同步。
import { computed, ref } from 'vue'
import { typeLabel } from './props'
import { MAX_LAYERS } from './arrange'

const props = defineProps({
  items: { type: Array, default: () => [] },   // json.items（顶层）
  layers: { type: Array, default: () => [] },
  curLayer: { type: Number, default: 1 },
  sel: { type: Array, default: () => [] }
})
const emit = defineEmits(['select', 'toggleHidden', 'toggleLock', 'zorder', 'reorder', 'addLayer', 'setLayer', 'rename'])

// 「本层」= item.layer === curLayer；老对象没有 layer 字段时按第 1 层算
const rows = computed(() => {
  const out = []
  props.items.forEach((it, idx) => {
    const lay = Number(it.layer) || 1
    if (lay === props.curLayer) out.push({ item: it, idx })
  })
  return out.reverse()          // 数组末尾在最上层，列表里放最前面
})

const dragFrom = ref(-1)
const dropAt = ref(-1)

// 提示词 10 4.2：双击图层名就地改名（重名/空名由编辑器统一处理）
const editIdx = ref(-1)
const draft = ref('')
const inpEl = ref(null)

async function startEdit(r) {
  editIdx.value = r.idx
  draft.value = r.item.name || ''
  await Promise.resolve()
  const el = Array.isArray(inpEl.value) ? inpEl.value[0] : inpEl.value
  if (el) { el.focus(); el.select() }
}
function cancelEdit() { editIdx.value = -1 }
let committed = false
function commitName(r) {
  if (editIdx.value !== r.idx || committed) { editIdx.value = -1; return }
  committed = true
  const v = String(draft.value || '').trim()
  editIdx.value = -1
  if (v !== (r.item.name || '')) emit('rename', r.item, v)
  setTimeout(() => { committed = false }, 0)
}

function onDragStart(e, i, r) {
  dragFrom.value = r.idx                    // 记的是 items 里的真实下标
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('text/scada-layer', String(r.idx))
}
function onDragOver(e, i) { dropAt.value = i }
function onDropWrap() {
  // 允许拖到空白处：不动（避免误操作），只处理落在行上的情况
  dragFrom.value = -1
  dropAt.value = -1
}
// 行内 drop 由冒泡到容器之前处理：容器已经 prevent，这里用 click 之外的方式接收
function onRowDrop(e, r) {
  e.stopPropagation()
  const from = Number(e.dataTransfer.getData('text/scada-layer'))
  if (Number.isFinite(from) && from !== r.idx) emit('reorder', from, r.idx)
  dragFrom.value = -1
}

function iconOf(it) {
  const C = '#7cc4ff'
  if (it.type === 'group') {
    return `<svg viewBox="0 0 16 16" width="12" height="12"><rect x="1.5" y="3.5" width="8" height="8" fill="none" stroke="${C}" stroke-width="1.2"/><rect x="6.5" y="6.5" width="8" height="8" fill="none" stroke="${C}" stroke-width="1.2"/></svg>`
  }
  if (it.type === 'control') {
    return `<svg viewBox="0 0 16 16" width="12" height="12"><rect x="1.5" y="2.5" width="13" height="11" rx="1" fill="none" stroke="${C}" stroke-width="1.2"/><path d="M1.5 6h13M6 6v7.5" stroke="${C}" stroke-width="1"/></svg>`
  }
  if (it.type === 'text' || it.type === 'value' || it.type === 'input') {
    return `<svg viewBox="0 0 16 16" width="12" height="12"><path d="M3 4h10M8 4v9" stroke="${C}" stroke-width="1.4"/></svg>`
  }
  if (it.type === 'circle' || it.type === 'ellipse' || it.type === 'lamp') {
    return `<svg viewBox="0 0 16 16" width="12" height="12"><circle cx="8" cy="8" r="5.5" fill="none" stroke="${C}" stroke-width="1.2"/></svg>`
  }
  if (it.type === 'line' || it.type === 'polyline' || it.type === 'arc' || it.type === 'pipe') {
    return `<svg viewBox="0 0 16 16" width="12" height="12"><path d="M2 12 14 4" stroke="${C}" stroke-width="1.4"/></svg>`
  }
  return `<svg viewBox="0 0 16 16" width="12" height="12"><rect x="2.5" y="3.5" width="11" height="9" rx="1" fill="none" stroke="${C}" stroke-width="1.2"/></svg>`
}
</script>

<style scoped>
.lp { display: flex; flex-direction: column; height: 100%; min-height: 0; color: #9fc3e8; font-size: 12px; }
.hd { display: flex; align-items: center; gap: 5px; padding: 5px 6px; border-bottom: 1px solid #16283d; }
.hd .ttl { color: #7ba3c9; font-size: 11px; letter-spacing: .5px; }
.band { width: 96px; }
.band :deep(.el-select__wrapper) { min-height: 22px; padding: 0 6px; background: #0e1f33; box-shadow: 0 0 0 1px #1e3a5f inset; }
.band :deep(.el-select__selected-item) { font-size: 11px; color: #cdeaff; }
.mini { width: 20px; height: 20px; line-height: 1; padding: 0; background: #0e1f33; color: #7cc4ff;
        border: 1px solid #1e3a5f; border-radius: 3px; cursor: pointer; }
.mini:hover:not(:disabled) { border-color: #1ec8ff; color: #cdeaff; }
.mini:disabled { opacity: .4; cursor: not-allowed; }
.mini.full { color: #f59e0b; border-color: #7a5a1a; }
.cnt { margin-left: auto; font-family: Consolas, monospace; font-size: 10px; color: #5b82a8; }
.ops { display: flex; align-items: center; gap: 3px; padding: 4px 6px; border-bottom: 1px solid #16283d; }
.op { width: 22px; height: 20px; padding: 0; background: #0e1f33; color: #7cc4ff; border: 1px solid #1e3a5f;
      border-radius: 3px; cursor: pointer; font-size: 12px; line-height: 1; }
.op:hover:not(:disabled) { border-color: #1ec8ff; color: #cdeaff; }
.op:disabled { opacity: .35; cursor: not-allowed; }
.tip { margin-left: auto; font-size: 10px; color: #5b82a8; }
.list { flex: 1; min-height: 0; overflow: auto; padding: 2px; }
.row { display: flex; align-items: center; gap: 4px; padding: 3px 4px; border-radius: 3px; cursor: pointer;
       border: 1px solid transparent; }
.row:hover { background: #12233a; }
.row.on { background: rgba(30,200,255,.14); border-color: #1ec8ff; }
.row.hide .nm, .row.hide .ty { opacity: .38; }
.row.lock .nm { color: #f59e0b; }
.row.grp { background-image: linear-gradient(90deg, rgba(30,200,255,.06), transparent 60%); }
.ic { display: inline-flex; width: 12px; height: 12px; flex: 0 0 12px; opacity: .9; }
.nm { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #cdeaff; }
.nm-inp { flex: 1 1 auto; min-width: 0; background: #0a1626; border: 1px solid #1ec8ff; color: #e2e8f0;
          border-radius: 3px; padding: 0 4px; font-size: 12px; height: 18px; }
.ty { flex: 0 0 auto; font-size: 10px; color: #5b82a8; }
.eye, .lk { flex: 0 0 16px; width: 16px; height: 16px; padding: 0; background: none; border: none;
            color: #7ba3c9; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
.eye:hover, .lk:hover { color: #1ec8ff; }
.empty { padding: 14px 8px; color: #5b82a8; font-size: 11px; text-align: center; }
</style>
