import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from './store'

const routes = [
  { path: '/login', component: () => import('./views/Login.vue') },
  { path: '/change-password', name: 'changePwd', component: () => import('./views/ChangePassword.vue') },
  {
    path: '/',
    component: () => import('./views/Layout.vue'),
    redirect: '/dashboard',
    children: [
      { path: 'dashboard', name: 'dashboard', component: () => import('./views/Dashboard.vue'), meta: { title: '总览' } },
      { path: 'sites', name: 'sites', component: () => import('./views/SiteList.vue'), meta: { title: '站点管理' } },
      { path: 'gateways', name: 'gateways', component: () => import('./views/GatewayList.vue'), meta: { title: '采集网关' } },
      { path: 'site/:id', name: 'siteDetail', component: () => import('./views/SiteDetail.vue'), meta: { title: '站点详情' } },
      // 09 站点与点位管理：一站点一台 PLC，没有设备层；点位三入口都在这页
      { path: 'points', name: 'points', component: () => import('./views/PointList.vue'), meta: { title: '点位管理' } },
      // 提示词 10 §4.4：开发阶段只有一张固定画面（id=1）。
      // 画面列表页、新建/复制/删除画面一律不做，组态菜单直接进编辑器。
      { path: 'scada', redirect: '/scada/pages' },
      // 14 号：画面列表（组态管理首页）
      { path: 'scada/pages', name: 'scadaPages',
        component: () => import('./views/PageList.vue'), meta: { title: '画面列表' } },
      // P8：viewer 只读 —— 编辑器路由直接挡在门口（任务书验收第 10 条）
      { path: 'scada/editor/:id', name: 'scadaEditor', component: () => import('./views/ScadaEditor.vue'),
        meta: { title: '组态画面', roles: ['admin', 'operator'] } },
      // P8：文本列表 / 图形列表管理（官方 4.7）
      { path: 'scada/lists', name: 'scadaLists', component: () => import('./views/ValueList.vue'), meta: { title: '列表管理' } },
      { path: 'alarms', name: 'alarms', component: () => import('./views/Alarms.vue'), meta: { title: '当前报警' } },
      { path: 'video', name: 'video', component: () => import('./views/VideoManage.vue'), meta: { title: '视频管理' } },
      { path: 'history', name: 'history', component: () => import('./views/History.vue'), meta: { title: '历史曲线' } },
      // 第 04 章：数据库只读查询 + 备份（仅 admin）
      { path: 'system/dbview', name: 'dbview',
        component: () => import('./views/DbView.vue'),
        meta: { title: '数据库查询', roles: ['admin'] } },
      { path: 'system/retention', name: 'retention',
        component: () => import('./views/Retention.vue'),
        meta: { title: '数据保留', roles: ['admin'] } },
      { path: 'system/backup', name: 'backup',
        component: () => import('./views/Backup.vue'),
        meta: { title: '数据库备份', roles: ['admin'] } },
      { path: 'system/users', name: 'users', component: () => import('./views/Users.vue'), meta: { title: '用户管理', roles: ['admin'] } },
      // 关于我们：系统管理下方，所有角色可见
      { path: 'about', name: 'about', component: () => import('./views/About.vue'), meta: { title: '关于我们' } }
    ]
  },
  // 组态只读页（独立于后台布局）
  { path: '/view/:id', name: 'view', component: () => import('./views/ViewPage.vue') },
  // 14 号：发布入口（带目录树），免登录，和 /view/:id 一样给 Kiosk 电视用
  { path: '/publish', name: 'publish', component: () => import('./views/PublishView.vue'),
    meta: { title: '监控画面' } },
  { path: '/publish/:id', name: 'publishPage', component: () => import('./views/PublishView.vue'),
    meta: { title: '监控画面' } }
]

const router = createRouter({ history: createWebHistory(), routes })

// 懒加载 chunk 丢失（部署后旧页面去加载已被删除的旧 hash 文件）时，
// 路由会静默中止，表现就是"点了没反应"。这里兜底：整页重载一次拿最新 index.html。
const CHUNK_ERR = /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|Loading chunk .* failed/i

router.onError((err, to) => {
  const msg = (err && err.message) || ''
  if (!CHUNK_ERR.test(msg)) return
  const key = 'chunk_reload_' + (to && to.fullPath ? to.fullPath : location.pathname)
  if (!sessionStorage.getItem(key)) {
    sessionStorage.setItem(key, '1')
    location.href = (to && to.fullPath) ? to.fullPath : location.href
  } else {
    sessionStorage.removeItem(key)
    ElMessage.error('页面资源已更新，请按 Ctrl+F5 强制刷新')
  }
})

const PUBLIC = ['/login', '/change-password']

router.beforeEach((to, from, next) => {
  const store = useUserStore()
  const isView = to.path.startsWith('/view/') || to.path.startsWith('/publish')
  if (PUBLIC.includes(to.path) || isView) {
    // 已登录却还去登录页 → 回总览
    if (to.path === '/login' && store.token) return next('/dashboard')
    return next()
  }
  if (!store.token) return next('/login')
  // 首次登录未改密：除改密页外全部拦回
  if (store.mustChangePwd && to.path !== '/change-password') return next('/change-password')
  // 页面级角色限制
  const roles = to.meta && to.meta.roles
  if (roles && !roles.includes(store.user?.role)) {
    // 不能说"点了没反应"：明确告诉用户是被权限挡下的
    ElMessage.warning('无权限访问「' + (to.meta.title || to.path) + '」：当前角色 ' + (store.user?.role || '未登录') + ' 只能查看')
    // 不能回 /scada：它现在重定向到需要 operator 的编辑器，viewer 会被来回踢成死循环
    return next('/dashboard')
  }
  next()
})

export default router
