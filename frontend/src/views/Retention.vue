<template>
  <el-card shadow="never">
    <div class="hd">
      <span class="ttl">数据保留策略</span>
      <span class="note">TDengine 的保留期是数据库级（KEEP），超期数据由它自动清理</span>
    </div>

    <el-form label-width="150px" style="max-width:620px">
      <el-form-item label="历史数据保留">
        <el-input-number v-model="keepDays" :min="1" :max="3650" :step="30" />
        <span class="unit">天</span>
        <div class="hint">超过这个天数的历史数据会被 TDengine 自动删除。6 个月按 180 天算。</div>
      </el-form-item>
      <el-form-item label="提前提醒备份">
        <el-input-number v-model="alertDays" :min="0" :max="365" :step="1" />
        <span class="unit">天</span>
        <div class="hint">距离到期还剩这么多天时，每次登录会弹窗提示备份。填 0 = 不提醒。</div>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="busy" @click="save">保存</el-button>
        <el-button :loading="busy" @click="load">刷新</el-button>
      </el-form-item>
    </el-form>

    <el-divider content-position="left">当前库里实际状态</el-divider>
    <el-descriptions :column="2" border size="small">
      <el-descriptions-item label="TDengine 实际 KEEP">
        <b>{{ actual.tdengine_keep_days ?? '—' }}</b> 天
      </el-descriptions-item>
      <el-descriptions-item label="最早一条数据">{{ actual.earliest || '—' }}</el-descriptions-item>
      <el-descriptions-item label="已积累">{{ actual.days_used ?? '—' }} 天</el-descriptions-item>
      <el-descriptions-item label="距到期">
        <b :class="{ warn: actual.days_left !== null && actual.days_left <= alertDays }">
          {{ actual.days_left ?? '—' }} 天
        </b>
      </el-descriptions-item>
    </el-descriptions>

    <el-alert v-if="notice" class="tip" type="warning" :closable="false" show-icon :title="notice" />
    <el-alert class="tip" type="info" :closable="false" show-icon
              title="改 KEEP 不会立刻删数据：TDengine 按文件块异步回收。验证方式看「实际 KEEP」是否变成你设的值。也不要在保存时顺手删数据。" />
  </el-card>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { get, put } from '../utils/request'

const keepDays = ref(180)
const alertDays = ref(7)
const busy = ref(false)
const notice = ref('')
const actual = reactive({ tdengine_keep_days: null, earliest: null, days_used: null, days_left: null })

async function load() {
  busy.value = true
  try {
    const r = await get('/api/system/retention')
    keepDays.value = r.config?.keep_days ?? 180
    alertDays.value = r.config?.alert_days ?? 7
    Object.assign(actual, r.actual || {})
    notice.value = r.notice || ''
  } catch (e) { ElMessage.error(String(e.message || e)) } finally { busy.value = false }
}

async function save() {
  try {
    await ElMessageBox.confirm(
      `将把 TDengine 的保留期设成 ${keepDays.value} 天（执行 ALTER DATABASE plant KEEP ${keepDays.value}）。` +
      `已有数据不会立即删除，但超过该天数的数据会被自动清理。继续？`,
      '确认修改保留期', { type: 'warning', confirmButtonText: '确认修改', cancelButtonText: '取消' })
  } catch (e) { return }
  busy.value = true
  try {
    const r = await put('/api/system/retention', { keep_days: keepDays.value, alert_days: alertDays.value })
    ElMessage.success(`保留期已改：KEEP ${r.keep_before ?? '—'} → ${r.keep_after ?? '—'} 天`)
    await load()
  } catch (e) {
    ElMessage.error(String(e.message || e))
  } finally { busy.value = false }
}

onMounted(load)
</script>

<style scoped>
.hd { display: flex; align-items: baseline; gap: 12px; margin-bottom: 12px; }
.ttl { font-size: 15px; font-weight: 600; color: #1f2d3d; }
.note { font-size: 12px; color: #909399; }
.unit { margin-left: 8px; font-size: 13px; color: #606266; }
.hint { font-size: 12px; color: #909399; line-height: 1.5; margin-top: 4px; }
.warn { color: #f56c6c; }
.tip { margin-top: 12px; }
</style>
