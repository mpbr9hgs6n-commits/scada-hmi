<template>
  <el-card shadow="never">
    <!-- 查询条件：站点 / 点位 + 年/月/日/时（粒度自动） -->
    <div class="bar">
      <el-button type="primary" plain @click="openExport">导出数据</el-button>
      <el-select v-model="site" style="width:210px" filterable @change="loadPoints">
        <el-option v-for="s in sites" :key="s.id" :value="s.id" :label="`${s.id} ${s.name}`" />
      </el-select>
      <el-select v-model="point" style="width:260px" filterable clearable placeholder="全部点位（≤20 个）">
        <el-option v-for="p in points" :key="p.code" :value="p.code"
                   :label="`${p.code} ${p.name || ''}${p.unit ? ' (' + p.unit + ')' : ''}`" />
      </el-select>
      <el-select v-model="year" style="width:100px" @change="onDim">
        <el-option v-for="y in years" :key="y" :value="y" :label="y + ' 年'" />
      </el-select>
      <el-select v-model="month" style="width:100px" clearable placeholder="全年" @change="onDim">
        <el-option v-for="m in 12" :key="m" :value="m" :label="m + ' 月'" />
      </el-select>
      <el-select v-model="day" style="width:100px" clearable placeholder="全月" :disabled="!month" @change="onDim">
        <el-option v-for="d in 31" :key="d" :value="d" :label="d + ' 日'" />
      </el-select>
      <el-select v-model="hour" style="width:110px" clearable placeholder="全天" :disabled="!day" @change="onDim">
        <el-option v-for="h in 24" :key="h - 1" :value="h - 1" :label="(h - 1) + ' 时'" />
      </el-select>
      <el-button type="primary" :loading="loading" @click="load">查询</el-button>
      <el-button :disabled="!rows.length" @click="exportCsv">导出 CSV</el-button>
    </div>
    <div class="meta">
      <span v-if="meta.range">范围 {{ meta.range[0] }} ~ {{ meta.range[1] }}</span>
      <span v-if="meta.granularity">粒度 {{ granLabel }}</span>
      <span v-if="meta.note" class="warn">{{ meta.note }}</span>
      <span>共 {{ rows.length }} 行</span>
    </div>

    <div ref="chart" style="height:420px"></div>

    <el-table :data="rows" size="small" height="240" style="margin-top:8px" empty-text="该时段没有数据（曲线断点，不补 0）">
      <el-table-column prop="ts" label="时间" width="200" />
      <el-table-column label="值" width="160">
        <template #default="{ row }">{{ row.val === null || row.val === undefined ? '—' : row.val }}</template>
      </el-table-column>
      <el-table-column label="单位" width="100"><template #default>{{ unit }}</template></el-table-column>
      <el-table-column label="采样数" width="100"><template #default="{ row }">{{ row.n ?? '—' }}</template></el-table-column>
    </el-table>

    <!-- 删除（admin）：按日期 / 只保留最近 N 天 -->
    <div v-if="isAdmin" class="danger">
      <el-button type="danger" plain :disabled="!point || !day" @click="delByDate">删除指定日期</el-button>
      <span class="hint">需选到「日」；只删所选点位该天的数据，不可恢复</span>
      <el-divider direction="vertical" />
      <span>只保留最近</span>
      <el-input-number v-model="keepDays" :min="7" :max="3650" size="small" style="width:110px;margin:0 6px" />
      <span>天</span>
      <el-button type="danger" plain :disabled="!point" @click="delKeepDays">清理更早数据</el-button>
    </div>
    <!-- 导出：自定义开始-截止日期，精确到天（第 02 章） -->
    <el-dialog v-model="expVisible" title="导出历史数据" width="460px">
      <el-form label-width="92px">
        <el-form-item label="站点">
          <el-input :model-value="`${expSite} ${expSiteName}`" disabled />
        </el-form-item>
        <el-form-item label="点位">
          <el-select v-model="expPoint" filterable style="width:100%" placeholder="只列出已开启存档的点位">
            <el-option v-for="p in expPoints" :key="p.code" :value="p.code"
                       :label="`${p.code} ${p.name || ''}${p.unit ? ' (' + p.unit + ')' : ''}`" />
          </el-select>
        </el-form-item>
        <el-form-item label="开始日期">
          <el-date-picker v-model="expFrom" type="date" value-format="YYYY-MM-DD" style="width:100%" />
        </el-form-item>
        <el-form-item label="截止日期">
          <el-date-picker v-model="expTo" type="date" value-format="YYYY-MM-DD" style="width:100%" />
        </el-form-item>
        <el-form-item>
          <span class="exp-tip">开始取当天 00:00:00，截止取当天 23:59:59；单次上限 50 万条。</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="expVisible = false">取消</el-button>
        <el-button type="primary" :loading="expBusy" @click="doExport">导出 CSV</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as echarts from 'echarts'
import { get, del } from '../utils/request'
import { useUserStore } from '../store'

const user = useUserStore()
const isAdmin = computed(() => user.user?.role === 'admin')

const sites = ref([])
const points = ref([])
const site = ref('S001')
const point = ref('')
const year = ref(new Date().getFullYear())
const month = ref(null)
const day = ref(null)
const hour = ref(null)
const years = Array.from({ length: 6 }, (_, i) => new Date().getFullYear() - 3 + i)
const rows = ref([])
const meta = reactive({ range: null, granularity: '', note: '' })
const loading = ref(false)
const keepDays = ref(30)
const chart = ref(null)
let ch = null

const unit = computed(() => (points.value.find(p => p.code === point.value) || {}).unit || '')
const granLabel = computed(() => ({
  '1s': '按秒', '5s': '按 5 秒', '1m': '按分钟', '1d': '按天'
}[meta.granularity] || meta.granularity))

function onDim() {
  if (!month.value) { day.value = null }
  if (!day.value) { hour.value = null }
}

// ===== 导出（第 02 章）：按日期区间导单个点位 =====
const expVisible = ref(false)
const expBusy = ref(false)
const expPoint = ref('')
const expFrom = ref('')
const expTo = ref('')
const expSite = computed(() => site.value)
const expSiteName = computed(() => {
  const s0 = sites.value.find(x => x.id === site.value)
  return s0 ? (s0.name || '') : ''
})
// 只列已开启存档的点位：没存历史的点位导出来必然是空表
const expPoints = computed(() => (points.value || []).filter(p => Number(p.save_history) === 1))

function openExport() {
  if (!site.value) { ElMessage.error('请先选站点'); return }
  expPoint.value = expPoints.value.some(p => p.code === point.value)
    ? point.value : (expPoints.value[0]?.code || '')
  const d = new Date()
  const iso = (x) => x.getFullYear() + '-' + String(x.getMonth() + 1).padStart(2, '0') + '-' + String(x.getDate()).padStart(2, '0')
  expTo.value = iso(d)
  expFrom.value = iso(new Date(d.getTime() - 6 * 86400000))
  expVisible.value = true
}

async function doExport() {
  if (!expPoint.value) { ElMessage.error('请选择点位'); return }
  if (!expFrom.value || !expTo.value) { ElMessage.error('请选择开始和截止日期'); return }
  if (expFrom.value > expTo.value) { ElMessage.error('开始日期不能晚于截止日期'); return }
  expBusy.value = true
  try {
    const qs = new URLSearchParams({
      site: site.value, point: expPoint.value,
      from_date: expFrom.value, to_date: expTo.value
    }).toString()
    const token = localStorage.getItem('token') || ''
    const res = await fetch('/api/history/export?' + qs, { headers: { Authorization: 'Bearer ' + token } })
    if (!res.ok) {
      let msg = '导出失败'
      try { const j = await res.json(); msg = j.detail || msg } catch (e) {}
      throw new Error(msg)
    }
    const blob = await res.blob()
    const cd = res.headers.get('content-disposition') || ''
    const m = cd.match(/filename="?([^";]+)"?/)
    const name = m ? m[1] : ('history_' + expPoint.value + '.csv')
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = name
    a.click()
    URL.revokeObjectURL(a.href)
    ElMessage.success('已导出')
    expVisible.value = false
  } catch (e) {
    ElMessage.error(String(e && e.message ? e.message : e))
  } finally { expBusy.value = false }
}

async function loadPoints() {
  const r = await get(`/api/points?site=${site.value}&size=200`)
  points.value = r.items || []
  if (!points.value.some(p => p.code === point.value)) {
    point.value = points.value[0]?.code || ''
  }
  load()
}

async function load() {
  if (!site.value) return
  loading.value = true
  const q = new URLSearchParams({ site: site.value, year: String(year.value) })
  if (point.value) q.set('point', point.value)
  if (month.value) q.set('month', String(month.value))
  if (day.value) q.set('day', String(day.value))
  if (hour.value !== null && hour.value !== '') q.set('hour', String(hour.value))
  try {
    const r = await get('/api/history?' + q.toString())
    rows.value = r.rows || (r.series && r.series[0] ? r.series[0].rows : []) || []
    meta.range = r.range || null
    meta.granularity = r.granularity || ''
    meta.note = r.note || ''
    draw()
  } catch (e) {
    rows.value = []
    draw()
  } finally {
    loading.value = false
  }
}

function draw() {
  if (!ch) return
  const data = rows.value
  ch.setOption({
    title: {
      text: `${site.value}${point.value ? ' · ' + point.value : ''}  历史曲线（${granLabel.value}）`,
      left: 'center', textStyle: { fontSize: 13 }
    },
    tooltip: { trigger: 'axis' },
    grid: { left: 62, right: 24, top: 46, bottom: 34 },
    xAxis: {
      type: 'category',
      data: data.map(x => String(x.ts || '').slice(5, 19)),
      axisLabel: { fontSize: 11 }
    },
    yAxis: { type: 'value', scale: true, name: unit.value || undefined },
    series: [{
      type: 'line', data: data.map(x => (x.val === null || x.val === undefined ? null : x.val)),
      showSymbol: false, connectNulls: false,
      lineStyle: { color: '#1d4ed8', width: 2 },
      areaStyle: { color: 'rgba(29,78,216,.06)' }
    }]
  }, true)
}

function exportCsv() {
  const head = '时间,值,单位\n'
  const body = rows.value.map(r => `${r.ts},${r.val ?? ''},${unit.value}`).join('\n')
  const blob = new Blob(['\ufeff' + head + body], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `${site.value}_${point.value || 'all'}_${year.value}${month.value ? '-' + month.value : ''}${day.value ? '-' + day.value : ''}.csv`
  a.click()
  URL.revokeObjectURL(a.href)
}

function dateStr() {
  const m = String(month.value).padStart(2, '0')
  const d = String(day.value).padStart(2, '0')
  return `${year.value}-${m}-${d}`
}

async function delByDate() {
  const ds = dateStr()
  try {
    await ElMessageBox.confirm(
      `将删除 ${site.value}/${point.value} 在 ${ds} 的数据，不可恢复。确定继续？`,
      '删除历史数据', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' })
  } catch { return }
  const r = await del(`/api/history?site=${encodeURIComponent(site.value)}`
    + `&point=${encodeURIComponent(point.value)}&date=${ds}&confirm=1`)
  ElMessage.success(`已删除 ${r.deleted_rows} 行`)
  load()
}

async function delKeepDays() {
  if (!keepDays.value || keepDays.value < 7) {
    ElMessage.warning('只保留天数不能小于 7（防误删）')
    return
  }
  try {
    await ElMessageBox.confirm(
      `${site.value}/${point.value} 只保留最近 ${keepDays.value} 天，更早的数据将被删除，不可恢复。确定继续？`,
      '清理历史数据', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' })
  } catch { return }
  const r = await del(`/api/history?site=${encodeURIComponent(site.value)}`
    + `&point=${encodeURIComponent(point.value)}&keep_days=${keepDays.value}&confirm=1`)
  ElMessage.success(`已删除 ${r.deleted_rows} 行（${r.scope}）`)
  load()
}

onMounted(async () => {
  ch = echarts.init(chart.value)
  const r = await get('/api/sites?size=500')
  sites.value = r.items || []
  const cur = sites.value.find(s => s.id === 'S001') ? 'S001' : (sites.value[0] || {}).id
  site.value = cur || ''
  await loadPoints()
  window.addEventListener('resize', () => ch && ch.resize())
})
</script>

<style scoped>
.bar { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 8px; }
.meta { display: flex; gap: 16px; font-size: 12px; color: var(--el-text-color-secondary); margin-bottom: 4px; }
.meta .warn { color: var(--el-color-warning); }
.danger { margin-top: 10px; padding-top: 8px; border-top: 1px dashed var(--el-border-color);
          display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 13px; }
.danger .hint { color: var(--el-text-color-secondary); font-size: 12px; }

.exp-tip { font-size: 12px; color: #909399; line-height: 1.5; }
</style>
