<template>
  <el-card shadow="never">
    <template #header>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span>用户管理</span>
        <el-button type="primary" @click="openCreate">新增用户</el-button>
      </div>
    </template>

    <el-table :data="users" size="default" v-loading="loading">
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="username" label="用户名" width="130" />
      <el-table-column prop="real_name" label="姓名" width="110" />
      <el-table-column label="角色" width="120">
        <template #default="{ row }">
          <el-tag size="small" :type="row.role === 'admin' ? 'danger' : 'info'">
            {{ roleName(row.role) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.enabled === 1 ? 'success' : 'danger'">
            {{ row.enabled === 1 ? '启用' : '禁用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="密码状态" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="row.must_change_pwd ? 'warning' : 'success'">
            {{ row.must_change_pwd ? '待首次改密' : '已设置' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="last_login" label="最后登录" min-width="160" />
      <el-table-column prop="created_at" label="创建时间" min-width="160" />
      <el-table-column label="操作" width="230" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="primary" @click="openPwd(row)">重置密码</el-button>
          <el-popconfirm v-if="row.id !== 1" title="确认禁用该账号？" @confirm="disable(row)">
            <template #reference>
              <el-button link type="danger" :disabled="row.enabled === 0">禁用</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新增 / 编辑 -->
    <el-dialog v-model="dlg" :title="form.id ? '编辑用户' : '新增用户'" width="480">
      <el-form label-width="90px">
        <el-form-item label="用户名">
          <el-input v-model="form.username" :disabled="!!form.id" placeholder="至少 3 位" />
        </el-form-item>
        <el-form-item label="姓名"><el-input v-model="form.real_name" /></el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width:100%">
            <el-option v-for="r in roles" :key="r.code" :value="r.code" :label="r.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="手机号"><el-input v-model="form.phone" /></el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="form.enabled" :active-value="1" :inactive-value="0"
                     active-text="启用" inactive-text="禁用" />
        </el-form-item>
        <el-form-item v-if="!form.id" label="初始密码">
          <el-input v-model="form.password" type="password" show-password
                    placeholder="至少10位，含大小写字母、数字、特殊字符" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 重置密码 -->
    <el-dialog v-model="pwdDlg" title="重置密码" width="440">
      <el-form label-width="90px">
        <el-form-item label="用户"><b>{{ pwdTarget.username }}</b></el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="pwdValue" type="password" show-password
                    placeholder="至少10位，含大小写字母、数字、特殊字符" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdDlg = false">取消</el-button>
        <el-button type="primary" @click="resetPwd">确定</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { get, post, put, del } from '../utils/request'

const users = ref([])
const roles = ref([
  { code: 'admin', name: '系统管理员' },
  { code: 'operator', name: '值班员' },
  { code: 'site_op', name: '区域运维' },
  { code: 'viewer', name: '只读' }
])
const loading = ref(false), saving = ref(false)
const dlg = ref(false), pwdDlg = ref(false)
const pwdTarget = ref({}), pwdValue = ref('')
const form = reactive({ id: null, username: '', real_name: '', role: 'viewer', phone: '', enabled: 1, password: '' })

function roleName(code) {
  return roles.value.find(r => r.code === code)?.name || code
}

function checkRule(p) {
  if (!p || p.length < 10) return '密码至少 10 位'
  if (!/[A-Z]/.test(p)) return '密码必须包含大写字母'
  if (!/[a-z]/.test(p)) return '密码必须包含小写字母'
  if (!/\d/.test(p)) return '密码必须包含数字'
  if (!/[^A-Za-z0-9]/.test(p)) return '密码必须包含特殊字符'
  return ''
}

async function load() {
  loading.value = true
  try {
    const r = await get('/api/users')
    users.value = r.items
  } catch (e) { users.value = [] }
  finally { loading.value = false }
}

function openCreate() {
  Object.assign(form, { id: null, username: '', real_name: '', role: 'viewer', phone: '', enabled: 1, password: '' })
  dlg.value = true
}
function openEdit(row) {
  Object.assign(form, { id: row.id, username: row.username, real_name: row.real_name,
    role: row.role, phone: row.phone, enabled: row.enabled, password: '' })
  dlg.value = true
}
async function save() {
  if (!form.username) return ElMessage.warning('请输入用户名')
  if (!form.id) {
    const err = checkRule(form.password)
    if (err) return ElMessage.warning(err)
  }
  saving.value = true
  try {
    if (form.id) {
      await put('/api/user/' + form.id, {
        real_name: form.real_name, role: form.role, phone: form.phone, enabled: form.enabled
      })
    } else {
      await post('/api/user', {
        username: form.username, password: form.password, real_name: form.real_name,
        role: form.role, phone: form.phone, enabled: form.enabled
      })
    }
    ElMessage.success('已保存')
    dlg.value = false
    load()
  } catch (e) { /* 已提示 */ }
  finally { saving.value = false }
}

function openPwd(row) { pwdTarget.value = row; pwdValue.value = ''; pwdDlg.value = true }
async function resetPwd() {
  const err = checkRule(pwdValue.value)
  if (err) return ElMessage.warning(err)
  await put(`/api/user/${pwdTarget.value.id}/password`, { new_password: pwdValue.value })
  ElMessage.success('密码已重置，该用户下次登录需修改')
  pwdDlg.value = false
  load()
}

async function disable(row) {
  await del('/api/user/' + row.id)
  ElMessage.success('已禁用')
  load()
}

onMounted(async () => {
  try {
    const r = await get('/api/roles')
    if (r.items?.length) roles.value = r.items
  } catch (e) {}
  load()
})
</script>
