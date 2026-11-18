<template>
  <el-card shadow="never">
    <!-- 顶部：关键字 + 协议筛选 + 新建 -->
    <div style="display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap">
      <el-input v-model="kw" placeholder="搜索编号/名称/PLC地址" style="width:220px" clearable @keyup.enter="load" />
      <el-select v-model="fproto" placeholder="全部协议" clearable style="width:150px" @change="load">
        <el-option v-for="p in ALL_PROTOCOLS" :key="p.v" :value="p.v" :label="p.label" />
      </el-select>
      <el-button type="primary" @click="load">查询</el-button>
      <el-button v-if="canEdit" type="success" @click="openForm()">新建站点</el-button>
      <el-button v-if="user.user?.role === 'admin'" type="danger" :disabled="!sel.length" @click="doBatchDelete">
        批量删除{{ sel.length ? `（${sel.length}）` : '' }}
      </el-button>
    </div>

    <el-table :data="rows" size="default" v-loading="loading" @selection-change="onSel">
      <el-table-column v-if="user.user?.role === 'admin'" type="selection" width="42" />
      <el-table-column prop="id" label="编号" width="80" />
      <el-table-column label="所属网关" width="100">
        <template #default="{ row }">
          <span :style="{ color: row.gateway_id ? 'inherit' : 'var(--el-color-danger)' }">
            {{ row.gateway_id || '未指定' }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="name" label="站点名称" min-width="140" show-overflow-tooltip />
      <el-table-column label="品牌/系列" width="130">
        <template #default="{ row }">{{ brandLabel(row.brand) }} {{ row.series || '' }}</template>
      </el-table-column>
      <el-table-column label="协议" width="110">
        <template #default="{ row }">{{ protoLabel(row.plc_protocol) }}</template>
      </el-table-column>
      <el-table-column label="PLC 地址" width="170">
        <template #default="{ row }">{{ row.plc_ip }}:{{ row.plc_port }}</template>
      </el-table-column>
      <el-table-column label="点位" width="70">
        <template #default="{ row }">{{ row.point_count ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="采集状态" width="92">
        <template #default="{ row }">
          <el-tag :type="row.online === true ? 'success' : row.online === false ? 'info' : 'warning'"
                  size="small">{{ { true: '在线', false: '离线' }[row.online] || '未采集' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="成功率" width="84">
        <template #default="{ row }">
          <span :style="{ color: row.succ_rate != null && row.succ_rate < 90 ? '#e6a23c' : '' }">
            {{ row.succ_rate != null ? row.succ_rate + '%' : '—' }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="last_err" label="最后错误" min-width="150" show-overflow-tooltip>
        <template #default="{ row }">{{ row.last_err || '—' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="300" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="doTest(row)">测试连接</el-button>
          <el-button link type="primary" @click="$router.push('/points?site=' + row.id)">点位管理</el-button>
          <el-button link type="primary" @click="$router.push('/site/' + row.id)">监控</el-button>
          <el-button v-if="canEdit" link type="primary" @click="openForm(row)">编辑</el-button>
          <el-popconfirm v-if="user.user?.role === 'admin'" title="确认删除该站点？（含点位需再次确认，历史数据保留）" @confirm="doDelete(row)">
            <template #reference><el-button link type="danger">删除</el-button></template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination style="margin-top:12px" layout="total, sizes, prev, pager, next"
      :total="total" v-model:page-size="size" v-model:current-page="page"
      :page-sizes="[20, 50, 100]" @change="load" />

    <!-- 测试连接：参数可编辑，测通了可以存回本站点（提示词 10 第 1 节） -->
    <el-dialog v-model="tst.show" :title="'测试连接 — ' + tst.name" width="560" :close-on-click-modal="false">
      <el-form label-width="90px" size="default">
        <el-form-item label="协议">
          <el-select v-model="tst.form.protocol" style="width:100%" @change="onTestProto">
            <el-option v-for="p in ALL_PROTOCOLS" :key="p.v" :value="p.v" :label="p.label" />
          </el-select>
        </el-form-item>
        <el-form-item label="IP">
          <el-input v-model="tst.form.ip" placeholder="192.168.1.10" />
        </el-form-item>
        <el-form-item label="端口">
          <el-input-number v-model="tst.form.port" :min="1" :max="65535" />
          <span style="margin-left:8px;font-size:12px;color:var(--el-text-color-secondary)">默认 {{ portOf(tst.form.protocol) }}</span>
        </el-form-item>
        <el-form-item label="从站号">
          <el-input-number v-model="tst.form.slave_id" :min="1" :max="247" />

          <span style="margin-left:6px;font-size:12px">ms</span>
        </el-form-item>
        <el-form-item label="测试地址">
          <el-input v-model="tst.addr" placeholder="选填，留空用本站第一个点位" style="width:220px" />
          <el-select v-model="tst.dtype" style="width:130px;margin-left:8px">
            <el-option v-for="t in DTYPES" :key="t" :value="t"
                       :label="{ bool: '位 Bool', uint16: '16位无符号', int16: '16位有符号', uint32: '32位无符号', int32: '32位有符号', float32: '32位浮点' }[t]" />
          </el-select>
        </el-form-item>
      </el-form>

      <div v-if="tst.loading" style="padding:6px 0;color:var(--el-text-color-secondary)">正在连接…</div>
      <div v-else-if="tst.tested">
        <div v-if="tst.ok" style="color:var(--el-color-success);font-size:15px">
          ✓ 连接成功，耗时 {{ tst.latency }}ms，读到 {{ tst.addrUsed || '默认地址' }} = {{ tst.value }}
        </div>
        <div v-else style="color:var(--el-color-danger);font-size:15px">✗ {{ tst.error }}</div>
        <div v-if="!tst.ok" style="margin-top:6px;color:var(--el-text-color-secondary)">
          排查建议：{{ tst.hint || '检查 IP/端口/协议/从站号' }}
        </div>
        <div v-if="tst.ok && tst.dirty" style="margin-top:6px;color:var(--el-color-warning)">
          参数已改动，请重新测试后才能保存
        </div>
      </div>

      <template #footer>
        <el-button @click="tst.show = false">取消</el-button>
        <el-button type="primary" :loading="tst.loading" @click="runTest">测试</el-button>
        <el-button type="success" :disabled="!tst.ok || tst.dirty" :loading="tst.applying"
                   @click="applyTest">保存到本站点</el-button>
      </template>
    </el-dialog>

    <!-- 站点表单：一站点一台 PLC，四段抽屉（从设备表单吸收而来） -->
    <el-drawer v-model="form.show" :title="form.editing ? '编辑站点 ' + form.data.id : '新建站点'" size="640px">
      <el-tabs v-model="form.tab">
        <el-tab-pane label="基本信息" name="base">
          <el-form label-width="110px">
            <el-form-item label="站点编号" required>
              <el-input v-model="form.data.id" :disabled="form.editing" placeholder="如 S005（保存后不可改）" />
            </el-form-item>
            <el-form-item label="站点名称" required>
              <el-input v-model="form.data.name" placeholder="如 1#泵站" />
            </el-form-item>
            <el-form-item label="所属网关" required>
              <el-select v-model="form.data.gateway_id" filterable style="width:240px"
                         placeholder="必须选一个网关">
                <el-option v-for="g in gateways" :key="g.id" :value="g.id"
                           :label="g.id + ' ' + g.name + '（' + g.sites + '/' + g.max_sites + ' 台）'
                                    + (g.online ? '' : '  ⚠ 未运行')"
                           :disabled="g.sites >= g.max_sites && form.data.gateway_id !== g.id" />
              </el-select>
              <span v-if="curGwOffline" style="margin-left:10px;font-size:12px;color:var(--el-color-danger)">
                该网关没有运行：保存后这个站点不会被采集，写点位会报「点位不存在」
              </span>
              <span v-else style="margin-left:10px;font-size:12px;color:var(--el-text-color-secondary)">
                一个网关最多 20 台 PLC，不指定不能保存
              </span>
            </el-form-item>
            <el-form-item label="品牌" required>
              <el-select v-model="form.data.brand" style="width:100%" @change="onBrand">
                <el-option v-for="b in BRANDS" :key="b.v" :value="b.v" :label="b.label" />
              </el-select>
            </el-form-item>
            <el-form-item label="系列型号">
              <el-select v-model="form.data.series" style="width:100%" allow-create filterable @change="onSeries">
                <el-option v-for="s in seriesOf(form.data.brand)" :key="s" :value="s" :label="s" />
              </el-select>
            </el-form-item>
            <el-form-item label="地址"><el-input v-model="form.data.address" placeholder="安装地址" /></el-form-item>
            <el-form-item label="安装位置"><el-input v-model="form.data.location" placeholder="机柜号/配电室" /></el-form-item>
            <el-form-item label="备注"><el-input v-model="form.data.remark" /></el-form-item>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="通讯参数" name="comm">
          <el-form label-width="110px">
            <el-form-item label="协议" required>
              <el-select v-model="form.data.plc_protocol" style="width:100%" @change="onProtocol">
                <el-option v-for="p in protoOptions" :key="p.v" :value="p.v" :label="p.label" />
              </el-select>
            </el-form-item>
            <el-form-item label="通讯方式">
              <el-radio-group v-model="form.data.comm_mode">
                <el-radio value="tcp">TCP</el-radio>
                <el-radio value="udp">UDP</el-radio>
                <el-radio value="serial">串口</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="PLC IP" required>
              <el-input v-model="form.data.plc_ip" placeholder="192.168.1.10" />
              <div class="form-hint">一个站点就是一台 PLC；同一台 PLC 不允许配到两个站点。</div>
            </el-form-item>
            <el-form-item label="端口">
              <el-input-number v-model="form.data.plc_port" :min="1" :max="65535" />
              <span style="margin-left:8px;color:var(--el-text-color-secondary);font-size:12px">{{ portHint }}</span>
            </el-form-item>
            <el-form-item v-if="form.data.plc_protocol === 'modbus_tcp' || form.data.plc_protocol === 'modbus_rtu'"
                          label="从站号">
              <el-input-number v-model="form.data.slave_id" :min="1" :max="247" />
            </el-form-item>
            <template v-if="form.data.plc_protocol === 's7'">
              <el-form-item label="机架号">
                <el-input-number v-model="form.data.rack" :min="0" :max="7" @change="onTsapInput" />
              </el-form-item>
              <el-form-item label="槽号">
                <el-input-number v-model="form.data.slot" :min="0" :max="31" @change="onTsapInput" />
                <span v-if="seriesRef" style="margin-left:10px;font-size:12px;color:var(--el-color-warning)">
                  {{ seriesRef }}（未确证，请按手册填）
                </span>
              </el-form-item>
            </template>
            <el-form-item label="判离线阈值">
              <el-input-number v-model="form.data.offline_threshold" :min="1" :max="20" />
              <span style="margin-left:8px;font-size:12px;color:var(--el-text-color-secondary)">连续失败几次判离线，默认 3</span>
            </el-form-item>
            <el-divider content-position="left">在线判定（心跳，二选一）</el-divider>
            <el-form-item label="心跳方式">
              <el-select v-model="form.data.heartbeat_mode" style="width:200px">
                <el-option value="none" label="不判定（看采集结果）" />
                <el-option value="modbus_echo" label="Modbus 回环心跳" />
                <el-option value="ping" label="ping 网络探测" />
              </el-select>
              <div v-if="form.data.heartbeat_mode === 'modbus_echo'" class="form-hint">
                心跳是独立通道，与采集协议无关：采集可以走 S7/MC，心跳单独走 Modbus TCP。
                PLC 梯形图必须有「MOV 40001 → 40002」，否则读回值永不相等、一直判离线。
                <span v-if="form.data.plc_protocol !== 'modbus_tcp'"
                      style="color:var(--el-color-warning)">该站不是 Modbus 采集，请务必填下面的写入/读取端口。</span>
              </div>
            </el-form-item>
            <template v-if="form.data.heartbeat_mode === 'modbus_echo'">
              <el-form-item label="写入地址">
                <el-input-number v-model="form.data.hb_write_addr" :min="0" :max="65535" />
                <span style="margin-left:8px;font-size:12px">0 = 40001</span>
              </el-form-item>
              <el-form-item label="读回地址">
                <el-input-number v-model="form.data.hb_read_addr" :min="0" :max="65535" />
                <span style="margin-left:8px;font-size:12px">1 = 40002</span>
              </el-form-item>
              <el-form-item label="写入端口">
                <el-input-number v-model="form.data.hb_write_port" :min="1" :max="65535"
                                 :value-on-clear="null" controls-position="right"
                                 placeholder="留空=站点端口" style="width:170px" />
                <span style="margin-left:8px;font-size:12px">留空用站点 PLC 端口</span>
              </el-form-item>
              <el-form-item label="读取端口">
                <el-input-number v-model="form.data.hb_read_port" :min="1" :max="65535"
                                 :value-on-clear="null" controls-position="right"
                                 placeholder="留空=站点端口" style="width:170px" />
                <span style="margin-left:8px;font-size:12px">可与写入不同，如 506 写 / 507 读</span>
              </el-form-item>
              <el-form-item label="心跳间隔(秒)">
                <el-input-number v-model="form.data.hb_interval_s" :min="0" :max="3600" />
                <span style="margin-left:8px;font-size:12px">0 = 每轮采集都跑；N = 每 N 秒写读一次</span>
              </el-form-item>
              <el-form-item label="循环上限">
                <el-input-number v-model="form.data.hb_max_value" :min="1" :max="2000" />
                <span style="margin-left:8px;font-size:12px">写入值 1~N 循环，到 N 后回到 1，默认 2000</span>
              </el-form-item>
            </template>
            <el-form-item v-if="form.data.heartbeat_mode !== 'none'" label="判定周期数">
              <el-input-number v-model="form.data.hb_cycles" :min="1" :max="10" />
              <span style="margin-left:8px;font-size:12px">连续失败几次判离线，默认 3</span>
            </el-form-item>
            <el-form-item v-if="form.data.heartbeat_mode === 'ping'" label="ping 间隔(ms)">
              <el-input-number v-model="form.data.ping_interval_ms" :min="1000" :max="60000" :step="1000" />
            </el-form-item>
            <el-form-item label="测试连接">
              <div style="width:100%">
                <div style="display:flex;gap:8px;align-items:center">
                  <el-input v-model="testAddr" placeholder="测试地址（留空用默认）" style="width:220px"
                            :class="{ 'addr-bad': addrState === 'bad', 'addr-ok': addrState === 'ok' }" />
                  <el-select v-model="testDtype" style="width:130px" title="按该数据类型读取并解码返回值">
                    <el-option v-for="t in DTYPES" :key="t" :value="t"
                               :label="{ bool: '位 Bool', uint16: '16位无符号', int16: '16位有符号', uint32: '32位无符号', int32: '32位有符号', float32: '32位浮点' }[t]" />
                  </el-select>
                  <el-button type="primary" :loading="form.testing" @click="doTestForm">测试连接</el-button>
                </div>
                <el-tooltip v-if="addrHint" :content="'合法示例：' + addrHint" placement="top">
                  <div style="margin-top:4px;font-size:12px" :style="{ color: addrColor }">{{ addrMsg }}</div>
                </el-tooltip>
              </div>
            </el-form-item>
            <el-form-item label="启用采集">
              <el-switch v-model="form.data.enabled" :active-value="1" :inactive-value="0" />
            </el-form-item>
          </el-form>
          <template v-if="form.data.comm_mode === 'serial'">
            <el-divider content-position="left">串口参数</el-divider>
            <el-form label-width="110px" style="max-width:420px">
              <el-form-item label="串口号"><el-input v-model="sp.port" placeholder="COM1 / /dev/ttyS0" /></el-form-item>
              <el-form-item label="波特率">
                <el-select v-model="sp.baud">
                  <el-option v-for="b in [9600, 19200, 38400, 57600, 115200]" :key="b" :value="b" :label="String(b)" />
                </el-select>
              </el-form-item>
              <el-form-item label="数据位"><el-input-number v-model="sp.dataBits" :min="7" :max="8" /></el-form-item>
              <el-form-item label="停止位">
                <el-select v-model="sp.stopBits"><el-option :value="1" label="1" /><el-option :value="2" label="2" /></el-select>
              </el-form-item>
              <el-form-item label="校验">
                <el-select v-model="sp.parity">
                  <el-option value="none" label="无 N" /><el-option value="even" label="偶 E" /><el-option value="odd" label="奇 O" />
                </el-select>
              </el-form-item>
            </el-form>
          </template>
        </el-tab-pane>

        <el-tab-pane :label="'协议参数（' + protoLabel(form.data.plc_protocol) + '）'" name="proto">
          <template v-if="protoParams.length">
            <el-form label-width="150px" style="max-width:480px">
              <template v-for="f in protoParams" :key="f.k">
                <el-form-item :label="f.label">
                  <el-select v-if="f.type === 'select'" v-model="form.data.proto_params[f.k]" style="width:100%"
                             @change="f.k === 'conn_type' ? onTsapInput() : undefined">
                    <el-option v-for="o in f.opts" :key="o.v ?? o" :value="o.v ?? o" :label="o.label ?? String(o)" />
                  </el-select>
                  <!-- combo = 下拉建议 + 可手输。TSAP / PDU 用它：既能按公式自动补，也允许现场覆盖 -->
                  <el-select v-else-if="f.type === 'combo'" v-model="form.data.proto_params[f.k]"
                             filterable allow-create default-first-option clearable
                             style="width:100%" :placeholder="f.ph || '选择或直接输入'"
                             @change="f.k === 'conn_type' ? onTsapInput() : undefined">
                    <el-option v-for="o in optsOf(f)" :key="String(o)" :value="o" :label="String(o)" />
                  </el-select>
                  <div v-else-if="f.type === 'switch'" style="display:flex;align-items:center;gap:8px">
                    <el-switch v-model="form.data.proto_params[f.k]" />
                    <span style="font-size:12px;color:var(--el-text-color-secondary)">开 = 优化块访问</span>
                  </div>
                  <el-input-number v-else-if="f.type === 'number'" v-model="form.data.proto_params[f.k]" style="width:180px" />
                  <el-input v-else v-model="form.data.proto_params[f.k]" :placeholder="f.ph || ''" />
                </el-form-item>
                <div v-if="f.tip" style="margin:-14px 0 10px 150px;font-size:12px;color:var(--el-color-warning);max-width:380px">
                  ⚠ {{ f.tip }}
                </div>
              </template>
            </el-form>
          </template>
          <el-empty v-else description="该协议没有专属参数" :image-size="60" />
          <el-divider content-position="left">高级</el-divider>
          <el-form label-width="150px" style="max-width:480px">
            <el-form-item label="合并连续地址">
              <el-switch v-model="form.data.merge_addr" :active-value="1" :inactive-value="0" />
              <span style="margin-left:8px;font-size:12px;color:var(--el-text-color-secondary)">20 万点位必须开</span>
            </el-form-item>
            <el-form-item label="单次最大读取数">
              <el-input-number v-model="form.data.max_batch" :min="10" :max="960" :step="10" />
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>

      <template #footer>
        <div style="display:flex;gap:8px">
          <el-button @click="form.show = false">取消</el-button>
          <el-button type="primary" :loading="form.saving" @click="doSave">保存</el-button>
        </div>
      </template>
    </el-drawer>
  </el-card>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { get, post, put, del } from '../utils/request'
import { useUserStore } from '../store'
import {
  BRANDS, SERIES, BRAND_LABEL, PROTOCOL_SCHEMA,
  protocolsOf, protoLabel, ALL_PROTOCOLS, applyBrand, applyProtocol, applySeries,
  applyTsap, tsapSuggestions,
} from '../protocolSchema'

const user = useUserStore()
// 网关列表（站点必须归属一个网关，上限 20 台 PLC）
const gateways = ref([])
const gwMax = ref(20)
// 当前选中的网关有没有在运行
const curGwOffline = computed(() => {
  const g = gateways.value.find(x => x.id === form.data.gateway_id)
  return !!g && g.online === false
})
const canEdit = computed(() => ['admin', 'operator'].includes(user.user?.role))
const sel = ref([])
function onSel(rows) { sel.value = rows }

async function doBatchDelete() {
  const ids = sel.value.map(r => r.id)
  const pts = sel.value.reduce((a, r) => a + (r.point_count || 0), 0)
  try {
    await ElMessageBox.confirm(
      `将删除 ${ids.length} 个站点：${ids.join('、')}\n连同 ${pts} 个点位一起删除；历史数据（TDengine）保留，只是不再采集。确定？`,
      '批量删除站点', { type: 'warning' })
  } catch { return }
  const d = await del('/api/site/batch?confirm=1', { body: { ids } })
  if (d.failed && d.failed.length) {
    ElMessageBox.alert(d.failed.map(f => `${f.id}：${f.reason}`).join('\n'),
      `成功 ${d.deleted.length} 个，失败 ${d.failed.length} 个`, { type: 'warning' })
  } else {
    ElMessage.success(`已删除 ${d.deleted.length} 个站点（含 ${d.deleted_points} 个点位）`)
  }
  sel.value = []
  load()
}

const brandLabel = v => BRAND_LABEL[v] || v || '—'
const seriesOf = b => SERIES[b] || []

const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const kw = ref('')
const fproto = ref('')
const loading = ref(false)

// protocolSchema 的 apply* 系列操作 {protocol, port, ...}；
// 站点表单字段是 plc_protocol/plc_port，做个 shim 适配，协议清单仍只有一份
const shim = computed(() => ({
  protocol: form.data.plc_protocol, port: form.data.plc_port,
  proto_params: form.data.proto_params, brand: form.data.brand,
  series: form.data.series, rack: form.data.rack, slot: form.data.slot,
}))
const protoOptions = computed(() =>
  (form.data.brand ? protocolsOf(form.data.brand) : ALL_PROTOCOLS))
const portHint = computed(() => {
  const sc = PROTOCOL_SCHEMA[form.data.plc_protocol]
  return sc ? ('默认 ' + sc.port) : ''
})
const protoParams = computed(() => {
  const sc = PROTOCOL_SCHEMA[form.data.plc_protocol]
  return sc ? sc.params : []
})

// 型号参考值提示（G2 这类未确证的型号，把一代的值以文字给出，不自动填）
const seriesRef = computed(() => {
  const sc = PROTOCOL_SCHEMA[form.data.plc_protocol]
  const d = sc && sc.seriesDefaults ? sc.seriesDefaults[form.data.series] : null
  return (d && d.ref) || ''
})

// 下拉建议值：remote_tsap 按当前 rack/slot 算三种连接类型的值；其余用静态 opts
function optsOf(f) {
  if (f.k === 'remote_tsap') {
    const sug = tsapSuggestions(form.data.rack, form.data.slot)
    if (sug.length) return sug
  }
  return f.opts || []
}

// rack / slot / conn_type 任一变化 → 重算 TSAP（算不出来就保留手填值）
function onTsapInput() {
  applyTsap({
    rack: form.data.rack,
    slot: form.data.slot,
    proto_params: form.data.proto_params,
  })
}

// 测试地址即时红绿校验 + 手动选数据类型
const testAddr = ref('')
const DTYPES = ['float32', 'uint16', 'int16', 'uint32', 'int32', 'bool', 'byte']
const testDtype = ref('float32')
const addrState = computed(() => {
  if (!testAddr.value) return 'none'
  const sc = PROTOCOL_SCHEMA[form.data.plc_protocol]
  if (!sc || !sc.addrRe) return 'none'
  try { return new RegExp(sc.addrRe).test(testAddr.value.trim().toUpperCase()) ? 'ok' : 'bad' } catch { return 'none' }
})
const addrHint = computed(() => (PROTOCOL_SCHEMA[form.data.plc_protocol] || {}).addrHint || '')
const addrColor = computed(() => (addrState.value === 'bad' ? 'var(--el-color-danger)'
  : addrState.value === 'ok' ? 'var(--el-color-success)' : 'var(--el-text-color-secondary)'))
const addrMsg = computed(() => {
  const label = protoLabel(form.data.plc_protocol)
  if (addrState.value === 'bad') return `${label} 地址格式不对，应为：${addrHint.value}`
  if (addrState.value === 'ok') return '✓ 格式正确'
  return '合法示例：' + addrHint.value
})

async function loadGateways() {
  try {
    const r = await get('/api/gateways')
    gateways.value = (r.items || []).map(g => ({ ...g, max_sites: r.max_sites || 20 }))
    gwMax.value = r.max_sites || 20
    // 只有一个网关时直接替他选上，少点一次
    if (gateways.value.length === 1 && !form.data.gateway_id) {
      form.data.gateway_id = gateways.value[0].id
    }
  } catch (e) { gateways.value = [] }
}

async function load() {
  loading.value = true
  try {
    const q = new URLSearchParams({ page: page.value, size: size.value, kw: kw.value })
    const r = await get('/api/sites?' + q)
    // 采集在线状态来自网关内存（不查库），合并进表格；协议筛选在前端做
    const st = await get('/api/sites/status').catch(() => ({ items: [] }))
    const map = {}
    for (const d of st.items || []) map[d.site] = d.online
    let items = r.items || []
    if (fproto.value) items = items.filter(s => s.plc_protocol === fproto.value)
    rows.value = items.map(s => ({ ...s, online: s.id in map ? map[s.id] : null }))
    total.value = fproto.value ? items.length : r.total
  } finally { loading.value = false }
}

// ---- 列表行测试连接：参数可编辑，测通了可存回本站点（提示词 10 第 1 节）----
// 09：前端只认规范协议名（mc = 三菱 MC 协议，帧格式在协议参数里选）。
// 历史库里的 1E/3E 别名由后端归一到 mc，前端不再出现（verify 第 99 条会盯这个）。
const PORT_DEFAULT = { s7: 102, mc: 5000, modbus_tcp: 502,
                       modbus_rtu: 502, fins: 9600, ab_eth: 44818, cip: 44818, opcua: 4840 }
// 历史别名兜底：mc 系列端口都是 5000，别退化成 502（那是 Modbus 的）
const portOf = (p) => PORT_DEFAULT[p] || (String(p || '').toLowerCase().indexOf('mc') === 0 ? 5000 : 502)
const tst = reactive({
  show: false, loading: false, applying: false, tested: false, ok: false, dirty: false,
  latency: 0, value: null, error: '', hint: '', name: '', row: null, addrUsed: '',
  addr: '', dtype: 'float32',
  form: { protocol: 'modbus_tcp', ip: '', port: 502, slave_id: 1, timeout_ms: 3000 }
})
let tstOkSig = ''
const tstSig = computed(() => JSON.stringify(tst.form) + '|' + tst.addr + '|' + tst.dtype)
watch(tstSig, () => { if (tst.tested) tst.dirty = tstSig.value !== tstOkSig })

function doTest(row) {
  Object.assign(tst, { show: true, loading: false, applying: false, tested: false, ok: false,
    dirty: false, name: row.name || row.id, row, addr: '', dtype: 'float32',
    error: '', hint: '', value: null, addrUsed: '', latency: 0 })
  tst.form = { protocol: row.plc_protocol, ip: row.plc_ip, port: row.plc_port,
               slave_id: row.slave_id ?? 1, timeout_ms: row.timeout_ms || 3000 }
  tstOkSig = ''
}

function onTestProto(v) { tst.form.port = portOf(v) }

async function runTest() {
  if (!tst.form.ip) { ElMessage.warning('IP 不能为空'); return }
  tst.loading = true
  tst.tested = false
  try {
    const d = await post(`/api/site/${tst.row.id}/test`,
      { ...tst.form, addr: tst.addr || '', dtype: tst.dtype })
    tstOkSig = tstSig.value
    Object.assign(tst, {
      tested: true, ok: !!d.ok, dirty: false,
      latency: d.elapsed_ms ?? d.latency_ms ?? 0,
      value: d.sample ?? d.read_value,
      error: d.error || '', hint: d.hint || '',
      addrUsed: (d.tested && d.tested.addr) || tst.addr || '默认地址'
    })
  } catch (e) {
    Object.assign(tst, { tested: true, ok: false, dirty: false,
                         error: String((e && e.message) || e) })
  } finally { tst.loading = false }
}

async function applyTest() {
  tst.applying = true
  try {
    await post(`/api/site/${tst.row.id}/test/apply`, tst.form)
    ElMessage.success('参数已保存并热加载，采集已按新参数生效')
    tst.show = false
    load()
  } finally { tst.applying = false }
}

// ---- 表单（四段，从设备表单吸收） ----
const sp = reactive({ port: 'COM1', baud: 9600, dataBits: 8, stopBits: 1, parity: 'none' })
const form = reactive({ show: false, tab: 'base', saving: false, testing: false, editing: false, data: blank() })
function blank() {
  return { id: '', name: '', gateway_id: '', address: '', location: '', remark: '',
           brand: '', series: '', plc_protocol: 'modbus_tcp', comm_mode: 'tcp',
           plc_ip: '', plc_port: 502, rack: 0, slot: 1, slave_id: 1,
           offline_threshold: 3, merge_addr: 1, max_batch: 120,
           heartbeat_mode: 'none', hb_write_addr: 0, hb_read_addr: 1,
           hb_max_value: 2000, hb_cycles: 3, ping_interval_ms: 5000,
           hb_write_port: null, hb_read_port: null, hb_interval_s: 0,
           enabled: 1, serial_params: null, proto_params: {} }
}
async function openForm(row) {
  // 先等网关列表到位：el-select 的 label 依赖 gateways 数组，
  // 数组没到就渲染，会显示成空白（看着像没选，实际 value 有值）
  await loadGateways()
  form.tab = 'base'
  form.editing = !!row
  form.data = row ? JSON.parse(JSON.stringify(row)) : blank()
  if (typeof form.data.proto_params === 'string') {
    try { form.data.proto_params = JSON.parse(form.data.proto_params || '{}') } catch { form.data.proto_params = {} }
  }
  if (!form.data.proto_params) form.data.proto_params = {}
  if (typeof form.data.serial_params === 'string') {
    try { Object.assign(sp, JSON.parse(form.data.serial_params || '{}')) } catch {}
  }
  applyProtocol(shim.value)
  testAddr.value = ''
  form.show = true
}
function onBrand() {
  applyBrand(shim.value)
  if (!seriesOf(form.data.brand).includes(form.data.series)) form.data.series = ''
}
function onProtocol() {
  form.data.plc_port = PROTOCOL_SCHEMA[form.data.plc_protocol]?.port || 502
  applyProtocol(shim.value)
}
function onSeries() { applySeries(shim.value) }

async function doSave() {
  const d = form.data
  if (!d.id) { ElMessage.warning('站点编号必填'); form.tab = 'base'; return }
  if (!/^[A-Za-z0-9_-]{1,32}$/.test(d.id)) { ElMessage.warning('站点编号限字母/数字/下划线'); form.tab = 'base'; return }
  if (!d.name) { ElMessage.warning('站点名称必填'); form.tab = 'base'; return }
  if (!d.gateway_id) { ElMessage.warning('必须指定所属网关'); form.tab = 'base'; return }
  const gw = gateways.value.find(g => g.id === d.gateway_id)
  if (gw && gw.sites >= gw.max_sites && !form.editing) {
    ElMessage.error(`网关 ${gw.id} 已挂 ${gw.sites} 台 PLC，上限 ${gw.max_sites} 台`)
    form.tab = 'base'; return
  }
  if (!d.brand) { ElMessage.warning('选品牌'); form.tab = 'base'; return }
  if (!d.plc_protocol) { ElMessage.warning('选协议'); form.tab = 'comm'; return }
  if (!d.plc_ip) { ElMessage.warning('PLC IP 必填'); form.tab = 'comm'; return }
  if (d.comm_mode === 'serial') d.serial_params = { ...sp }
  form.saving = true
  try {
    if (d.created_at) {   // 编辑（列表行带回 created_at 标记是已有站点）
      const { id, ...body } = d
      const r1 = await put('/api/site/' + id, body)
      if (r1 && r1.reload_ok === false) {
        ElMessage.warning('站点已保存，但网关没重载：' + (r1.reload_err || '网关未响应')
          + '。新的通讯参数暂时不生效')
      }
    } else {
      const r2 = await post('/api/site', d)
      if (r2 && r2.reload_ok === false) {
        ElMessage.error('站点已存库，但网关没重载：' + (r2.reload_err || '网关未响应')
          + '。这个站点现在不会被采集')
      }
    }
    ElMessage.success('已保存（采集配置已热加载）')
    form.show = false
    load()
  } finally { form.saving = false }
}

// ---- 表单里的测试连接（未保存也能测，参数原样转发网关）----
async function doTestForm() {
  const d = form.data
  if (!d.plc_ip) { ElMessage.warning('先填 PLC IP'); return }
  form.testing = true
  try {
    const r = await post('/api/site/test', {
      protocol: d.plc_protocol, ip: d.plc_ip, port: d.plc_port, slave_id: d.slave_id,
      rack: d.rack, slot: d.slot, series: d.series,
      proto_params: d.proto_params || {}, addr: testAddr.value || '',
      dtype: testDtype.value,
    })
    if (r.ok) {
      ElMessage.success(`连接成功，响应 ${r.latency_ms}ms，读到 ${testAddr.value || '默认地址'} = ${r.read_value}`)
    } else {
      ElMessageBox.alert(
        `<div style="color:var(--el-color-danger)">连接失败：${r.error}</div>
         <div style="margin-top:8px;color:var(--el-text-color-secondary)">排查建议：${r.hint || ''}</div>`,
        '测试连接失败', { dangerouslyUseHTMLString: true, type: 'error' })
    }
  } finally { form.testing = false }
}

// ---- 删除（有点位时后端 400，弹二次确认再 confirm=1）----
async function doDelete(row) {
  try {
    await del('/api/site/' + row.id)
    ElMessage.success('已删除')
  } catch (e) {
    const msg = String(e && e.message || e)
    if (/点位|confirm/.test(msg)) {
      await ElMessageBox.confirm(msg + '。历史数据（TDengine）保留，只是不再采集。是否继续？', '二次确认', { type: 'warning' })
      await del(`/api/site/${row.id}?confirm=1`)
      ElMessage.success('站点与点位已删除')
    }
  }
  load()
}

// 状态 10 秒一刷
let timer = null
onMounted(() => {
  load()
  loadGateways()
  timer = setInterval(load, 10000)
})
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.form-hint { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.5; margin-top: 2px; }
.addr-bad :deep(.el-input__wrapper) { box-shadow: 0 0 0 1px var(--el-color-danger) inset; }
.addr-ok :deep(.el-input__wrapper) { box-shadow: 0 0 0 1px var(--el-color-success) inset; }
</style>
