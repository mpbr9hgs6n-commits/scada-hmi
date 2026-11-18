<template>
  <div class="page-list">
    <div class="hd">
      <h2>画面列表</h2>
      <div class="hd-actions">
        <el-button size="small" @click="load">刷新</el-button>
        <el-button type="primary" size="small" @click="openNew">新建画面</el-button>
      </div>
    </div>

    <div class="bar">
      <span class="hint">
        已发布：</span><el-tag type="success" size="small">{{ publishedCount }}</el-tag>
      <span class="hint">草稿：</span><el-tag size="small">{{ pages.length - publishedCount }}</el-tag>
      <span class="hint" style="margin-left:14px">
        发布后的画面会出现在 <code>/publish</code> 的目录树里，按站点分组
      </span>
      <div class="sp" />
      <el-button size="small" v-if="publishedCount" @click="openPublish">打开发布入口</el-button>
    </div>

    <el-table :data="pages" size="small" border v-loading="loading"
              empty-text="还没有组态画面" style="width:100%">
      <el-table-column label="缩略图" width="110">
        <template #default="{ row }">
          <img v-if="row.thumb" :src="thumbUrl(row)" class="thumb" alt="" />
          <div v-else class="thumb none">无</div>
        </template>
      </el-table-column>
      <el-table-column prop="name" label="名称" min-width="180" />
      <el-table-column label="站点" width="110">
        <template #default="{ row }">
          <span v-if="row.site_id">{{ row.site_id }}</span>
          <span v-else class="dim">未分类</span>
        </template>
      </el-table-column>
      <el-table-column prop="objects" label="对象数" width="90" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.published ? 'success' : 'info'" size="small">
            {{ row.published ? '已发布' : '草稿' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="updated_at" label="更新时间" width="175" />
      <el-table-column label="操作" width="290" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openEditor(row)"
                     title="用组态编辑器打开这张画面">编辑</el-button>
          <el-button link type="primary" size="small" @click="preview(row)">预览</el-button>
          <el-button link size="small"
                     :type="row.published ? 'warning' : 'success'"
                     @click="togglePublish(row)">
            {{ row.published ? '取消发布' : '发布' }}
          </el-button>
          <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建画面 -->
    <el-dialog v-model="dlg" title="新建组态画面" width="480px">
      <el-form :model="form" label-width="80px" size="small">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="如 生化池监控" />
        </el-form-item>
        <el-form-item label="站点">
          <el-select v-model="form.site_id" clearable filterable style="width:220px"
                     placeholder="不选则归入「未分类」">
            <el-option v-for="s in sites" :key="s.id" :label="`${s.id} ${s.name || ''}`" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="尺寸">
          <el-select v-model="form.size" style="width:180px">
            <el-option label="1600 × 900" value="1600x900" />
            <el-option label="1920 × 1080" value="1920x1080" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="dlg = false">取消</el-button>
        <el-button size="small" type="primary" :loading="creating" @click="doCreate">创建并编辑</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { get, post, del } from '../utils/request'

const router = useRouter()
const pages = ref([])
const sites = ref([])
const loading = ref(false)
const dlg = ref(false)
const creating = ref(false)
const form = ref({ name: '', site_id: '', size: '1600x900' })

const publishedCount = computed(() => pages.value.filter(p => p.published).length)

function thumbUrl(row) {
  // ?v=更新时间 防缓存
  const v = encodeURIComponent(String(row.updated_at || '').replace(/\s+/g, '_'))
  return `/api/page/${row.id}/thumb.png?v=${v}`
}

async function load() {
  loading.value = true
  try {
    const r = await get('/api/pages?kind=scada')
    pages.value = r.items || []
  } catch (e) {
    pages.value = []
    ElMessage.error(e.message || '读取画面列表失败')
  } finally {
    loading.value = false
  }
}

async function loadSites() {
  try {
    const r = await get('/api/sites')
    sites.value = r.items || r.sites || []
  } catch (e) { sites.value = [] }
}

function openNew() {
  form.value = { name: '', site_id: '', size: '1600x900' }
  dlg.value = true
}

async function doCreate() {
  if (!form.value.name.trim()) { ElMessage.warning('请填名称'); return }
  const [w, h] = form.value.size.split('x').map(Number)
  creating.value = true
  try {
    const r = await post('/api/page', {
      name: form.value.name.trim(),
      kind: 'scada',
      site_id: form.value.site_id || null,
      json: { width: w, height: h, items: [] },
    })
    const nid = r.id || (r.page && r.page.id)
    dlg.value = false
    if (nid) router.push(`/scada/editor/${nid}`)
    else load()
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  } finally {
    creating.value = false
  }
}

function openEditor(row) {
  router.push(`/scada/editor/${row.id}`)
}

function preview(row) {
  window.open(`/view/${row.id}`, '_blank')
}

async function togglePublish(row) {
  const want = row.published ? 0 : 1
  try {
    const r = await post(`/api/page/${row.id}/publish`, { published: want })
    row.published = r.published
    ElMessage.success(want ? '已发布，可在发布入口看到' : '已取消发布')
  } catch (e) {
    ElMessage.error(e.message || '操作失败')
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(
      `删除画面「${row.name}」？${row.published ? '\n它已发布，删除后会从发布目录树消失。' : ''}`,
      '确认删除', { type: 'warning' })
  } catch (e) { return }
  try {
    await del('/api/page/' + row.id)
    ElMessage.success('已删除')
    load()
  } catch (e) {
    ElMessage.error(e.message || '删除失败')
  }
}

function openPublish() {
  window.open('/publish', '_blank')
}

onMounted(() => { load(); loadSites() })
</script>

<style scoped>
.page-list { padding: 4px 6px; }
.hd { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.hd h2 { font-size: 16px; margin: 0; color: #cfe4f7; }
.hd-actions { display: flex; gap: 8px; }
.bar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.bar .sp { flex: 1; }
.hint { color: #6b8cb0; font-size: 12px; }
.hint code { background: #16283c; padding: 1px 5px; border-radius: 3px; color: #9fc3e8; }
.dim { color: #47596b; }
.thumb { width: 92px; height: 52px; object-fit: cover; border-radius: 3px; border: 1px solid #1e3a5f; background: #08111b; }
.thumb.none { display: flex; align-items: center; justify-content: center; color: #47596b; font-size: 11px; }
</style>
