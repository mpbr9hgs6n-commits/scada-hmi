<template>
  <el-card shadow="never">
    <div class="hd">
      <span class="ttl">数据库备份</span>
      <span class="note">MySQL 导出可下载；TDengine 只显示状态（数据量太大，不做导出）</span>
    </div>

    <!-- MySQL -->
    <el-divider content-position="left">MySQL（配置与业务数据）</el-divider>
    <div class="bar">
      <el-button type="primary" :loading="busy" @click="doBackup">立即备份</el-button>
      <el-button :loading="busy" @click="loadAll">刷新</el-button>
      <span class="meta">
        磁盘剩余 <b :class="{ warn: st.mysql.disk_free_gb < 20 }">{{ st.mysql.disk_free_gb }} GB</b>
        · 保留最近 {{ st.mysql.keep }} 份
        · 上次 <b>{{ st.mysql.last_time || '从未备份' }}</b>
      </span>
    </div>
    <el-table :data="st.files || []" size="small" border style="width:100%">
      <el-table-column prop="name" label="文件名" min-width="260" />
      <el-table-column label="大小" width="120">
        <template #default="{row}">{{ fmtSize(row.size) }}</template>
      </el-table-column>
      <el-table-column prop="mtime" label="生成时间" width="180" />
      <el-table-column label="操作" width="110">
        <template #default="{row}">
          <el-button link type="primary" size="small" @click="download(row.name)">下载</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-alert class="tip" type="info" :closable="false" show-icon
              title="备份前会检查磁盘剩余，低于 10GB 直接拒绝；只保留最近 3 份，旧的自动删除。还原请上服务器人工执行。" />

    <!-- TDengine -->
    <el-divider content-position="left">TDengine（历史时序数据）</el-divider>
    <el-descriptions :column="2" border size="small">
      <el-descriptions-item label="最早数据">{{ st.td.earliest || '—' }}</el-descriptions-item>
      <el-descriptions-item label="已积累天数">{{ st.td.days_used ?? '—' }} 天</el-descriptions-item>
      <el-descriptions-item label="当前保留期(KEEP)">{{ st.td.keep_days ?? '—' }} 天</el-descriptions-item>
      <el-descriptions-item label="MySQL 上次备份">{{ st.mysql.last_time || '从未备份' }}</el-descriptions-item>
    </el-descriptions>
    <el-alert class="tip" type="warning" :closable="false" show-icon
              :title="'TDengine 不提供页面导出：' + (st.td.why || '数据量过大')" />
    <el-alert v-if="st.td.note" class="tip" type="error" :closable="false" show-icon :title="'TDengine 状态读取失败：' + st.td.note" />
  </el-card>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { get, post } from '../utils/request'

const busy = ref(false)
const st = reactive({
  mysql: { last_name: null, last_time: null, last_size: null, keep: 3, disk_free_gb: 0 },
  td: { earliest: null, keep_days: null, days_used: null, note: '', why: '' },
  files: []
})

function fmtSize(n) {
  const b = Number(n) || 0
  if (b < 1024) return b + ' B'
  if (b < 1024 ** 2) return (b / 1024).toFixed(1) + ' KB'
  if (b < 1024 ** 3) return (b / 1024 ** 2).toFixed(1) + ' MB'
  return (b / 1024 ** 3).toFixed(2) + ' GB'
}

async function loadAll() {
  busy.value = true
  try {
    const s = await get('/api/backup/status')
    st.mysql = s.mysql || st.mysql
    st.td = s.tdengine || st.td
    const l = await get('/api/backup/list')
    st.files = l.files || []
    st.mysql.disk_free_gb = l.disk_free_gb ?? st.mysql.disk_free_gb
  } catch (e) {
    ElMessage.error(String(e.message || e))
  } finally { busy.value = false }
}

async function doBackup() {
  try {
    await ElMessageBox.confirm('将执行一次 MySQL 全量导出，可能耗时几十秒到几分钟。继续？', '确认备份',
      { type: 'warning', confirmButtonText: '开始备份', cancelButtonText: '取消' })
  } catch (e) { return }
  busy.value = true
  try {
    const r = await post('/api/backup/create', {})
    ElMessage.success(`备份完成：${r.name}（${fmtSize(r.size)}，${r.ms} ms）`)
    await loadAll()
  } catch (e) {
    ElMessage.error(String(e.message || e))
  } finally { busy.value = false }
}

async function download(name) {
  try {
    const token = localStorage.getItem('token') || ''
    const res = await fetch('/api/backup/download?name=' + encodeURIComponent(name),
                            { headers: { Authorization: 'Bearer ' + token } })
    if (!res.ok) {
      let msg = '下载失败'
      try { const j = await res.json(); msg = j.detail || msg } catch (e) {}
      throw new Error(msg)
    }
    const blob = await res.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = name
    a.click()
    URL.revokeObjectURL(a.href)
  } catch (e) {
    ElMessage.error(String(e.message || e))
  }
}

onMounted(loadAll)
</script>

<style scoped>
.hd { display: flex; align-items: baseline; gap: 12px; margin-bottom: 6px; }
.ttl { font-size: 15px; font-weight: 600; color: #1f2d3d; }
.note { font-size: 12px; color: #909399; }
.bar { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.meta { font-size: 12px; color: #606266; margin-left: 8px; }
.meta b { color: #1f2d3d; }
.meta b.warn { color: #f56c6c; }
.tip { margin-top: 12px; }
</style>
