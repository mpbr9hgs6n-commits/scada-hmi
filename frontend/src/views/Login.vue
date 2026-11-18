<template>
  <div class="login-bg">
    <el-card class="login-card">
      <div class="brand">
        <span class="brand-mark"></span>
        <div>
          <div class="brand-cn">陆祺智控</div>
          <div class="brand-en">luche · 集中监控平台</div>
        </div>
      </div>
      <el-form @keyup.enter="doLogin">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名" size="large" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" placeholder="密码" size="large" show-password />
        </el-form-item>
        <el-button type="primary" size="large" style="width:100%" :loading="loading" @click="doLogin">登 录</el-button>
      </el-form>
      <div class="tip">初始账号 admin / Admin@2026，首次登录需修改密码</div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '../store'
import { api } from '../utils/request'

const router = useRouter()
const store = useUserStore()
const form = reactive({ username: '', password: '' })
const loading = ref(false)

async function go(path) {
  try {
    await router.push(path)
    // 导航被中止（例如懒加载 chunk 404）时，URL 不会变，这里用硬跳兜底
    if (location.pathname !== path) location.href = path
  } catch (e) {
    location.href = path
  }
}

async function doLogin() {
  if (!form.username || !form.password) return ElMessage.warning('请输入用户名和密码')
  loading.value = true
  try {
    const r = await api('/api/auth/login', { method: 'POST', body: form })
    store.setLogin(r.token, r.user, r.must_change_pwd)
    if (r.must_change_pwd) {
      ElMessage.warning('首次登录，请先修改初始密码')
      await go('/change-password')
    } else {
      ElMessage.success('登录成功')
      await go('/dashboard')
    }
  } catch (e) { /* request.js 已提示 */ }
  finally { loading.value = false }
}
</script>

<style scoped>
.login-bg { height: 100vh; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #0b1622 0%, #123252 60%, #0b1622 100%); }
.login-card { width: 380px; }
.brand { display: flex; align-items: center; gap: 12px; margin-bottom: 24px; }
.brand-mark { width: 44px; height: 44px; border-radius: 8px; background: #D01818;
  display: inline-block; }
.brand-cn { font-size: 22px; font-weight: 700; color: #222; }
.brand-en { font-size: 11px; color: #888; letter-spacing: 1px; }
.tip { margin-top: 14px; font-size: 12px; color: #999; text-align: center; }
</style>
