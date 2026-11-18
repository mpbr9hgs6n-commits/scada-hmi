<template>
  <div class="vl">
    <div class="bar">
      <el-button size="small" type="primary" class="vl-newtext" :disabled="!canEdit" @click="openEdit(null, 'text')">
        新建文本列表
      </el-button>
      <el-button size="small" type="success" class="vl-newgraph" :disabled="!canEdit" @click="openEdit(null, 'graph')">
        新建图形列表
      </el-button>
      <el-button size="small" :disabled="!canEdit" @click="pickImport">导入 JSON</el-button>
      <el-button size="small" @click="doExport">导出 JSON</el-button>
      <input ref="fileEl" type="file" accept="application/json,.json" style="display:none" @change="onImport" />
      <span class="sp"></span>
      <span class="hint">文本列表：数值 → 文字（0/1/2 → 停止/运行/故障）；图形列表：数值 → 图片。用法：对象属性 → 动态化 → 文本列表 / 图形列表。</span>
    </div>

    <el-table :data="rows" size="small" class="tb">
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column label="类型" width="96">
        <template #default="{ row }">
          <el-tag size="small" :type="row.kind === 'graph' ? 'success' : 'primary'">
            {{ row.kind === 'graph' ? '图形' : '文本' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="项数" width="70" align="right">
        <template #default="{ row }">{{ (row.items || []).length }}</template>
      </el-table-column>
      <el-table-column label="内容预览" min-width="260">
        <template #default="{ row }">
          <span class="prev">
            <template v-if="row.kind === 'graph'">
              <img v-for="(it, i) in (row.items || []).slice(0, 4)" :key="i" :src="it.image" class="pv-img" :alt="String(it.value)" />
              <span v-for="(it, i) in (row.items || []).slice(0, 4)" :key="'v' + i" class="pv">{{ it.value }}→图 </span>
            </template>
            <template v-else>
              <span v-for="(it, i) in (row.items || []).slice(0, 5)" :key="i" class="pv">
                {{ it.value }}→{{ it.text }}
              </span>
            </template>
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="updated_at" label="更新时间" width="150" />
      <el-table-column label="操作" width="130" fixed="right">
        <template #default="{ row }">
          <el-button v-if="canEdit" link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="canEdit" link type="danger" size="small" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dlg.open" :title="dlg.id ? '编辑列表' : '新建列表'" width="680px" append-to-body>
      <div class="dr">
        <label>名称</label>
        <el-input v-model="dlg.name" size="small" class="dlg-name" placeholder="泵状态" />
        <label class="ty">类型</label>
        <el-select v-model="dlg.kind" size="small" class="dlg-kind" :disabled="!!dlg.id">
          <el-option value="text" label="文本列表" />
          <el-option value="graph" label="图形列表" />
        </el-select>
      </div>

      <table class="it">
        <thead>
          <tr><th style="width:120px">值</th><th>{{ dlg.kind === 'graph' ? '图片地址' : '显示文字' }}</th><th style="width:46px"></th></tr>
        </thead>
        <tbody>
          <tr v-for="(it, i) in dlg.items" :key="i">
            <td><el-input v-model="it.value" size="small" class="it-value" placeholder="0" /></td>
            <td>
              <div class="it-row">
                <el-input v-model="it.text" size="small" class="it-text" :placeholder="dlg.kind === 'graph' ? '/api/upload/xxx.png' : '停止'" />
                <el-button v-if="dlg.kind === 'graph'" size="small" class="it-up" @click="uploadFor(it)">上传</el-button>
                <img v-if="dlg.kind === 'graph' && it.text" :src="it.text" class="it-pv" alt="" />
              </div>
            </td>
            <td><button class="it-x" @click="dlg.items.splice(i, 1)">×</button></td>
          </tr>
        </tbody>
      </table>
      <div class="it-ops">
        <el-button size="small" class="it-add" @click="dlg.items.push({ value: nextVal(), text: '' })">＋ 增加一项</el-button>
      </div>

      <template #footer>
        <el-button @click="dlg.open = false">取消</el-button>
        <el-button type="primary" class="dlg-ok" :loading="dlg.busy" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
// 文本列表 / 图形列表管理（P8，官方 4.7.1 / 4.7.2）
// 列表本身是"数值 → 文字/图片"的字典，画面里通过动态化的 textlist / graphlist 模式引用。
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { get, post, del } from '../utils/request'
import { useUserStore } from '../store'

const store = useUserStore()
const canEdit = computed(() => ['admin', 'operator'].includes(store.user?.role))

const rows = ref([])
const fileEl = ref(null)
const dlg = reactive({ open: false, id: 0, name: '', kind: 'text', items: [], busy: false })

async function load() {
  try {
    const r = await get('/api/valuelists')
    rows.value = r.items || []
  } catch (e) { /* 已提示 */ }
}

function nextVal() {
  const nums = dlg.items.map(x => Number(x.value)).filter(n => isFinite(n))
  return nums.length ? Math.max(...nums) + 1 : 0
}

function openEdit(row, kind) {
  dlg.open = true
  dlg.id = row ? row.id : 0
  dlg.name = row ? row.name : ''
  dlg.kind = row ? row.kind : (kind || 'text')
  dlg.items = row ? JSON.parse(JSON.stringify(row.items || [])).map(x => ({ value: x.value, text: x.text !== undefined ? x.text : x.image }))
    : [{ value: 0, text: '' }]
  dlg.busy = false
}

async function save() {
  if (!dlg.name.trim()) { ElMessage.warning('名称不能为空'); return }
  if (!dlg.items.length) { ElMessage.warning('至少一项'); return }
  const items = []
  for (const it of dlg.items) {
    const v = Number(it.value)
    if (!isFinite(v)) { ElMessage.error('值必须是数字：' + it.value); return }
    if (!String(it.text || '').trim()) { ElMessage.error('第 ' + (items.length + 1) + ' 项内容不能为空'); return }
    items.push(dlg.kind === 'graph' ? { value: v, image: String(it.text).trim() } : { value: v, text: String(it.text) })
  }
  dlg.busy = true
  try {
    await post('/api/valuelist', { id: dlg.id || undefined, name: dlg.name.trim(), kind: dlg.kind, items })
    ElMessage.success('已保存')
    dlg.open = false
    load()
  } catch (e) { /* 已提示 */ } finally { dlg.busy = false }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm('删除列表「' + row.name + '」？画面里引用它的动态化会取不到值。', '删除', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消'
    })
  } catch (e) { return }
  try {
    await del('/api/valuelist/' + row.id)
    ElMessage.success('已删除')
    load()
  } catch (e) { /* 已提示 */ }
}

// 图形列表的图片：走既有 /api/upload（不能收 SVG，避免 XSS）
async function uploadFor(it) {
  const inp = document.createElement('input')
  inp.type = 'file'
  inp.accept = 'image/png,image/jpeg,image/webp,image/gif'
  inp.onchange = async () => {
    const f = (inp.files || [])[0]
    if (!f) return
    try {
      const res = await fetch('/api/upload', {
        method: 'POST',
        headers: {
          Authorization: 'Bearer ' + (localStorage.getItem('token') || ''),
          'Content-Type': f.type
        },
        body: f
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(d.detail || '上传失败')
      it.text = d.url
      ElMessage.success('已上传')
    } catch (e) {
      ElMessage.error(e.message || '上传失败')
    }
  }
  inp.click()
}

function pickImport() { if (fileEl.value) fileEl.value.click() }

async function onImport(e) {
  const f = (e.target.files || [])[0]
  if (!f) return
  let data
  try { data = JSON.parse(await f.text()) } catch (err) { ElMessage.error('不是合法 JSON'); return }
  const lists = Array.isArray(data) ? data : (data.lists || [])
  if (!lists.length) { ElMessage.error('文件里没有 lists'); return }
  try {
    const r = await post('/api/valuelist/import', { lists })
    ElMessage.success('导入完成：新增 ' + r.created + '，更新 ' + r.updated)
    load()
  } catch (err) { /* 已提示 */ }
  if (fileEl.value) fileEl.value.value = ''
}

async function doExport() {
  try {
    const r = await get('/api/valuelist/export')
    const blob = new Blob([JSON.stringify(r, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'valuelists-' + new Date().toISOString().slice(0, 10) + '.json'
    a.click()
    setTimeout(() => URL.revokeObjectURL(a.href), 1000)
  } catch (e) { /* 已提示 */ }
}

onMounted(load)
</script>

<style scoped>
.vl { color: #1f2937; }
.bar { display: flex; align-items: center; gap: 8px; padding: 8px 10px; background: #fff;
  border: 1px solid #e5e7eb; border-radius: 4px; margin-bottom: 10px; flex-wrap: wrap; }
.bar .sp { flex: 0 0 12px; }
.hint { font-size: 11px; color: #64748b; }
.tb { background: #fff; }
.prev { display: inline-flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.pv { font-size: 11px; color: #475569; background: #f1f5f9; border-radius: 3px; padding: 1px 5px; }
.pv-img { width: 26px; height: 26px; object-fit: contain; background: #0b1622; border-radius: 2px; }
.dr { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; font-size: 12px; }
.dr label { color: #475569; }
.dr .ty { margin-left: 10px; }
.dlg-name { width: 200px; }
.dlg-kind { width: 130px; }
.it { width: 100%; border-collapse: collapse; font-size: 12px; }
.it th { text-align: left; color: #64748b; font-weight: 500; border-bottom: 1px solid #e5e7eb; padding: 4px 6px; }
.it td { padding: 3px 6px; }
.it-row { display: flex; align-items: center; gap: 6px; }
.it-text { flex: 1; }
.it-pv { width: 30px; height: 30px; object-fit: contain; background: #0b1622; border-radius: 2px; }
.it-x { width: 22px; height: 22px; border: 1px solid #e5e7eb; background: #fff; color: #ef4444;
  border-radius: 3px; cursor: pointer; }
.it-ops { margin-top: 8px; }
</style>
