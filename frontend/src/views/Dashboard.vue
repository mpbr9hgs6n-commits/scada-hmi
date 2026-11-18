<template>
  <div>
    <el-row :gutter="12" style="margin-bottom:12px">
      <el-col :span="6"><el-card shadow="never"><el-statistic title="站点总数" :value="total" /></el-card></el-col>
      <el-col :span="6"><el-card shadow="never"><el-statistic title="在线" :value="online" value-style="color:#22c55e" /></el-card></el-col>
      <el-col :span="6"><el-card shadow="never"><el-statistic title="离线" :value="offline" value-style="color:#ef4444" /></el-card></el-col>
      <el-col :span="6"><el-card shadow="never"><el-statistic title="当前报警" :value="alarms" value-style="color:#f59e0b" /></el-card></el-col>
    </el-row>
    <el-card shadow="never">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>站点状态</span>
          <span style="font-size:12px;color:#909399">
            共 {{ total }} 站，本页 {{ sites.length }} 条 · 累计入库 {{ histWritten }} 条
          </span>
        </div>
      </template>
      <el-table :data="sites" size="default" v-loading="loading">
        <el-table-column prop="id" label="站点编号" width="110" />
        <el-table-column prop="name" label="站点名称" min-width="180" />
        <el-table-column prop="plc_ip" label="PLC地址" width="140" />
        <el-table-column prop="plc_port" label="端口" width="90" />
        <el-table-column label="采集状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.online ? 'success' : 'info'" size="small">
              {{ row.online ? '在线' : '未采集' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button link type="primary" @click="$router.push('/site/' + row.id)">进入监控</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination style="margin-top:12px" layout="total, prev, pager, next"
        :total="total" :page-size="size" :current-page="page" @current-change="p => { page = p; load() }" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { get } from '../utils/request'

const sites = ref([]); const total = ref(0); const online = ref(0)
const offline = ref(0); const alarms = ref(0); const histWritten = ref(0)
const page = ref(1); const size = ref(15); const loading = ref(false)
let timer = null

async function load() {
  loading.value = true
  try {
    const r = await get(`/api/sites?size=${size.value}&page=${page.value}`)
    total.value = r.total
    // 在线状态来自网关内存，和数据库里的 status 无关
    const st = await get('/api/sites/status').catch(() => ({ items: [] }))
    const map = {}
    for (const d of st.items || []) map[d.site] = d.online
    sites.value = r.items.map(s => ({ ...s, online: !!map[s.id] }))
    histWritten.value = st.hist_written || 0
    const allOnline = Object.values(map).filter(Boolean).length
    online.value = allOnline
    offline.value = Math.max(total.value - allOnline, 0)
    const a = await get('/api/alarms?state=0&size=1')
    alarms.value = a.total
  } catch (e) {}
  finally { loading.value = false }
}
onMounted(() => { load(); timer = setInterval(load, 10000) })
onUnmounted(() => clearInterval(timer))
</script>
