<template>
  <el-card shadow="never">
    <div class="hd">
      <span class="ttl">数据库查询（只读）</span>
      <span class="note">不提供自由 SQL：20 万点位规模下一条 SELECT * 就能把库拖死</span>
    </div>

    <el-tabs v-model="tab" @tab-change="onTab">
      <!-- ===== 点位 ===== -->
      <el-tab-pane label="点位" name="points">
        <div class="bar">
          <el-select v-model="site" style="width:280px" filterable @change="loadAll">
            <el-option v-for="s in sites" :key="s.id" :value="s.id" :label="`${s.id} ${s.name}`" />
          </el-select>
          <el-input v-model="kw" placeholder="编码/名称/地址" style="width:220px" clearable @keyup.enter="loadPoints" />
          <el-button type="primary" @click="loadPoints">查询</el-button>
          <el-button @click="exportCsv('points')" :disabled="!rows.length">导出 CSV</el-button>
        </div>
        <el-table :data="rows" size="small" border height="520" v-loading="busy">
          <el-table-column prop="code" label="编码" width="130" />
          <el-table-column prop="name" label="名称" width="150" />
          <el-table-column prop="addr" label="地址" width="110" />
          <el-table-column prop="dtype" label="类型" width="90" />
          <el-table-column prop="unit" label="单位" width="70" />
          <el-table-column label="读写" width="60"><template #default="{row}">{{ row.rw ? '读写' : '只读' }}</template></el-table-column>
          <el-table-column label="存档" width="60"><template #default="{row}">{{ row.save_history ? '是' : '否' }}</template></el-table-column>
          <el-table-column prop="hist_interval" label="入库间隔(秒)" width="110" />
          <el-table-column prop="poll_ms" label="采集周期(ms)" width="110" />
        </el-table>
        <el-pagination class="pg" layout="total, prev, pager, next" :total="total"
                       :page-size="50" :current-page="page" @current-change="onPage" />
      </el-tab-pane>

      <!-- ===== 报警 ===== -->
      <el-tab-pane label="报警" name="alarms">
        <div class="bar">
          <el-select v-model="site" style="width:280px" filterable @change="loadAll">
            <el-option v-for="s in sites" :key="s.id" :value="s.id" :label="`${s.id} ${s.name}`" />
          </el-select>
          <el-select v-model="alarmLevel" placeholder="全部级别" clearable style="width:120px">
            <el-option v-for="l in [1,2,3,4]" :key="l" :value="l" :label="'级别 ' + l" />
          </el-select>
          <el-select v-model="alarmState" placeholder="全部状态" clearable style="width:130px">
            <el-option :value="0" label="未确认" /><el-option :value="1" label="已确认" />
            <el-option :value="2" label="已恢复" /><el-option :value="3" label="已关闭" />
          </el-select>
          <el-button type="primary" @click="loadAlarms">查询</el-button>
          <el-button @click="exportCsv('alarms')" :disabled="!rows.length">导出 CSV</el-button>
        </div>
        <el-table :data="rows" size="small" border height="520" v-loading="busy">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="first_ts" label="首次" width="160" />
          <el-table-column prop="point_code" label="点位" width="100" />
          <el-table-column prop="name" label="名称" width="130" />
          <el-table-column prop="level" label="级别" width="70" />
          <el-table-column prop="state" label="状态" width="70" />
          <el-table-column prop="msg" label="内容" show-overflow-tooltip />
        </el-table>
        <el-pagination class="pg" layout="total, prev, pager, next" :total="total"
                       :page-size="50" :current-page="page" @current-change="onPage" />
      </el-tab-pane>

      <!-- ===== 历史 ===== -->
      <el-tab-pane label="历史" name="history">
        <div class="bar">
          <el-select v-model="site" style="width:260px" filterable @change="loadPointsForSite">
            <el-option v-for="s in sites" :key="s.id" :value="s.id" :label="`${s.id} ${s.name}`" />
          </el-select>
          <el-select v-model="hPoint" filterable placeholder="选点位（必填）" style="width:240px">
            <el-option v-for="p in sitePoints" :key="p.code" :value="p.code"
                       :label="`${p.code} ${p.name || ''}`" />
          </el-select>
          <el-date-picker v-model="hFrom" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss"
                          placeholder="开始时间" style="width:200px" />
          <el-date-picker v-model="hTo" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss"
                          placeholder="结束时间" style="width:200px" />
          <el-button type="primary" :disabled="!hPoint || !hFrom || !hTo" :loading="busy" @click="loadHistory">查询</el-button>
          <el-button @click="exportCsv('history')" :disabled="!rows.length">导出 CSV</el-button>
        </div>
        <el-alert v-if="hNote" :title="hNote" type="warning" :closable="false" show-icon class="mb" />
        <el-table :data="rows" size="small" border height="500" v-loading="busy">
          <el-table-column prop="ts" label="时间" width="180" />
          <el-table-column prop="val" label="数值" width="140" />
          <el-table-column prop="q" label="质量" width="80" />
        </el-table>
        <div class="pg" v-if="hTotal !== null">区间内共 {{ hTotal }} 条，本次返回 {{ rows.length }} 条（上限 5000）</div>
      </el-tab-pane>

      <!-- ===== 操作日志 ===== -->
      <el-tab-pane label="操作日志" name="logs">
        <div class="bar">
          <el-input v-model="logUser" placeholder="用户名" style="width:160px" clearable />
          <el-input v-model="logAction" placeholder="动作关键字" style="width:180px" clearable />
          <el-button type="primary" @click="loadLogs">查询</el-button>
          <el-button @click="exportCsv('logs')" :disabled="!rows.length">导出 CSV</el-button>
        </div>
        <el-table :data="rows" size="small" border height="520" v-loading="busy">
          <el-table-column prop="id" label="ID" width="80" />
          <el-table-column prop="ts" label="时间" width="180" />
          <el-table-column prop="username" label="用户" width="120" />
          <el-table-column prop="action" label="动作" width="140" />
          <el-table-column prop="target" label="对象" show-overflow-tooltip />
          <el-table-column prop="detail" label="详情" show-overflow-tooltip />
        </el-table>
        <el-pagination class="pg" layout="total, prev, pager, next" :total="total"
                       :page-size="50" :current-page="page" @current-change="onPage" />
      </el-tab-pane>
    </el-tabs>
  </el-card>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { get } from '../utils/request'

const tab = ref('points')
const sites = ref([])
const site = ref('')
const busy = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)

const kw = ref('')
const alarmLevel = ref(null)
const alarmState = ref(null)

const sitePoints = ref([])
const hPoint = ref('')
const hFrom = ref('')
const hTo = ref('')
const hNote = ref('')
const hTotal = ref(null)

const logUser = ref('')
const logAction = ref('')

const COLS = {
  points: [['编码','code'],['名称','name'],['地址','addr'],['类型','dtype'],['单位','unit'],
           ['读写','rw'],['存档','save_history'],['入库间隔(秒)','hist_interval'],['采集周期(ms)','poll_ms']],
  alarms: [['ID','id'],['首次','first_ts'],['点位','point_code'],['名称','name'],
           ['级别','level'],['状态','state'],['内容','msg']],
  history: [['时间','ts'],['数值','val'],['质量','q']],
  logs: [['ID','id'],['时间','ts'],['用户','username'],['动作','action'],['对象','target'],['详情','detail']]
}

async function loadSites() {
  const r = await get('/api/sites?size=500')
  sites.value = r.items || []
  site.value = sites.value[0]?.id || ''
  await loadAll()
}

function onTab() { page.value = 1; loadAll() }
function onPage(p) { page.value = p; loadAll() }

async function loadAll() {
  if (!site.value) return
  if (tab.value === 'points') return loadPoints()
  if (tab.value === 'alarms') return loadAlarms()
  if (tab.value === 'history') return loadPointsForSite()
  if (tab.value === 'logs') return loadLogs()
}

async function loadPointsForSite() {
  const r = await get(`/api/points?site=${site.value}&size=2000`)
  sitePoints.value = (r.items || []).filter(p => Number(p.save_history) === 1)
  if (!sitePoints.value.some(p => p.code === hPoint.value)) hPoint.value = sitePoints.value[0]?.code || ''
}

async function loadPoints() {
  busy.value = true
  try {
    const q = new URLSearchParams({ site: site.value, keyword: kw.value, page: String(page.value) })
    const r = await get('/api/dbview/points?' + q)
    rows.value = r.rows || []; total.value = r.total || 0
  } catch (e) { ElMessage.error(String(e.message || e)) } finally { busy.value = false }
}

async function loadAlarms() {
  busy.value = true
  try {
    const q = new URLSearchParams({ site: site.value, page: String(page.value) })
    if (alarmLevel.value !== null && alarmLevel.value !== '') q.set('level', String(alarmLevel.value))
    if (alarmState.value !== null && alarmState.value !== '') q.set('state', String(alarmState.value))
    const r = await get('/api/dbview/alarms?' + q)
    rows.value = r.rows || []; total.value = r.total || 0
  } catch (e) { ElMessage.error(String(e.message || e)) } finally { busy.value = false }
}

async function loadHistory() {
  if (!hPoint.value || !hFrom.value || !hTo.value) { ElMessage.warning('点位和起止时间都要选'); return }
  busy.value = true; hNote.value = ''
  try {
    const q = new URLSearchParams({ site: site.value, point: hPoint.value,
      from_ts: hFrom.value, to_ts: hTo.value })
    const r = await get('/api/dbview/history?' + q)
    rows.value = r.rows || []
    hTotal.value = r.total ?? null
    hNote.value = r.note || ''
  } catch (e) { ElMessage.error(String(e.message || e)) } finally { busy.value = false }
}

async function loadLogs() {
  busy.value = true
  try {
    const q = new URLSearchParams({ page: String(page.value) })
    if (logUser.value) q.set('user', logUser.value)
    if (logAction.value) q.set('action', logAction.value)
    const r = await get('/api/dbview/logs?' + q)
    rows.value = r.rows || []; total.value = r.total || 0
  } catch (e) { ElMessage.error(String(e.message || e)) } finally { busy.value = false }
}

function exportCsv(kind) {
  const cols = COLS[kind] || []
  const esc = (v) => {
    const s = String(v === null || v === undefined ? '' : v)
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
  }
  const lines = [cols.map(c => c[0]).join(',')]
  for (const r of rows.value) lines.push(cols.map(c => esc(r[c[1]])).join(','))
  const csv = '\ufeff' + lines.join('\n') + '\n'
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  a.download = `dbview_${kind}_${new Date().toISOString().slice(0,10)}.csv`
  a.click()
  URL.revokeObjectURL(a.href)
}

onMounted(loadSites)
</script>

<style scoped>
.hd { display: flex; align-items: baseline; gap: 12px; margin-bottom: 10px; }
.ttl { font-size: 15px; font-weight: 600; color: #1f2d3d; }
.note { font-size: 12px; color: #909399; }
.bar { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
.pg { margin-top: 10px; text-align: right; font-size: 12px; color: #606266; }
.mb { margin-bottom: 10px; }
</style>
