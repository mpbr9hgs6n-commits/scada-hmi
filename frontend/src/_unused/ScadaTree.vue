<template>
  <div class="tree">
    <div class="search">
      <input v-model="kw" class="kw" placeholder="搜索画面名称" spellcheck="false" />
      <span v-if="kw" class="clr" title="清除" @click="kw = ''">×</span>
    </div>

    <div class="body" @scroll="closeMenu">
      <!-- 公共模板 -->
      <div class="row root" @click="toggle('tpl')" @contextmenu.prevent="openMenu($event, { type: 'tplgroup' })">
        <span class="caret" :class="{ open: isOpen('tpl') }">▶</span>
        <span class="dot tpl"></span>
        <span class="nm">公共模板</span>
        <span class="cnt">{{ tplFiltered.length }}</span>
      </div>
      <template v-if="isOpen('tpl')">
        <div v-for="p in tplFiltered" :key="'t' + p.id">
          <div class="row page lv1" :class="{ cur: p.id === currentId }"
               :title="tip(p)" @click="open(p.id)"
               @contextmenu.prevent="openMenu($event, { type: 'page', page: p })">
            <span class="caret" :class="{ open: isOpen('p' + p.id), hide: !kids(p.id).length }"
                  @click.stop="toggle('p' + p.id)">▶</span>
            <span class="dot t"></span>
            <span class="nm">{{ p.name }}</span>
            <span v-if="p.locked" class="lock" title="已锁定">🔒</span>
            <span class="cnt">{{ p.objects }}</span>
          </div>
          <template v-if="isOpen('p' + p.id)">
            <div v-for="c in kids(p.id)" :key="'c' + c.id" class="row page lv2"
                 :class="{ cur: c.id === currentId }" :title="tip(c)"
                 @click="open(c.id)"
                 @contextmenu.prevent="openMenu($event, { type: 'page', page: c })">
              <span class="caret hide">▶</span>
              <span class="dot i"></span>
              <span class="nm">{{ c.name }}</span>
              <span class="tag">{{ c.site_id }}</span>
              <span class="cnt">{{ c.objects }}</span>
            </div>
          </template>
        </div>
        <div v-if="!tplList.length" class="empty">暂无公共模板</div>
      </template>

      <!-- 各站点 -->
      <div class="row root" @click="toggle('sites')" @contextmenu.prevent="openMenu($event, { type: 'sitegroup' })">
        <span class="caret" :class="{ open: isOpen('sites') }">▶</span>
        <span class="dot site"></span>
        <span class="nm">站点画面</span>
        <span class="cnt">{{ sites.length }}</span>
      </div>
      <template v-if="isOpen('sites')">
        <div v-for="s in shownSites" :key="'s' + s.id">
          <div class="row page lv1" @click="toggle('s' + s.id)"
               @contextmenu.prevent="openMenu($event, { type: 'site', site: s })">
            <span class="caret" :class="{ open: isOpen('s' + s.id), hide: !sitePages(s.id).length }">▶</span>
            <span class="dot s"></span>
            <span class="nm">{{ s.name }}</span>
            <span class="tag">{{ s.id }}</span>
            <span class="cnt">{{ sitePages(s.id).length }}</span>
          </div>
          <template v-if="isOpen('s' + s.id)">
            <div v-for="p in sitePages(s.id)" :key="'sp' + p.id">
              <div class="row page lv2" :class="{ cur: p.id === currentId }" :title="tip(p)"
                   @click="open(p.id)"
                   @contextmenu.prevent="openMenu($event, { type: 'page', page: p })">
                <span class="caret" :class="{ open: isOpen('p' + p.id), hide: !kids(p.id).length }"
                      @click.stop="toggle('p' + p.id)">▶</span>
                <span class="dot i"></span>
                <span class="nm">{{ p.name }}</span>
                <span class="cnt">{{ p.objects }}</span>
              </div>
              <template v-if="isOpen('p' + p.id)">
                <div v-for="c in kids(p.id)" :key="'sc' + c.id" class="row page lv3"
                     :class="{ cur: c.id === currentId }" :title="tip(c)"
                     @click="open(c.id)"
                     @contextmenu.prevent="openMenu($event, { type: 'page', page: c })">
                  <span class="caret hide">▶</span>
                  <span class="dot i"></span>
                  <span class="nm">{{ c.name }}</span>
                  <span class="cnt">{{ c.objects }}</span>
                </div>
              </template>
            </div>
            <div v-if="!sitePages(s.id).length" class="empty lv2">无独立画面</div>
          </template>
        </div>
      </template>
    </div>

    <!-- 右键菜单：未满足条件的项置灰而不是隐藏 -->
    <div v-if="menu.show" class="ctx" :style="{ left: menu.x + 'px', top: menu.y + 'px' }">
      <template v-for="mi in menuItems" :key="mi.key">
        <div v-if="mi.sep" class="sep"></div>
        <div v-else class="mi" :class="{ dis: mi.disabled }" @click="runMenu(mi)">
          {{ mi.label }}
          <span v-if="mi.disabled && mi.why" class="why">{{ mi.why }}</span>
        </div>
      </template>
    </div>

    <!-- 新建 / 复制 对话框 -->
    <el-dialog v-model="dlg.show" :title="dlg.title" width="440px" append-to-body>
      <el-form label-width="72px" size="small">
        <el-form-item label="名称">
          <el-input v-model="dlg.name" maxlength="64" show-word-limit placeholder="画面名称" />
        </el-form-item>
        <el-form-item label="类型">
          <el-radio-group v-model="dlg.kind" :disabled="dlg.mode === 'copy'">
            <el-radio label="scada">工艺图</el-radio>
            <el-radio label="screen">大屏</el-radio>
            <el-radio label="template">模板</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="尺寸">
          <el-radio-group v-model="dlg.size" :disabled="dlg.mode === 'copy'">
            <el-radio label="1600x900">1600 × 900</el-radio>
            <el-radio label="1920x1080">1920 × 1080</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="所属站点">
          <el-select v-model="dlg.site" clearable filterable placeholder="模板不选站点"
                     style="width:100%" :disabled="dlg.kind === 'template' || dlg.mode === 'copy'">
            <el-option v-for="s in sites" :key="s.id" :value="s.id" :label="s.id + ' ' + s.name" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="dlg.parent" label="父画面">
          <el-input :model-value="dlg.parent" disabled />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="dlg.show = false">取消</el-button>
        <el-button size="small" type="primary" :loading="dlg.busy" @click="submitDlg">
          {{ dlg.mode === 'copy' ? '复制' : '新建' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 绑定站点 -->
    <el-dialog v-model="bind.show" title="绑定到站点" width="380px" append-to-body>
      <el-select v-model="bind.site" filterable placeholder="选择站点" style="width:100%">
        <el-option v-for="s in sites" :key="s.id" :value="s.id" :label="s.id + ' ' + s.name" />
      </el-select>
      <div class="bind-tip">绑定后该画面成为此站点的实际画面，模板属性会被取消。</div>
      <template #footer>
        <el-button size="small" @click="bind.show = false">取消</el-button>
        <el-button size="small" type="primary" :disabled="!bind.site" :loading="bind.busy"
                   @click="doBind">绑定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
// 画面树（多画面用）。提示词 10 §4.4 开发阶段只有 id=1 一张画面，
// ScadaEditor 已不再挂载本组件；文件保留，后期放开多画面时接回左栏即可。
// 里面带新建/复制/删除/铺站入口，单画面阶段不能让它露出来。
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { get, post, put, del } from '../utils/request'
import { useUserStore } from '../store'

const props = defineProps({
  pages: { type: Array, default: () => [] },
  sites: { type: Array, default: () => [] },
  currentId: { type: [Number, String], default: null }
})
const emit = defineEmits(['open', 'refresh'])
const store = useUserStore()
const isAdmin = computed(() => store.user && store.user.role === 'admin')

const kw = ref('')
const expanded = reactive({ tpl: true, sites: true })   // 组默认展开，站点/画面默认折叠
const isOpen = (k) => !!expanded[k]
function toggle(k) { expanded[k] = !expanded[k] }

const tplList = computed(() => props.pages.filter(p => p.kind === 'template' && !p.site_id))
const kids = (id) => props.pages.filter(p => p.template_id === id)
// 挂在模板下的实例已经显示在模板节点里，这里只列该站独立建的画面，避免同一张画面出现两次
const sitePages = (sid) => props.pages.filter(p => p.site_id === sid && !p.template_id)

const shownSites = computed(() => {
  const k = kw.value.trim()
  if (!k) return props.sites
  // 搜索时只留下有匹配画面的站点
  return props.sites.filter(s => sitePages(s.id).some(p => p.name.includes(k)) ||
    kids(s.id).length && kids(s.id).some(p => p.name.includes(k)))
})

const tplFiltered = computed(() => {
  const k = kw.value.trim()
  if (!k) return tplList.value
  return tplList.value.filter(p => p.name.includes(k) || kids(p.id).some(c => c.name.includes(k)))
})

function tip(p) {
  return `${p.name}\n类型：${p.kind === 'template' ? '模板' : p.kind === 'screen' ? '大屏' : '工艺图'}` +
    `${p.site_id ? '\n站点：' + p.site_id : ''}\n对象：${p.objects}\n更新：${p.updated_at}`
}

function open(id) {
  if (id === props.currentId) return
  emit('open', id)     // 是否真的切换交给编辑器（有未保存改动要先问）
}

// —— 右键菜单 ——
const menu = reactive({ show: false, x: 0, y: 0, node: null })
function openMenu(e, node) {
  menu.node = node
  menu.show = true
  // 防止菜单超出视口
  menu.x = Math.min(e.clientX, window.innerWidth - 190)
  menu.y = Math.min(e.clientY, window.innerHeight - 250)
}
function closeMenu() { menu.show = false }

const menuItems = computed(() => {
  const n = menu.node
  if (!n) return []
  const p = n.page
  if (n.type === 'page') {
    return [
      { key: 'newsub', label: '新建子画面', act: () => newPage({ parent: p }) },
      // P8：组件模板是画一次铺满全部站点的那条路，入口放在这里（官方 4.6）
      { key: 'newfpt', label: '新建组件模板…', act: () => newFpt() },
      { key: 'rename', label: '重命名', act: () => rename(p) },
      { key: 'copy', label: '复制画面', act: () => copyPage(p) },
      { key: 'lock', label: p.locked ? '解除锁定' : '锁定画面', act: () => toggleLock(p) },
      { sep: true, key: 's1' },
      { key: 'astpl', label: '设为模板', disabled: p.kind === 'template', why: p.kind === 'template' ? '已是模板' : '', act: () => setTemplate(p) },
      { key: 'bind', label: '绑定到站点', disabled: !!p.template_id, why: p.template_id ? '子画面随父画面' : '', act: () => openBind(p) },
      { sep: true, key: 's2' },
      { key: 'del', label: '删除画面', act: () => remove(p) }
    ]
  }
  if (n.type === 'site') {
    return [
      { key: 'new', label: '在此站点新建画面', act: () => newPage({ site: n.site }) },
      { key: 'newfpt', label: '新建组件模板…', act: () => newFpt() }
    ]
  }
  return [
    { key: 'new', label: '新建画面', act: () => newPage({}) },
    { key: 'newfpt', label: '新建组件模板…', act: () => newFpt() }
  ]
})

function runMenu(mi) {
  if (mi.disabled) { closeMenu(); return }
  closeMenu()
  mi.act && mi.act()
}

// —— 新建 / 复制 ——
const dlg = reactive({ show: false, mode: 'new', title: '', name: '', kind: 'scada', size: '1600x900', site: '', parent: '', parentId: null, busy: false })

function newPage({ site, parent } = {}) {
  dlg.mode = 'new'
  dlg.title = parent ? '新建子画面' : '新建画面'
  dlg.name = parent ? '子画面' : '新建画面'
  dlg.kind = parent ? (parent.kind === 'screen' ? 'screen' : 'scada') : 'scada'
  dlg.size = '1600x900'
  dlg.site = parent ? (parent.site_id || '') : (site ? site.id : '')
  dlg.parent = parent ? parent.name : ''
  dlg.parentId = parent ? parent.id : null
  dlg.busy = false
  dlg.show = true
}

function copyPage(p) {
  dlg.mode = 'copy'
  dlg.title = '复制画面'
  dlg.name = p.name + '-副本'
  dlg.kind = p.kind
  dlg.size = '1600x900'
  dlg.site = p.site_id || ''
  dlg.parent = ''
  dlg.parentId = null
  dlg.busy = false
  dlg.srcId = p.id
  dlg.show = true
}

async function submitDlg() {
  const name = (dlg.name || '').trim()
  if (!name) { ElMessage.warning('请填写画面名称'); return }
  dlg.busy = true
  try {
    if (dlg.mode === 'copy') {
      const r = await post(`/api/page/${dlg.srcId}/duplicate`, { name })
      ElMessage.success('已复制')
      dlg.show = false
      emit('refresh')
      emit('open', r.id)
      return
    }
    const [w, h] = dlg.size.split('x').map(Number)
    const body = {
      name,
      kind: dlg.kind,
      site_id: dlg.kind === 'template' ? null : (dlg.site || null),
      json: { width: w, height: h, bg: '#0b1622', items: [] }
    }
    if (dlg.parentId) body.template_id = dlg.parentId
    const r = await post('/api/page', body)
    ElMessage.success('已新建')
    dlg.show = false
    emit('refresh')
    emit('open', r.id)
  } finally {
    dlg.busy = false
  }
}

async function rename(p) {
  try {
    const { value } = await ElMessageBox.prompt('新的画面名称', '重命名', {
      inputValue: p.name, inputPattern: /\S/, inputErrorMessage: '名称不能为空',
      confirmButtonText: '确定', cancelButtonText: '取消'
    })
    await put('/api/page/' + p.id, { name: value.trim() })
    ElMessage.success('已重命名')
    emit('refresh')
  } catch (e) { /* 取消 */ }
}

async function toggleLock(p) {
  await put('/api/page/' + p.id, { locked: !p.locked })
  ElMessage.success(p.locked ? '已解锁' : '已锁定')
  emit('refresh')
}

// P8：新建组件模板（默认 200×200，建完直接进模板编辑器；尺寸之后可在编辑器里改）
async function newFpt() {
  let name = ''
  try {
    const r = await ElMessageBox.prompt('组件模板名称（例：泵组模板）', '新建组件模板', {
      inputValue: '组件模板',
      inputPattern: /\S/, inputErrorMessage: '名称不能为空',
      confirmButtonText: '新建', cancelButtonText: '取消'
    })
    name = r.value.trim()
  } catch (e) { return }
  try {
    const r = await post('/api/fpt', {
      name, w: 200, h: 200,
      iface: [],
      json: { width: 200, height: 200, bg: 'transparent', items: [] }
    })
    ElMessage.success('已创建组件模板「' + name + '」，正在打开编辑器')
    emit('refresh')
    location.href = '/scada/fpt/' + r.id
  } catch (e) { /* 已提示 */ }
}

async function setTemplate(p) {
  try {
    await ElMessageBox.confirm(
      `把「${p.name}」设为公共模板？${p.site_id ? '当前绑定的站点 ' + p.site_id + ' 会被解除。' : ''}`,
      '设为模板', { type: 'warning', confirmButtonText: '设为模板', cancelButtonText: '取消' })
  } catch (e) { return }
  await put('/api/page/' + p.id, { kind: 'template' })
  ElMessage.success('已设为模板')
  emit('refresh')
}

const bind = reactive({ show: false, site: '', page: null, busy: false })
function openBind(p) { bind.page = p; bind.site = p.site_id || ''; bind.busy = false; bind.show = true }
async function doBind() {
  bind.busy = true
  try {
    await put('/api/page/' + bind.page.id, { site_id: bind.site })
    ElMessage.success('已绑定到 ' + bind.site)
    bind.show = false
    emit('refresh')
  } finally { bind.busy = false }
}

async function remove(p) {
  try {
    await ElMessageBox.confirm(
      `删除画面「${p.name}」？画面内容和对象会一起删除，不可恢复。`,
      '删除画面', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger' })
  } catch (e) { return }
  try {
    await del('/api/page/' + p.id)
    ElMessage.success('已删除')
    emit('refresh')
  } catch (e) { /* 后端已提示（如仍有子画面） */ }
}

// 点空白关菜单
function onDocClick() { closeMenu() }
onMounted(() => document.addEventListener('click', onDocClick))
onUnmounted(() => document.removeEventListener('click', onDocClick))
</script>

<style scoped>
.tree { display: flex; flex-direction: column; height: 100%; min-height: 0; font-size: 12px; color: #9fc3e8; }
.search { position: relative; padding: 6px 8px; border-bottom: 1px solid #16283d; }
.kw { width: 100%; box-sizing: border-box; background: #0e1f33; border: 1px solid #1e3a5f; color: #dbeafe;
      border-radius: 3px; padding: 4px 20px 4px 7px; font-size: 12px; outline: none; }
.kw:focus { border-color: #1ec8ff; }
.clr { position: absolute; right: 14px; top: 9px; cursor: pointer; color: #5b82a8; font-size: 14px; }
.body { flex: 1; overflow: auto; padding: 4px 0 20px; min-height: 0; }
.row { display: flex; align-items: center; gap: 5px; height: 24px; padding: 0 8px; cursor: pointer; white-space: nowrap; }
.row:hover { background: #12233a; }
.row.cur { background: #123a5c; color: #fff; }
.row.root { font-weight: 600; color: #c3ddf5; }
.caret { font-size: 8px; color: #4a6d92; width: 10px; flex: 0 0 10px; transition: transform .12s; }
.caret.open { transform: rotate(90deg); }
.caret.hide { visibility: hidden; }
.dot { width: 6px; height: 6px; border-radius: 1px; flex: 0 0 6px; background: #3b5c82; }
.dot.tpl { background: #f59e0b; }
.dot.t { background: #d97706; }
.dot.site { background: #2563eb; }
.dot.s { background: #3b82f6; }
.dot.i { background: #475569; }
.nm { overflow: hidden; text-overflow: ellipsis; }
.lv1 { padding-left: 16px; }
.lv2 { padding-left: 30px; }
.lv3 { padding-left: 44px; }
.cnt { margin-left: auto; color: #4a6d92; font-size: 10px; padding-left: 6px; }
.tag { color: #5b82a8; font-size: 10px; border: 1px solid #1e3a5f; border-radius: 2px; padding: 0 3px; }
.lock { font-size: 10px; }
.empty { color: #3b5c82; padding: 4px 16px; font-size: 11px; }
.empty.lv2 { padding-left: 30px; }
.ctx { position: fixed; z-index: 3000; min-width: 170px; background: #0f1f33; border: 1px solid #1e3a5f;
       border-radius: 4px; box-shadow: 0 6px 20px rgba(0,0,0,.5); padding: 4px 0; }
.mi { padding: 6px 12px; cursor: pointer; display: flex; gap: 6px; align-items: center; }
.mi:hover { background: #16324f; }
.mi.dis { color: #3b5c82; cursor: not-allowed; }
.mi.dis:hover { background: transparent; }
.why { margin-left: auto; font-size: 10px; color: #3b5c82; }
.sep { height: 1px; background: #16283d; margin: 4px 0; }
.bind-tip { margin-top: 8px; color: #5b82a8; font-size: 11px; line-height: 1.6; }
</style>
