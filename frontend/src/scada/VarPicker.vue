<template>
  <el-dialog v-model="open" title="关联变量（站点 · 点位）" width="620px" append-to-body
             :close-on-click-modal="false">
    <el-form label-width="70px">
      <el-form-item label="站点">
        <el-select v-model="site" style="width:100%" filterable placeholder="选择站点"
                   @change="loadPoints">
          <el-option v-for="s in enabledSites" :key="s.id" :value="s.id"
                     :label="`${s.id} ${s.name || ''}`" />
        </el-select>
      </el-form-item>
      <el-form-item label="点位">
        <el-select v-model="code" style="width:100%" filterable placeholder="选择点位（可输入编码/名称过滤）"
                   :disabled="!site" :loading="loading">
          <el-option v-for="p in points" :key="p.code" :value="p.code"
                     :label="`${p.code} ${p.name || ''}${p.unit ? ' (' + p.unit + ')' : ''}`" />
        </el-select>
      </el-form-item>
      <el-form-item label="当前">
        <span class="cur">{{ site && code ? site + '.' + code : '未选择' }}</span>
        <span v-if="pickedUnit" class="unit">单位 {{ pickedUnit }}</span>
      </el-form-item>
    </el-form>
    <div v-if="site && !loading && !points.length" class="tip">
      该站点没有启用的点位（enabled=1）
    </div>

    <template #footer>
      <el-button @click="open = false">取消</el-button>
      <el-button type="primary" :disabled="!site || !code" @click="confirm">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
// 变量选择器（提示词 10 4.3）：只有「站点 → 点位」两个下拉，禁止手写表达式。
// 输出对象 { site, point }，由调用方写进 page.json 的 items[].var。
import { computed, ref, watch } from 'vue'
import { get } from '../utils/request'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  sites: { type: Array, default: () => [] },
  site: { type: String, default: '' },
  writable: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue', 'pick'])

const open = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v)
})

const site = ref(props.site || '')
const code = ref('')
const points = ref([])
const loading = ref(false)

// 站点下拉只列 enabled=1
const enabledSites = computed(() => (props.sites || []).filter(s => s.enabled !== 0))
const pickedUnit = computed(() => (points.value.find(p => p.code === code.value) || {}).unit || '')
const current = computed(() => (site.value && code.value ? { site: site.value, point: code.value } : null))

async function loadPoints() {
  code.value = ''
  points.value = []
  if (!site.value) return
  loading.value = true
  try {
    // size 要够：1000 点的站点也必须能选到最后一个点位（后端上限 2000）
    const r = await get(`/api/points?site=${encodeURIComponent(site.value)}&enabled=1&size=2000`)
    // 只列启用点位；可写模式再筛 rw=1
    points.value = (r.items || []).filter(p => p.enabled !== 0 && (!props.writable || p.rw === 1))
  } catch (e) {
    points.value = []
  } finally {
    loading.value = false
  }
}

watch(() => props.modelValue, (v) => {
  if (v) {
    if (!site.value) site.value = props.site || (enabledSites.value[0] || {}).id || ''
    loadPoints()
  }
})
watch(() => props.site, (v) => { if (v) site.value = v })

function confirm() {
  if (!current.value) return
  emit('pick', current.value)
  open.value = false
}
</script>

<style scoped>
.cur { font-family: Consolas, monospace; color: #1d4ed8; font-size: 14px; }
.unit { margin-left: 12px; font-size: 12px; color: var(--el-text-color-secondary); }
.tip { padding: 6px 0 0 70px; font-size: 12px; color: var(--el-color-warning); }
</style>
