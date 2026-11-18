<template>
  <el-card shadow="never">
    <!-- 顶部：站点选择 + 搜索 + 三入口 + 批量删 -->
    <div style="display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap;align-items:center">
      <el-select v-model="siteId" placeholder="选择站点" filterable style="width:200px" @change="onSite">
        <el-option v-for="s in sites" :key="s.id" :value="s.id" :label="s.id + ' ' + s.name" />
      </el-select>
      <el-input v-model="kw" placeholder="搜索编码/名称" style="width:200px" clearable @keyup.enter="load" />
      <el-select v-model="fEnabled" placeholder="全部状态" clearable style="width:120px" @change="load">
        <el-option :value="1" label="在采" /><el-option :value="0" label="停用" />
      </el-select>
      <el-button type="primary" @click="load">查询</el-button>
      <el-button v-if="isAdmin && siteId" type="success" @click="openSingle">单个新增</el-button>
      <el-button v-if="isAdmin && siteId" @click="dlgBatch.show = true">批量生成</el-button>
      <el-button v-if="isAdmin && siteId" @click="pickFile">Excel/CSV 导入</el-button>
      <el-button v-if="isAdmin && siteId" @click="downloadTpl">导出</el-button>
      <el-button v-if="isAdmin && siteId && sel.length" type="danger" @click="doBatchDel">
        删除选中（{{ sel.length }}）
      </el-button>
      <input ref="fileInput" type="file" accept=".csv,.xlsx,.txt" style="display:none" @change="onFile" />
    </div>

    <el-table :data="rows" size="default" v-loading="loading" @selection-change="s => sel = s">
      <el-table-column v-if="isAdmin && siteId" type="selection" width="42" />
      <el-table-column prop="site_id" label="站点" width="80" v-if="!siteId" />
      <el-table-column prop="code" label="编码" width="150" />
      <el-table-column prop="name" label="名称" min-width="150" show-overflow-tooltip />
      <el-table-column label="错误提示" min-width="200">
        <template #default="{ row }">
          <span v-if="row.import_error" class="imp-err">{{ row.import_error }}</span>
          <span v-else class="imp-ok">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="addr" label="地址" width="110" />
      <el-table-column prop="dtype" label="类型" width="84" />
      <el-table-column prop="unit" label="单位" width="70" />
      <el-table-column label="值" width="100" align="right">
        <template #default="{ row }">
          <span style="font-family:Consolas,monospace">{{ row.value === null || row.value === undefined ? '--' : row.value }}</span>
        </template>
      </el-table-column>
      <el-table-column label="读写" width="64">
        <template #default="{ row }">{{ row.rw ? '读写' : '只读' }}</template>
      </el-table-column>
      <el-table-column label="历史" width="64">
        <template #default="{ row }">
          <el-tag v-if="row.save_history" size="small" type="success">存</el-tag>
          <el-tag v-else size="small" type="info">不存</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="96">
        <template #default="{ row }">
          <!-- 采集状态要看两维：点位是否启用 + 站点是否在线（用户 2026-11 指出
               "站点不采集时点位还显示在采"是错的） -->
          <el-tag v-if="!row.enabled" type="info" size="small">停用</el-tag>
          <el-tag v-else-if="row.site_online === true" type="success" size="small">在采</el-tag>
          <el-tag v-else-if="row.site_online === false" type="warning" size="small"
                  title="站点心跳离线，网关暂停采集，心跳恢复后自动继续">
            未采
          </el-tag>
          <el-tag v-else type="danger" size="small"
                  title="站点未配心跳，网关永远不采集（需在站点管理里配心跳才会开始采集）">
            未采
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button v-if="isAdmin" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="isAdmin" link type="warning" @click="doToggle(row)">
            {{ row.enabled ? '停用' : '启用' }}
          </el-button>
          <el-popconfirm v-if="isAdmin" title="删除该点位？（组态引用会被拦截，历史数据保留）" @confirm="doDel(row)">
            <template #reference><el-button link type="danger">删除</el-button></template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination style="margin-top:12px" layout="total, sizes, prev, pager, next"
      :total="total" v-model:page-size="size" v-model:current-page="page"
      :page-sizes="[20, 50, 100, 200]" @change="load" />

    <!-- ===== 单个新增 / 编辑 ===== -->
    <el-dialog v-model="dlg.show" :title="dlg.edit ? '编辑点位 ' + dlg.form.code : '单个新增'" width="560" :close-on-click-modal="false">
      <el-form label-width="110px">
        <el-form-item label="编码" required>
          <el-input v-model="dlg.form.code" :disabled="dlg.edit" placeholder="大写字母/数字/下划线，如 PUMP1_RUN" />
          <div v-if="dlg.edit" class="hint">编码不允许改（改名等于断链）；要换编码请删除后重建。</div>
        </el-form-item>
        <el-form-item label="名称"><el-input v-model="dlg.form.name" placeholder="如 1#泵运行状态" /></el-form-item>
        <el-form-item label="地址" required>
          <el-input v-model="dlg.form.addr" :placeholder="addrPlaceholder" />
        </el-form-item>
        <el-form-item label="数据类型">
          <el-select v-model="dlg.form.dtype" style="width:180px">
            <el-option v-for="t in DTYPES" :key="t" :value="t" :label="DTYPE_LABEL[t]" />
          </el-select>
          <el-select v-if="needByteOrder" v-model="dlg.form.byte_order" style="width:120px;margin-left:8px" title="32 位量的字序">
            <el-option v-for="b in ['ABCD', 'CDAB', 'BADC', 'DCBA']" :key="b" :value="b" :label="b" />
          </el-select>
        </el-form-item>
        <el-form-item label="单位"><el-input v-model="dlg.form.unit" style="width:120px" /></el-form-item>
        <el-form-item label="量程下限"><el-input-number v-model="dlg.form.scale_min" :controls="false" style="width:140px" /></el-form-item>
        <el-form-item label="量程上限">
          <el-input-number v-model="dlg.form.scale_max" :controls="false" style="width:140px" />
          <span class="hint" style="margin-left:8px">量程同时用于报警上下限判定</span>
        </el-form-item>
        <el-form-item label="小数位"><el-input-number v-model="dlg.form.decimals" :min="0" :max="6" style="width:120px" /></el-form-item>
        <el-form-item label="死区(%)">
          <el-input-number v-model="dlg.form.deadband" :min="0" :max="100" style="width:120px" />
          <span class="hint" style="margin-left:8px">0=变化即存；按量程百分比</span>
        </el-form-item>
        <el-form-item label="可写"><el-switch v-model="dlg.form.rw" :active-value="1" :inactive-value="0" /></el-form-item>
        <el-form-item label="存历史">
          <el-switch v-model="dlg.form.save_history" :active-value="1" :inactive-value="0" />
          <span class="hint" style="margin-left:8px">开=TDengine 每点位一张子表</span>
        </el-form-item>
        <el-form-item label="采集周期(ms)">
          <el-input-number v-model="dlg.form.poll_ms" :min="0" :step="100" style="width:140px" />
          <span class="hint" style="margin-left:8px">0=用站点默认周期</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.show = false">取消</el-button>
        <el-button type="primary" :loading="dlg.busy" @click="doSaveSingle">{{ dlg.edit ? '保存' : '新增' }}</el-button>
      </template>
    </el-dialog>

    <!-- ===== 批量生成 ===== -->
    <el-dialog v-model="dlgBatch.show" title="批量生成点位（先预览再落库）" width="620" :close-on-click-modal="false">
      <el-form label-width="110px">
        <el-form-item label="起始地址" required>
          <el-input v-model="dlgBatch.start_addr" placeholder="如 VD2000 / D200 / 40001" style="width:200px" />
        </el-form-item>
        <el-form-item label="数量" required>
          <el-input-number v-model="dlgBatch.count" :min="1" :max="2000" style="width:140px" />
        </el-form-item>
        <el-form-item label="地址步长">
          <el-input-number v-model="dlgBatch.step" :min="1" :max="100" style="width:140px" />
          <span class="hint" style="margin-left:8px">32 位量填 2（Modbus）或 4（S7 字节）</span>
        </el-form-item>
        <el-form-item label="编码前缀">
          <el-input v-model="dlgBatch.prefix" style="width:120px" placeholder="P" />
          <span class="hint" style="margin-left:8px">编码 = 前缀 + 地址数字</span>
        </el-form-item>
        <el-form-item label="名称模板">
          <el-input v-model="dlgBatch.name_tpl" style="width:240px" placeholder="如 温度{n}" />
          <span class="hint" style="margin-left:8px">{n}=序号 {a}=地址</span>
        </el-form-item>
        <el-form-item label="数据类型">
          <el-select v-model="dlgBatch.dtype" style="width:180px">
            <el-option v-for="t in DTYPES" :key="t" :value="t" :label="DTYPE_LABEL[t]" />
          </el-select>
        </el-form-item>
        <el-form-item label="单位"><el-input v-model="dlgBatch.unit" style="width:120px" /></el-form-item>
        <el-form-item label="可写"><el-switch v-model="dlgBatch.rw" :active-value="1" :inactive-value="0" /></el-form-item>
        <el-form-item label="存历史"><el-switch v-model="dlgBatch.save_history" :active-value="1" :inactive-value="0" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlgBatch.show = false">取消</el-button>
        <el-button type="primary" :loading="dlgBatch.busy" @click="doGenPreview">生成预览</el-button>
      </template>
    </el-dialog>

    <!-- ===== 导入（CSV/XLSX）预览 ===== -->
    <el-dialog v-model="dlgImp.show" title="导入预览（有问题的行也会导入，问题记入「错误提示」列）" width="980" top="6vh">
      <div v-if="dlgImp.total != null" style="margin-bottom:8px;color:var(--el-text-color-secondary)">
        共解析 {{ dlgImp.total }} 行：合法 {{ (dlgImp.preview || []).length }} 行，
        错误 {{ (dlgImp.bad_rows || []).length }} 行
        <span v-if="(dlgImp.warnings || []).length" style="color:var(--el-color-warning)">；{{ dlgImp.warnings.length }} 条提醒</span>
      </div>
      <el-table ref="impTbl" :data="dlgImp.preview" size="small" max-height="320"
                @selection-change="onImpSel">
        <el-table-column type="selection" width="44" />
        <el-table-column prop="code" label="编码" width="150" />
        <el-table-column prop="name" label="名称" min-width="120" show-overflow-tooltip />
        <el-table-column prop="addr" label="地址" width="100" />
        <el-table-column prop="dtype" label="类型" width="76" />
        <el-table-column prop="unit" label="单位" width="56" />
        <el-table-column label="错误" min-width="240">
          <template #default="{ row }">
            <span v-if="(row._errors || []).length" style="color:#f56c6c">
              {{ (row._errors || []).map(e => e.field + '：' + e.msg).join('；') }}
            </span>
            <span v-else style="color:#c0c4cc">—</span>
          </template>
        </el-table-column>
      </el-table>
      <template v-if="(dlgImp.bad_rows || []).length">
        <div style="margin:10px 0 6px;color:var(--el-color-danger);font-weight:600">错误行（不会导入）</div>
        <el-table :data="dlgImp.bad_rows" size="small" max-height="220"
                  :row-style="{ background: 'var(--el-color-danger-light-9)' }">
          <el-table-column prop="row" label="行号" width="70" />
          <el-table-column prop="code" label="编码" width="130" />
          <el-table-column prop="addr" label="地址" width="110" />
          <el-table-column label="错误" min-width="220">
            <template #default="{ row }">
              <span v-for="(e, i) in row.errors" :key="i" style="margin-right:8px">{{ e.field }}：{{ e.msg }}</span>
            </template>
          </el-table-column>
        </el-table>
      </template>
      <template #footer>
        <span style="float:left;color:var(--el-text-color-secondary);font-size:12px;line-height:32px">
          已勾选 {{ (dlgImp.sel || []).length }} 行 / 共 {{ (dlgImp.preview || []).length }} 行
        </span>
        <el-button @click="dlgImp.show = false">取消</el-button>
        <el-button type="warning" :disabled="!(dlgImp.preview || []).length" :loading="dlgImp.busy"
                   @click="doCommitWithConflict('overwrite', dlgImp)">
          覆盖（勾选的覆盖，其余忽略）
        </el-button>
        <el-button type="info" :disabled="!(dlgImp.preview || []).length" :loading="dlgImp.busy"
                   @click="doCommitWithConflict('ignore', dlgImp)">
          忽略（勾选的忽略，其余覆盖）
        </el-button>
        <el-button type="primary" :disabled="!(dlgImp.preview || []).length" :loading="dlgImp.busy"
                   @click="doCommit(dlgImp.preview, dlgImp.show)">
          原样导入 {{ (dlgImp.preview || []).length }} 行
        </el-button>
      </template>
    </el-dialog>

    <!-- ===== 批量生成预览 ===== -->
    <el-dialog v-model="dlgPrev.show" title="批量生成预览（前 50 行示例）" width="860" top="6vh">
      <el-table :data="dlgPrev.preview.slice(0, 50)" size="small" max-height="380">
        <el-table-column prop="code" label="编码" width="130" />
        <el-table-column prop="name" label="名称" min-width="150" show-overflow-tooltip />
        <el-table-column prop="addr" label="地址" width="110" />
        <el-table-column prop="dtype" label="类型" width="80" />
      </el-table>
      <template v-if="(dlgPrev.bad_rows || []).length">
        <div style="margin:10px 0 6px;color:var(--el-color-danger);font-weight:600">错误行（不会导入）</div>
        <el-table :data="dlgPrev.bad_rows" size="small" max-height="200">
          <el-table-column prop="row" label="行号" width="70" />
          <el-table-column prop="code" label="编码" width="130" />
          <el-table-column label="错误" min-width="260">
            <template #default="{ row }">
              <span v-for="(e, i) in row.errors" :key="i" style="margin-right:8px">{{ e.field }}：{{ e.msg }}</span>
            </template>
          </el-table-column>
        </el-table>
      </template>
      <template #footer>
        <el-button @click="dlgPrev.show = false">取消</el-button>
        <el-button type="primary" :disabled="!(dlgPrev.preview || []).length" :loading="dlgPrev.busy"
                   @click="doCommit(dlgPrev.preview, dlgPrev.show)">
          确认导入 {{ (dlgPrev.preview || []).length }} 行
        </el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup>
// 09 点位管理：三入口（单个/批量生成/Excel-CSV 导入）→ 预览 → /api/point/commit 一条落库路径。
// 服务端校验是唯一权威（提示词 09 第 7 节），前端预览只是给人看的。
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { get, post, put, del } from '../utils/request'
import { useUserStore } from '../store'
import { PROTOCOL_SCHEMA, protoLabel } from '../protocolSchema'

const user = useUserStore()
const isAdmin = computed(() => user.user?.role === 'admin')
const route = useRoute()

// 必须和后端 core/validate.py 的 DTYPE_SET 完全一致（少一个用户就选不到）
const DTYPES = ['bool', 'byte', 'uint16', 'int16', 'uint32', 'int32', 'float32', 'float64', 'string']
const DTYPE_LABEL = {
  bool: '位 Bool', byte: '8位字节', uint16: '16位无符号', int16: '16位有符号',
  uint32: '32位无符号', int32: '32位有符号',
  float32: '32位浮点', float64: '64位浮点',
  string: '字符串',
}

const sites = ref([])
const siteId = ref('')
const rows = ref([])
const sel = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(50)
const kw = ref('')
const fEnabled = ref(null)
const loading = ref(false)

// 当前站点协议（地址占位符、字序需求都跟协议走）
const curSite = computed(() => sites.value.find(s => s.id === siteId.value))
const addrPlaceholder = computed(() =>
  (PROTOCOL_SCHEMA[curSite.value?.plc_protocol] || {}).addrHint || '按站点协议填写')
// 32 位和 64 位都要字节序；string 不需要
const needByteOrder = computed(() =>
  ['uint32', 'int32', 'float32', 'float64'].includes(dlg.form.dtype))

async function loadSites() {
  const r = await get('/api/sites?size=500')
  sites.value = r.items || []
  const fromQuery = route.query.site
  siteId.value = fromQuery && sites.value.find(s => s.id === fromQuery)
    ? fromQuery : (sites.value[0]?.id || '')
  load()
}
function onSite() { page.value = 1; load() }

async function load() {
  loading.value = true
  try {
    const q = new URLSearchParams({ page: page.value, size: size.value, kw: kw.value, with_value: 1 })
    if (siteId.value) q.set('site_id', siteId.value)
    if (fEnabled.value !== null && fEnabled.value !== '') q.set('enabled', fEnabled.value)
    const r = await get('/api/points?' + q)
    rows.value = r.items || []
    total.value = r.total
  } finally { loading.value = false }
}

// ===== 单个新增 / 编辑 =====
const dlg = reactive({ show: false, edit: false, busy: false, form: blankPt() })
function blankPt() {
  // 32 位量的字序跟 PLC 型号绑定，默认值必须按协议给：
  // 三菱 FX（MC 1E 帧）是低字在前 = CDAB；西门子 S7 是高字在前 = ABCD。
  // 全部写死 ABCD 的话，给 MC 站点新建浮点量一建就是错的，采集出来是 1e-14 这种垃圾。
  const proto = (curSite.value && curSite.value.plc_protocol) || ''
  const isMc = proto.startsWith('mc')
  return { code: '', name: '', addr: '', dtype: 'float32',
           byte_order: isMc ? 'CDAB' : 'ABCD',
           unit: '', scale_min: null, scale_max: null, decimals: 2,
           deadband: 0, rw: 0, save_history: 1, poll_ms: 0 }
}
function openSingle() {
  dlg.edit = false
  dlg.form = blankPt()
  dlg.show = true
}
function openEdit(row) {
  dlg.edit = true
  dlg.form = { ...blankPt(), ...row }
  dlg.show = true
}
async function doSaveSingle() {
  const f = dlg.form
  if (!f.code || !f.addr) { ElMessage.warning('编码与地址必填'); return }
  dlg.busy = true
  try {
    if (dlg.edit) {
      const r1 = await put('/api/point/' + f.id, f)
      if (r1 && r1.reload_ok === false) {
        ElMessage.warning('已保存，但网关没重载：' + (r1.reload_err || '网关未响应')
          + '。这个点位的改动暂时不生效')
      } else {
        ElMessage.success('已保存（变更已热加载）')
      }
    } else {
      const r2 = await post('/api/point', { ...f, site_id: siteId.value })
      if (r2 && r2.reload_ok === false) {
        ElMessage.error('点位已存库，但网关没重载：' + (r2.reload_err || '网关未响应')
          + '。现在写这个点位会报「点位不存在」，请先让网关跑起来')
      } else {
        ElMessage.success('已新增并开始采集')
      }
    }
    dlg.show = false
    load()
  } finally { dlg.busy = false }
}

// ===== 批量生成 → 预览 → commit =====
const dlgBatch = reactive({ show: false, busy: false, start_addr: '', count: 20, step: 2,
                            prefix: 'P', name_tpl: '点位{n}', dtype: 'float32',
                            unit: '', rw: 0, save_history: 0 })
const dlgPrev = reactive({ show: false, busy: false, preview: [], bad_rows: [], warnings: [] })
async function doGenPreview() {
  if (!dlgBatch.start_addr || !dlgBatch.count) { ElMessage.warning('起始地址与数量必填'); return }
  dlgBatch.busy = true
  try {
    const r = await post('/api/point/batch', { ...dlgBatch, site_id: siteId.value })
    dlgPrev.preview = r.preview || []
    dlgPrev.bad_rows = r.bad_rows || []
    dlgPrev.warnings = r.warnings || []
    dlgPrev.show = true
  } finally { dlgBatch.busy = false }
}

// ===== 导入 =====
const dlgImp = reactive({ show: false, busy: false, preview: [], bad_rows: [], warnings: [],
                         total: null, sel: [] })
const impTbl = ref(null)
function onImpSel(rows) { dlgImp.sel = rows || [] }

// 「覆盖」/「忽略」：勾选的行按点击的语义处理，未勾选的行按相反语义处理。
//   点「覆盖」→ 勾选=overwrite，其余=ignore
//   点「忽略」→ 勾选=ignore，其余=overwrite
async function doCommitWithConflict(mode, dlg) {
  const selSet = new Set((dlg.sel || []).map(r => r.code))
  const rows = (dlg.preview || []).map(r => {
    const picked = selSet.has(r.code)
    let c
    if (mode === 'overwrite') c = picked ? 'overwrite' : 'ignore'
    else c = picked ? 'ignore' : 'overwrite'
    return Object.assign({}, r, { _conflict: c })
  })
  const nOv = rows.filter(r => r._conflict === 'overwrite').length
  const nIg = rows.length - nOv
  try {
    await ElMessageBox.confirm(
      `将提交 ${rows.length} 行：覆盖 ${nOv} 行、忽略 ${nIg} 行。` +
      `覆盖会更新同编码点位、并删掉占着同地址的旧点位，操作不可撤销。继续？`,
      mode === 'overwrite' ? '覆盖确认' : '忽略确认',
      { type: 'warning', confirmButtonText: '确认提交', cancelButtonText: '取消' })
  } catch (e) { return }
  dlg.busy = true
  try {
    const r = await post('/api/point/commit', { site_id: siteId.value, rows })
    ElMessage.success(`导入完成：新增 ${r.created}，更新 ${r.updated}，跳过 ${r.skipped}`)
    dlg.show = false
    load()
  } catch (e) {
    ElMessage.error(String(e && e.message ? e.message : e))
  } finally { dlg.busy = false }
}
const fileInput = ref(null)
function pickFile() { fileInput.value?.click() }
async function onFile(e) {
  const f = e.target.files[0]
  e.target.value = ''
  if (!f) return
  if (f.size > 5 * 1024 * 1024) { ElMessage.error('文件超过 5MB'); return }
  dlgImp.busy = true
  dlgImp.show = true
  try {
    const fd = new FormData()
    fd.append('file', f)
    const token = localStorage.getItem('token') || ''
    const res = await fetch(`/api/point/import?site_id=${encodeURIComponent(siteId.value)}`,
                            { method: 'POST', body: fd, headers: { Authorization: 'Bearer ' + token } })
    const r = await res.json()
    if (!res.ok) throw new Error(r.detail || '解析失败')
    dlgImp.preview = r.preview || []
    dlgImp.bad_rows = r.bad_rows || []
    dlgImp.warnings = r.warnings || []
    dlgImp.total = r.total
  } catch (err) {
    dlgImp.show = false
    ElMessage.error(String(err.message || err))
  } finally { dlgImp.busy = false }
}

// 导入模板：列名与后端 IMPORT_COLS 一致
// 导出：当前站点的实际点位，7 列中文表头（用户 2026-11 定稿，去掉了存档时间列）
// 列表是分页的（默认 50），导出必须自己翻页拉全量；后端单页上限 2000
async function downloadTpl() {
  if (!siteId.value) { ElMessage.error('请先选站点'); return }
  // 表头用英文（沿用原来的写法，便于和导入端 / IMPORT_COLS 对齐）：
  //   code        点位编码（大写字母/数字/下划线，站内唯一）
  //   site_name   站点名称（只用于人看；导入按 URL 的 site_id，这一列会被忽略）
  //   name        点位名称
  //   addr        寄存器地址
  //   dtype       数据类型
  //   rw          读/写标记（0=只读 1=读写）
  //   save_history 是否存档（0=不保存 1=保存）
  const COLS = [
    ['code', (p) => p.code || ''],
    ['site_name', (p) => (curSite.value || {}).name || siteId.value],
    ['name', (p) => p.name || ''],
    ['addr', (p) => p.addr || ''],
    ['dtype', (p) => p.dtype || ''],
    ['rw', (p) => (Number(p.rw) ? 1 : 0)],
    ['save_history', (p) => (Number(p.save_history) ? 1 : 0)]
  ]
  loading.value = true
  try {
    const all = []
    let pg = 1
    for (;;) {
      const q = new URLSearchParams({ site_id: siteId.value, page: String(pg), size: '2000' })
      const r = await get('/api/points?' + q)
      const items = r.items || []
      all.push(...items)
      if (!items.length || all.length >= (r.total || 0) || pg >= 100) break
      pg += 1
    }
    const esc = (v) => {
      const s = String(v === null || v === undefined ? '' : v)
      return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
    }
    const head = COLS.map((c) => c[0]).join(',')
    const lines2 = all.map((p) => COLS.map((c) => esc(c[1](p))).join(','))
    // 首行中文注释：说明这份导出是台账用途。以 # 开头，导入时后端会跳过
    // （见 points.py 的 _parse_upload）；用户手动删掉这行也不影响导入。
    const NOTE = '# 本文件为点位台账（导出用于查看/交底）。表头为英文列名：code=点位编码, site_name=站点名称, ' + 'name=点位名称, addr=寄存器地址, dtype=数据类型, rw=读/写(0只读1读写), save_history=是否存档(0否1是)。如需导入新增点位，在文件末尾追加行即可（code 填新编码，勿改已有行）'
      + '（大写字母/数字/下划线，站内唯一）；导入接口只支持新增，不会覆盖已有点位。本行以 # 开头，导入时自动忽略。'
    // 首行 # 中文注释 + 7 列英文表头（NOTE 在数组最前面）
    const csv = '\ufeff' + [NOTE, head, ...lines2].join('\n') + '\n'
    const siteName = (curSite.value || {}).name || siteId.value
    const d = new Date()
    const stamp = '' + d.getFullYear() + String(d.getMonth() + 1).padStart(2, '0') + String(d.getDate()).padStart(2, '0')
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
    a.download = '点位导出_' + siteName + '_' + stamp + '.csv'
    a.click()
    URL.revokeObjectURL(a.href)
    ElMessage.success('已导出 ' + all.length + ' 个点位')
  } catch (e) {
    ElMessage.error('导出失败：' + (e && e.message ? e.message : ''))
  } finally { loading.value = false }
}

// ===== 预览确认 → 唯一落库路径（服务端重新校验）=====
async function doCommit(rowsIn, dlgRef) {
  dlgRef.busy = true
  try {
    const r = await post('/api/point/commit', { site_id: siteId.value, rows: rowsIn })
    // 后端已不再因校验错误整批拒绝：有问题的行照样落库，问题写进 import_error 列
    ElMessage.success(`导入完成：新增 ${r.created ?? 0}，更新 ${r.updated ?? 0}，跳过 ${r.skipped ?? 0}`)
    dlgRef.show = false
    dlgBatch.show = false
    load()
  } finally { dlgRef.busy = false }
}

// ===== 停用/启用（≠删除）=====
async function doToggle(row) {
  await post(`/api/point/${row.id}/toggle`)
  ElMessage.success(row.enabled ? '已停用（配置保留，不再采集）' : '已启用')
  load()
}

// ===== 删除（带引用检查）=====
async function doDel(row) {
  try {
    await del('/api/point/' + row.id)
    ElMessage.success('已删除（历史数据保留）')
  } catch (e) {
    // 409：被组态画面引用或有活动报警 —— 后端消息已带画面名，长提示多停一会儿
    ElMessage.warning({ message: String(e.message || e).slice(0, 400), duration: 6000 })
  }
  load()
}

async function doBatchDel() {
  await ElMessageBox.confirm(`确认删除选中的 ${sel.value.length} 个点位？被组态画面引用的会被拦下并单独报告。`, '批量删除', { type: 'warning' })
  const r = await del('/api/point/batch', { body: { ids: sel.value.map(x => x.id) } })
  const lines = [`成功 ${r.deleted.length} 个`]
  if (r.failed?.length) lines.push(`失败 ${r.failed.length} 个：` +
    r.failed.map(f => `${f.code}（${f.reason}）`).join('、'))
  ElMessageBox.alert(lines.join('\n'), '批量删除结果', { type: r.failed?.length ? 'warning' : 'success' })
  load()
}

onMounted(loadSites)
</script>

<style scoped>
.hint { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.5; }

.imp-err { color: #f56c6c; font-size: 12px; }
.imp-ok { color: #c0c4cc; font-size: 12px; }
</style>
