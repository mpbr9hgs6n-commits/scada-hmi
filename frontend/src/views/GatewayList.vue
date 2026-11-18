<template>
  <div class="gw-page">
    <div class="hd">
      <h2>采集网关</h2>
      <div>
        <span class="hint">每个网关一套独立 TDengine，共享 MySQL / Redis；一个网关最多 {{ maxSites }} 台 PLC</span>
        <el-button size="small" style="margin-left:12px" @click="load">刷新</el-button>
        <el-button v-if="canEdit" type="primary" size="small" @click="openForm(null)">新建网关</el-button>
      </div>
    </div>

    <el-alert v-if="offlineGws.length" type="error" :closable="false" show-icon
              style="margin-bottom:12px"
              :title="'有 ' + offlineGws.length + ' 个网关没有运行：' + offlineGws.join('、')"
              description="站点分给这些网关就没人采集，写点位会报『点位不存在』。先把容器起起来（compose 里加 gateway-{标识} 和 tdengine-{标识}），或者把站点改到运行中的网关。" />

    <el-table :data="rows" size="small" border v-loading="loading">
      <el-table-column prop="id" label="网关标识" width="110" />
      <el-table-column prop="name" label="名称" width="150" />
      <el-table-column label="运行状态" width="120">
        <template #default="{ row }">
          <el-tag :type="row.online ? 'success' : 'danger'" size="small">
            {{ row.online ? '运行中' : '未运行' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="tdengine_url" label="TDengine 地址" min-width="200" show-overflow-tooltip />
      <el-table-column label="已挂 PLC" width="110">
        <template #default="{ row }">
          <el-tag :type="row.sites >= maxSites ? 'danger' : 'info'" size="small">
            {{ row.sites }} / {{ maxSites }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="remark" label="备注" min-width="150" show-overflow-tooltip />
      <el-table-column prop="created_at" label="创建时间" width="160" />
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button v-if="canEdit" link size="small" @click="openForm(row)">编辑</el-button>
          <el-button v-if="canEdit" link size="small" type="danger"
                     :disabled="row.sites > 0" @click="del(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="tip">
      加网关的完整步骤：① 在 compose.yml 里加 gateway-gw2 + tdengine-gw2 两个服务（文件末尾有示例）
      ② 在本页登记 gw2，TDengine 地址填 <code>http://tdengine-gw2:6041</code>
      ③ 到站点管理把要迁的站点改到 gw2。MySQL / Redis 继续共用，不用动。
    </div>

    <el-dialog v-model="form.show" :title="form.editing ? '编辑网关' : '新建网关'" width="560px">
      <el-form label-width="120px">
        <el-form-item label="网关标识" required>
          <el-input v-model="form.data.id" :disabled="form.editing" maxlength="32"
                    placeholder="如 gw2（只能英文/数字/下划线/短横）"
                    @input="onIdInput" />
          <div class="form-hint">
            只能用英文字母、数字、下划线、短横，必须以字母或数字开头（如 gw2）。
            不能填中文：它要拼进容器名 <code>gateway-gw2</code> 和 DNS 名
            <code>tdengine-gw2</code>，这两处只接受 ASCII。
          </div>
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="form.data.name" placeholder="如 二号网关" />
        </el-form-item>
        <el-form-item label="TDengine 地址">
          <el-input :model-value="previewTd" readonly />
          <div class="form-hint">
            系统按网关标识自动生成：gw1 用现有实例，gwN 用 tdengine-gwN。
            地址不需要（也不能）手填，避免和实际部署对不上。
          </div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.data.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="form.show = false">取消</el-button>
        <el-button type="primary" :loading="form.saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { get, post, put, del as httpDel } from '../utils/request'
import { useUserStore } from '../store'

const user = useUserStore()
const canEdit = computed(() => ['admin', 'operator'].includes(user.user?.role))
const rows = ref([])
const loading = ref(false)
const maxSites = ref(20)
const form = reactive({ show: false, editing: false, saving: false, data: {} })

// 没在运行的网关：站点分过去就没人采，必须在页面上直接点出来
const offlineGws = computed(() => rows.value.filter(r => !r.online).map(r => r.id))

// 地址由后端按网关标识生成，这里只是把将要生成的地址提前显示出来给人看
const previewTd = computed(() => {
  const id = ((form.data && form.data.id) || '').trim()
  if (!id) return '（填了网关标识后自动生成）'
  if (form.editing && form.data.tdengine_url) return form.data.tdengine_url
  if (id.toLowerCase() === 'gw1') return 'http://tdengine:6041'
  return 'http://tdengine-' + id.toLowerCase() + ':6041'
})

async function load() {
  loading.value = true
  try {
    const r = await get('/api/gateways')
    rows.value = r.items || []
    maxSites.value = r.max_sites || 20
  } catch (e) { /* 已提示 */ } finally { loading.value = false }
}

// 网关标识实时过滤：敲中文/空格/符号直接摇掉，不留到保存时才报错
function onIdInput(v) {
  const clean = String(v || '').replace(/[^A-Za-z0-9_-]/g, '')
  if (clean !== v) form.data.id = clean
}

function openForm(row) {
  form.editing = !!row
  form.data = row ? { ...row } : { id: '', name: '', tdengine_url: '', remark: '' }
  form.show = true
}

async function save() {
  const d = form.data
  if (!d.id) { ElMessage.warning('网关标识必填'); return }
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$/.test(d.id)) {
    ElMessage.error('网关标识只能用英文字母、数字、下划线、短横，且必须以字母或数字开头')
    return
  }
  if (!d.name) { ElMessage.warning('名称必填'); return }
  form.saving = true
  try {
    // tdengine_url 不传：后端按网关标识自动生成
    const { tdengine_url, sites, created_at, ...payload } = d
    if (form.editing) await put('/api/gateway/' + d.id, payload)
    else await post('/api/gateway', payload)
    ElMessage.success('已保存')
    form.show = false
    load()
  } catch (e) { /* 已提示 */ } finally { form.saving = false }
}

async function del(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除网关 ${row.id}？它专属的 TDengine 数据不会自动删除。`, '删除网关',
      { type: 'warning' })
  } catch (e) { return }
  try {
    await httpDel('/api/gateway/' + row.id)
    ElMessage.success('已删除')
    load()
  } catch (e) { /* 已提示 */ }
}

onMounted(load)
</script>

<style scoped>
.gw-page { padding: 16px; }
.hd { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.hd h2 { margin: 0; font-size: 17px; }
.hint { font-size: 12px; color: var(--el-text-color-secondary); }
.tip { margin-top: 14px; font-size: 12px; line-height: 1.8; color: var(--el-text-color-secondary); }
.tip code { background: var(--el-fill-color-light); padding: 1px 5px; border-radius: 3px; }
.form-hint { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.5; margin-top: 4px; }
</style>
