<template>
  <div class="ctl symb" :class="{ 'ctl-edit': edit }">
    <template v-if="edit">
      <div class="hd">符号库<small>拖到画布</small></div>
      <div class="body">
        <div v-for="g in groups" :key="g.key" class="g">
          <div class="gh">{{ g.key }}</div>
          <div class="grid">
            <div v-for="s in g.items" :key="s.id" class="it" :title="s.name" draggable="true"
                 @dragstart="drag($event, s)">
              <svg viewBox="0 0 100 100" v-html="thumb(s.id)"></svg>
              <span>{{ s.name }}</span>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
// 符号库控件：编辑态是一个可拖拽的图层面板，运行态整块不显示（在 render.js 里隐藏）。
import { computed } from 'vue'
import { SYMBOL_GROUPS, symbolSvg } from './symbols'

const props = defineProps({ item: { type: Object, required: true }, env: { type: Object, required: true } })
const edit = computed(() => props.env.mode === 'edit')
const P = computed(() => props.item.props || {})
// 指定了分组就只列那一组（配置对话框里能选），否则全列出来
const groups = computed(() => {
  const g = String(P.value.group || '').trim()
  return g && g !== '全部' ? SYMBOL_GROUPS.filter(x => x.key === g) : SYMBOL_GROUPS
})

const PAL = { stroke: '#6fa8d8', accent: '#1ec8ff', text: '#9fc3e8', bg: 'transparent', sw: 2 }
function thumb(id) { return symbolSvg(id, 100, 100, PAL) }

function drag(e, s) {
  if (props.env.mode !== 'edit') { e.preventDefault(); return }
  e.dataTransfer.effectAllowed = 'copy'
  e.dataTransfer.setData('text/scada-symbol', JSON.stringify({ symbol: s.id, name: s.name, w: 80, h: 80 }))
  // 有些浏览器只认 text/plain，再加一份
  e.dataTransfer.setData('text/plain', 'symbol:' + s.id)
}
</script>

<style scoped>
.ctl { width: 100%; height: 100%; box-sizing: border-box; overflow: hidden; display: flex; flex-direction: column;
  background: #0d1b2b; font-size: 11px; }
.ctl-edit { pointer-events: auto; }
.hd { padding: 4px 8px; color: #c3ddf5; font-weight: 600; border-bottom: 1px solid #16283d;
  display: flex; justify-content: space-between; align-items: center; }
.hd small { color: #4a6d92; font-weight: 400; font-size: 10px; }
.body { flex: 1 1 auto; overflow: auto; padding: 4px 6px 8px; }
.g { margin-bottom: 4px; }
.gh { color: #5b82a8; font-size: 10px; padding: 3px 2px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(58px, 1fr)); gap: 3px; }
.it { display: flex; flex-direction: column; align-items: center; gap: 1px; padding: 2px; border: 1px solid transparent;
  border-radius: 3px; cursor: grab; color: #9fc3e8; }
.it:hover { background: #12233a; border-color: #1e3a5f; }
.it:active { cursor: grabbing; }
.it svg { width: 30px; height: 30px; }
.it span { font-size: 9px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
</style>
