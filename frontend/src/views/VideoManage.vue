<template>
  <div class="video-page">
    <div class="hd">
      <h2>视频管理</h2>
      <div class="hd-actions">
        <el-button size="small" @click="refreshAll">刷新</el-button>
      </div>
    </div>

    <el-tabs v-model="tab" class="vtabs">
      <!-- ===================== RTSP 通道 ===================== -->
      <el-tab-pane label="RTSP 通道" name="rtsp">
        <div class="bar">
          <el-button type="primary" size="small" @click="openAdd">新增通道</el-button>
          <span class="hint">
            直接填完整 RTSP 地址（含账号密码）。编码为 H.265 的通道浏览器播不了，需在相机侧改成 H.264。
          </span>
        </div>

        <el-table :data="rtspList" size="small" border v-loading="loadingRtsp"
                  empty-text="还没有通道，点「新增通道」添加" style="width:100%">
          <el-table-column prop="stream" label="流名" width="100" />
          <el-table-column prop="name" label="名称" min-width="150" />
          <el-table-column prop="brand" label="品牌" width="100" />
          <el-table-column label="RTSP 地址" min-width="280">
            <template #default="{ row }">
              <span class="mono">{{ row.rtsp_main }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="codec" label="编码" width="80" />
          <el-table-column prop="resolution" label="分辨率" width="110" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag v-if="row.online === true" type="success" size="small">在线</el-tag>
              <el-tag v-else-if="row.online === false" type="danger" size="small">离线</el-tag>
              <el-tag v-else type="info" size="small">未拉流</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="230" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="probe(row)">测试连接</el-button>
              <el-button link type="primary" size="small" @click="startStream(row)">拉流</el-button>
              <el-button link type="danger" size="small" @click="removeRtsp(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

    </el-tabs>

    <!-- 新增 RTSP 通道 -->
    <el-dialog v-model="dlgOpen" title="新增 RTSP 通道" width="640px">
      <el-form :model="form" label-width="110px" size="small">
        <el-form-item label="站点">
          <el-input v-model="form.site_id" placeholder="如 S001" />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="如 进水口" />
        </el-form-item>
        <el-form-item label="品牌">
          <el-select v-model="form.brand" style="width:180px">
            <el-option label="大华" value="dahua" />
            <el-option label="海康" value="hikvision" />
            <el-option label="宇视" value="uniview" />
            <el-option label="其它" value="other" />
          </el-select>
        </el-form-item>
        <el-form-item label="RTSP 地址">
          <el-input v-model="form.rtsp_main" type="textarea" :rows="2"
                    placeholder="rtsp://your_user:your_password@192.168.1.1:554/cam/realmonitor?channel=1&subtype=0" />
        </el-form-item>
        <el-form-item v-if="form.rtsp_main" label=" ">
          <el-button size="small" @click="probeForm" :loading="probing">先测一下通不通</el-button>
          <span v-if="probeResult" class="probe-ok" :class="{ bad: !probeResult.ok }">
            {{ probeResult.ok
               ? `${probeResult.codec} ${probeResult.width}x${probeResult.height} ${probeResult.fps}fps`
               : probeResult.error }}
          </span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="dlgOpen = false">取消</el-button>
        <el-button size="small" type="primary" @click="doAdd" :loading="saving">确定</el-button>
      </template>
    </el-dialog>

    <!-- 新建监控视窗 -->
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { get, post, del } from '../utils/request'

const tab = ref('rtsp')

// ---------------- RTSP ----------------
const rtspList = ref([])
const loadingRtsp = ref(false)
const dlgOpen = ref(false)
const saving = ref(false)
const probing = ref(false)
const probeResult = ref(null)
const form = ref({ site_id: 'S001', name: '', brand: 'dahua', rtsp_main: '' })

// ---------------- 监控视窗 ----------------

function refreshAll() {
  loadRtsp()
}

async function loadRtsp() {
  loadingRtsp.value = true
  try {
    const r = await get('/api/video/sources')
    rtspList.value = r.items || []
  } catch (e) {
    rtspList.value = []
  } finally {
    loadingRtsp.value = false
  }
}

function openAdd() {
  form.value = { site_id: 'S001', name: '', brand: 'dahua', rtsp_main: '' }
  probeResult.value = null
  dlgOpen.value = true
}

async function probeForm() {
  probing.value = true
  probeResult.value = null
  try {
    probeResult.value = await post('/api/video/probe', { url: form.value.rtsp_main })
  } catch (e) {
    probeResult.value = { ok: false, error: e.message || '探测失败' }
  } finally {
    probing.value = false
  }
}

async function doAdd() {
  if (!form.value.rtsp_main) { ElMessage.warning('请填 RTSP 地址'); return }
  saving.value = true
  try {
    await post('/api/video/sources', form.value)
    ElMessage.success('已添加')
    dlgOpen.value = false
    loadRtsp()
  } catch (e) {
    ElMessage.error(e.message || '添加失败')
  } finally {
    saving.value = false
  }
}

async function probe(row) {
  const loading = ElMessage({ message: '探测中…', duration: 0 })
  try {
    const r = await post('/api/video/probe', { id: row.id })
    loading.close()
    if (r.ok) {
      ElMessage.success(`${r.codec} ${r.width}x${r.height} ${r.fps}fps` +
        (r.browser_ok === false ? '（H.265，浏览器播不了）' : ''))
    } else {
      ElMessage.error(r.error || '探测失败')
    }
  } catch (e) {
    loading.close()
    ElMessage.error(e.message || '探测失败')
  }
}

async function startStream(row) {
  try {
    const r = await post('/api/video/live/start', { id: row.id })
    ElMessage.success(r.already ? '已经在拉了' : '已开始拉流')
    loadRtsp()
  } catch (e) {
    ElMessage.error(e.message || '拉流失败')
  }
}

async function removeRtsp(row) {
  try {
    await ElMessageBox.confirm(`删除通道「${row.name}」？（已拖到画面上的不影响）`, '确认', { type: 'warning' })
  } catch (e) { return }
  try {
    await del('/api/video/sources/' + row.id)
    ElMessage.success('已删除')
    loadRtsp()
  } catch (e) {
    ElMessage.error(e.message || '删除失败')
  }
}


onMounted(() => { loadRtsp() })
</script>

<style scoped>
.video-page { padding: 4px 6px; }
.hd { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.hd h2 { font-size: 16px; margin: 0; color: #cfe4f7; }
.bar { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; flex-wrap: wrap; }
.hint { color: #6b8cb0; font-size: 12px; }
.mono { font-family: Consolas, Monaco, monospace; font-size: 12px; color: #9fc3e8; }
.probe-ok { margin-left: 10px; font-size: 12px; color: #4ade80; }
.probe-ok.bad { color: #f87171; }
</style>
