<template>
  <div class="pwd-bg">
    <el-card class="pwd-card">
      <div class="brand">
        <span class="brand-mark"></span>
        <div>
          <div class="brand-cn">修改密码</div>
          <div class="brand-en">首次登录或定期更换，保障平台安全</div>
        </div>
      </div>
      <el-alert v-if="store.mustChangePwd" type="warning" :closable="false" show-icon
                title="首次登录必须修改初始密码后才能使用平台功能" style="margin-bottom:14px" />
      <el-form label-width="90px" @keyup.enter="submit">
        <el-form-item label="原密码">
          <el-input v-model="form.old_password" type="password" show-password placeholder="当前密码" />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="form.new_password" type="password" show-password
                    placeholder="至少10位，含大小写字母、数字、特殊字符" />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="form.confirm" type="password" show-password />
        </el-form-item>
      </el-form>
      <div class="rule">
        密码规则：≥10 位，且同时包含大写字母、小写字母、数字、特殊字符
      </div>
      <div style="margin-top:16px;display:flex;gap:10px">
        <el-button type="primary" :loading="loading" style="flex:1" @click="submit">确认修改</el-button>
        <el-button v-if="!store.mustChangePwd" @click="$router.back()">返回</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '../store'
import { post } from '../utils/request'

const router = useRouter()
const store = useUserStore()
const loading = ref(false)
const form = reactive({ old_password: '', new_password: '', confirm: '' })

function checkRule(p) {
  if (!p || p.length < 10) return '新密码至少 10 位'
  if (!/[A-Z]/.test(p)) return '新密码必须包含大写字母'
  if (!/[a-z]/.test(p)) return '新密码必须包含小写字母'
  if (!/\d/.test(p)) return '新密码必须包含数字'
  if (!/[^A-Za-z0-9]/.test(p)) return '新密码必须包含特殊字符'
  return ''
}

async function submit() {
  const err = checkRule(form.new_password)
  if (err) return ElMessage.warning(err)
  if (form.new_password !== form.confirm) return ElMessage.warning('两次输入的新密码不一致')
  loading.value = true
  try {
    await post('/api/auth/change-pwd', {
      old_password: form.old_password, new_password: form.new_password
    })
    store.clearMustChange()
    ElMessage.success('密码已修改，请使用新密码登录')
    store.logout()
    router.push('/login')
  } catch (e) { /* 已提示 */ }
  finally { loading.value = false }
}
</script>

<style scoped>
.pwd-bg { height: 100vh; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #0b1622 0%, #123252 60%, #0b1622 100%); }
.pwd-card { width: 460px; }
.brand { display: flex; align-items: center; gap: 12px; margin-bottom: 18px; }
.brand-mark { width: 44px; height: 44px; border-radius: 8px; background: #D01818; display: inline-block; }
.brand-cn { font-size: 20px; font-weight: 700; color: #222; }
.brand-en { font-size: 11px; color: #888; letter-spacing: 1px; }
.rule { font-size: 12px; color: #909399; line-height: 1.6; }
</style>
