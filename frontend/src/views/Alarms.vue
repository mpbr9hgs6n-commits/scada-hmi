<template>
  <el-card shadow="never">
    <template #header>
      <div style="display:flex;gap:10px;align-items:center">
        <span>当前报警</span>
        <el-select v-model="state" style="width:130px" @change="load">
          <el-option :value="0" label="报警中" />
          <el-option :value="1" label="已确认" />
          <el-option :value="2" label="已恢复" />
          <el-option :value="3" label="已关闭" />
          <el-option :value="null" label="全部" />
        </el-select>
      </div>
    </template>
    <el-table :data="items" size="default">
      <el-table-column prop="site_id" label="站点" width="90" />
      <el-table-column prop="point_code" label="点位" width="120" />
      <el-table-column prop="msg" label="报警内容" min-width="220" />
      <el-table-column prop="val" label="当前值" width="90" align="right" />
      <el-table-column prop="threshold" label="阈值" width="90" align="right" />
      <el-table-column label="级别" width="80">
        <template #default="{ row }">
          <el-tag size="small" :type="row.level === 1 ? 'danger' : 'warning'">
            {{ row.level === 1 ? '紧急' : (row.level === 2 ? '重要' : '一般') }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="['danger','primary','success','info'][row.state]">
            {{ ['报警','已确认','已恢复','已关闭'][row.state] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="count" label="次数" width="70" />
      <el-table-column prop="first_ts" label="首次时间" width="170" />
      <el-table-column prop="last_ts" label="最近时间" width="170" />
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button v-if="row.state === 0" link type="primary" @click="ack(row)">确认</el-button>
          <el-button v-if="row.state !== 3" link type="danger" @click="close(row)">关闭</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination style="margin-top:12px" layout="total, prev, pager, next"
      :total="total" v-model:page-size="size" v-model:current-page="page" @change="load" />
  </el-card>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { get, post } from '../utils/request'

const items = ref([]); const total = ref(0)
const page = ref(1); const size = ref(20); const state = ref(0)
let timer = null

async function load() {
  const q = state.value === null ? '' : `&state=${state.value}`
  const r = await get(`/api/alarms?page=${page.value}&size=${size.value}${q}`)
  items.value = r.items; total.value = r.total
}
async function ack(row) {
  await post(`/api/alarm/${row.id}/ack`, { note: '' })
  ElMessage.success('已确认'); load()
}
async function close(row) {
  await post(`/api/alarm/${row.id}/close`)
  ElMessage.success('已关闭'); load()
}
onMounted(() => { load(); timer = setInterval(load, 5000) })
onUnmounted(() => clearInterval(timer))
</script>
