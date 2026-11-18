<template>
  <el-container class="layout">
    <el-aside width="200px" class="sidebar">
      <div class="logo"><span class="logo-mark"></span>陆祺智控</div>
      <el-menu :default-active="$route.path" router background-color="#0b1622"
               text-color="#9fc3e8" active-text-color="#ffffff" class="menu">
        <el-menu-item index="/dashboard"><el-icon><Odometer /></el-icon>总览</el-menu-item>
        <el-sub-menu index="site-mgr">
          <template #title><el-icon><Monitor /></el-icon>站点与点位</template>
          <el-menu-item index="/sites">站点管理</el-menu-item>
          <el-menu-item index="/gateways">采集网关</el-menu-item>
          <el-menu-item index="/points">点位管理</el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="alarm-mgr">
          <template #title><el-icon><Bell /></el-icon>报警中心</template>
          <el-menu-item index="/alarms">当前报警</el-menu-item>
          <el-menu-item index="/history">历史曲线</el-menu-item>
        </el-sub-menu>
        <el-menu-item index="/video"><el-icon><VideoCamera /></el-icon>视频管理</el-menu-item>
        <el-sub-menu index="scada-mgr">
          <template #title><el-icon><SetUp /></el-icon>组态管理</template>
          <el-menu-item index="/scada/pages">画面列表</el-menu-item>
          <el-menu-item index="/scada/editor/1">组态画面</el-menu-item>
          <el-menu-item index="/scada/lists">列表管理</el-menu-item>
        </el-sub-menu>
        <el-sub-menu v-if="store.user?.role === 'admin'" index="sys-mgr">
          <template #title><el-icon><Setting /></el-icon>系统管理</template>
          <el-menu-item index="/system/users">用户管理</el-menu-item>
          <el-menu-item index="/system/dbview">数据库查询</el-menu-item>
          <el-menu-item index="/system/retention">数据保留</el-menu-item>
          <el-menu-item index="/system/backup">数据库备份</el-menu-item>
        </el-sub-menu>
        <!-- 关于我们：放在系统管理下方，所有角色都能看（不是 admin 专属） -->
        <el-menu-item index="/about">
          <el-icon><InfoFilled /></el-icon>关于我们
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="navbar">
        <!-- TagsView：多页签，切换不丢筛选条件 -->
        <div class="tags">
          <span v-for="t in tags" :key="t.path" class="tag"
                :class="{ active: t.path === $route.path }" @click="$router.push(t.path)">
            {{ t.title }}
            <span v-if="t.path !== '/dashboard'" class="tag-close" @click.stop="closeTag(t)">×</span>
          </span>
        </div>
        <div class="nav-right">
          <el-dropdown @command="onCmd">
            <span class="uname">{{ store.user?.real_name || store.user?.username }}
              <el-tag size="small" style="margin-left:6px">{{ store.user?.role }}</el-tag>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="changePwd">修改密码</el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main class="main"><router-view /></el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { watch, ref, onMounted } from 'vue'
import { ElMessageBox } from 'element-plus'
import { get } from '../utils/request'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '../store'
import { Odometer, Monitor, Bell, SetUp, Setting, VideoCamera } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const store = useUserStore()

const tags = ref([{ path: '/dashboard', title: '总览' }])
watch(() => route.path, p => {
  if (!p.startsWith('/view') && p !== '/login' && !tags.value.some(t => t.path === p)) {
    tags.value.push({ path: p, title: route.meta.title || p })
  }
}, { immediate: true })

// 数据保留到期提醒（第 03 章）：每次登录检查一次，满足条件弹模态框。
// 不用 toast —— toast 会被忽略，而这条信息关系到"数据即将被清理"。
onMounted(async () => {
  const role = store.user?.role_code || store.user?.role || ''
  if (role !== 'admin') return
  const today = new Date().toISOString().slice(0, 10)
  if (localStorage.getItem('retentionAlertDate') === today) return   // 当天不再弹
  try {
    const r = await get('/api/system/storage')
    if (!r.need_alert) return
    localStorage.setItem('retentionAlertDate', today)
    ElMessageBox.alert(r.message || '数据库即将清理历史数据，请先备份。',
      '⚠ 数据库即将清理历史数据',
      { type: 'warning', confirmButtonText: '去备份', showCancelButton: true,
        cancelButtonText: '知道了', distinguishCancelAndClose: true })
      .then(() => router.push('/system/backup'))
      .catch(() => {})
  } catch (e) { /* 读不到就不弹，不影响正常使用 */ }
})

function closeTag(t) {
  tags.value = tags.value.filter(x => x.path !== t.path)
  if (route.path === t.path) router.push(tags.value[tags.value.length - 1].path)
}
function onCmd(cmd) {
  if (cmd === 'logout') { store.logout(); router.push('/login') }
  if (cmd === 'changePwd') router.push('/change-password')
}
</script>

<style scoped>
.layout { height: 100vh; }
.sidebar { background: #0b1622; }
.logo { color: #fff; font-size: 17px; font-weight: 700; padding: 16px; display: flex; align-items: center; gap: 8px; }
.logo-mark { width: 22px; height: 22px; background: #D01818; border-radius: 4px; display: inline-block; }
.menu { border-right: none; }
.navbar { background: #fff; border-bottom: 1px solid #e5e7eb; display: flex; align-items: center; justify-content: space-between; height: 44px; padding: 0 16px; }
.tags { display: flex; gap: 6px; overflow-x: auto; }
.tag { cursor: pointer; padding: 3px 10px; border-radius: 3px; font-size: 12px; background: #f1f5f9; color: #475569; white-space: nowrap; }
.tag.active { background: #1d4ed8; color: #fff; }
.tag-close { margin-left: 4px; }
.main { background: #f3f5f9; padding: 12px; overflow: auto; }
.uname { cursor: pointer; font-size: 14px; }
</style>
