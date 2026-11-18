"""采集服务：地址合并 -> 批量读 -> 写 Redis Hash + Stream -> 历史入 TDengine -> 报警状态机
   对外提供 /api/status（采集状态）与 /write（带 200ms 回读校验）

09 改造：一站点一台 PLC。配置从 site 表加载（不再有 device 表），
键是站点编号；/internal/reload?site=S001 增量重载单个站点。"""
import os, math, struct, time, json, re, asyncio, logging
from collections import defaultdict
import httpx
import redis.asyncio as aioredis
from pymodbus.client import AsyncModbusTcpClient
# 全系统唯一的地址解析（shared/addr.py 构建时拷到 /app/addr.py）：
# 采集 / 后端校验 / 批量生成 / 导入共用，本文件不再自带解析
from addr import parse_addr, type_size, mc_is_word
# FX3U-ENET-ADP 专用：A 兼容 1E 帧（pymcprotocol 的 3E 帧会被 ADP 静默拒绝成 0）
from fx3u_adp_mc import FX3U_ADP
# S7-200 SMART 专用：S7comm（V 区=DB1、大端、0x8104 容错；pymcprotocol/snap7 通用教程都会踩坑）
from s7_200smart import S7200SMART
# 提示词 10：在线判定（modbus_echo 回环 / ping）——状态机与探测都在这个模块里
from heartbeat import Heartbeat, ONLINE as HB_ONLINE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("collector")

# 本网关的标识：只采 gateway_id 等于它的站点。默认 gw1 = 单网关部署时不用改任何东西。
GATEWAY_ID = os.getenv("GATEWAY_ID", "gw1")
MYSQL_HOST = os.getenv("MYSQL_HOST", "mysql")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_ROOT_PWD = os.getenv("MYSQL_ROOT_PWD", "")   # 必须在 .env 里设置
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
TD_REST = os.getenv("TDENGINE_REST", "http://tdengine:6041")
TD_USER = os.getenv("TD_USER", "root")
# 口令只从 .env 的 TDENGINE_PWD 取，代码里不留出厂默认值
TD_PWD = os.getenv("TDENGINE_PWD") or os.getenv("TD_PWD") or ""
LISTEN_PORT = int(os.getenv("GATEWAY_PORT", "8090"))

# 历史采样参数（全部从环境变量读，不许写死）
SAMPLE_INTERVAL = float(os.getenv("SAMPLE_INTERVAL", "5"))      # 入库周期 秒
HISTORY_HEARTBEAT = float(os.getenv("HISTORY_HEARTBEAT", "60"))  # 心跳兜底 秒
HISTORY_BATCH = int(os.getenv("HISTORY_BATCH", "500"))           # 单次 SQL 最大行数
# 点位没配 hist_interval 时的兜底入库间隔（秒）。生产建议 120~300。
# 注意：这个只影响「写 TDengine 历史」的节奏，不影响采集/实时值/SSE。
HIST_INTERVAL_DEFAULT = float(os.getenv("HIST_INTERVAL_DEFAULT", "180"))

EPS = 1e-6

# ---------------- 地址合并（全系统最关键的算法） ----------------
# 解析在 shared/addr.py（唯一实现）；这里只做块规划。
# modbus 视图：parse_addr('modbus_tcp', 'HR8') -> ('HR', 0, 8, 2, None)
# mc 视图：parse_addr('mc', 'D1018') -> ('D', 0, 1018, 2, None)（字/位看 mc_is_word）
# s7 视图：parse_addr('s7', 'VD1000') -> ('V', 1, 1000, 4, None) —— 位地址 size=1

def _mb_reg(proto, addr):
    """modbus 寄存器/线圈偏移视图"""
    return parse_addr(proto, addr)[2]


def _mc3(addr):
    """mc 三元组视图（软元件字母, 编号, 是否字软元件）—— 只是对唯一解析器的包装"""
    d, _db, n, _sz, _bit = parse_addr("mc", addr)
    return d, n, mc_is_word(d)


def _s7(addr):
    """s7 五元组视图，与 parse_addr('s7', …) 完全同形"""
    return parse_addr("s7", addr)


def s7_span(p):
    """(区, db, 偏移, 读多少字节, 位) —— 字节数取「地址写法」与「数据类型」的较大者。

    VB1006 这种写法按地址规则是 1 字节，但 dtype=uint16 要 2 字节；只读 1 字节再按
    uint16 解会抛 `unpack requires a buffer of 2 bytes`，整个站点被判离线
    （2026-11-10 现场：S001 加了 VB1006/V1007.1 两个点后整站离线，就是这个原因）。
    位地址（V1007.1）例外：读 1 字节取位即可，不受 dtype 影响。
    """
    area, db, off, size, bit = _s7(p["addr"])
    if bit is None:
        size = max(int(size or 0), type_size(p.get("dtype")))
    return area, db, off, size, bit


def max_block(proto):
    return {"s7": 200, "modbus_tcp": 250, "mc": 960}.get(proto, 200)

def plan_requests(points, proto):
    """按地址连续性合并：gap<=8 字节且块不超上限就并入同一请求"""
    def key(p):
        return parse_addr(proto, p["addr"])[0], parse_addr(proto, p["addr"])[2]
    pts = sorted(points, key=key)
    blocks, cur = [], []
    for p in pts:
        if not cur:
            cur = [p]; continue
        last = cur[-1]
        gap = key(p)[1] * 2 - (key(last)[1] * 2 + type_size(last["dtype"]))
        if (key(p)[0] == key(last)[0] and 0 <= gap <= 8
                and (key(p)[1] - key(cur[0])[1]) * 2 + type_size(p["dtype"]) <= max_block(proto)):
            cur.append(p)
        else:
            blocks.append(cur); cur = [p]
    if cur:
        blocks.append(cur)
    return blocks

def decode_val(dtype, raw_regs, byte_order="ABCD"):
    """寄存器数组 -> 数值；REAL 必须 4 字节整体读"""
    if dtype == "byte":
        # 无符号 8 位：只取寄存器低字节（VB 这类字节寻址点位用它）
        return float(int(raw_regs[0]) & 0xFF)
    if dtype in ("uint16", "int16", "bool"):
        v = raw_regs[0]
        if dtype == "int16" and v >= 0x8000:
            v -= 0x10000
        return float(v)
    if dtype == "float32":
        b = struct.pack(">HH", raw_regs[0], raw_regs[1])
        if byte_order == "CDAB":
            b = struct.pack(">HH", raw_regs[1], raw_regs[0])
        return struct.unpack(">f", b)[0]
    if dtype == "float64":
        # 8 字节 = 4 个寄存器；CDAB 只交换相邻两字（与 float32 语义一致）
        if len(raw_regs) < 4:
            return None
        if byte_order == "CDAB":
            regs = [raw_regs[1], raw_regs[0], raw_regs[3], raw_regs[2]]
        else:
            regs = list(raw_regs[:4])
        b = struct.pack(">HHHH", *regs)
        return struct.unpack(">d", b)[0]
    if dtype in ("int32", "uint32"):
        v = (raw_regs[0] << 16) | raw_regs[1]
        if dtype == "int32" and v >= 0x80000000:
            v -= 0x100000000
        return float(v)
    if dtype == "string":
        # 字符串是变长类型，点位表里没有"长度"字段，无法确定要读几个寄存器。
        # 这里不猜长度、也不返回第一个寄存器的值（那会造成"看起来有数"的假象），
        # 明确返回 None，由上层按"该点位不支持"处理并记日志。
        return None
    return float(raw_regs[0])

def near(a, b):
    """浮点比较（写入回读校验用），禁止 ==。

    不能只用固定 1e-6 绝对容差：float32 存不下十进制小数，
    44.88 读回来是 44.880001068115234，绝对差 1.068e-6 > 1e-6，
    会被误判成「写入失败」（用户 2026-11 实测踩到）。
    float32 相对精度约 1.19e-7，44.88 档的绝对误差上限约 5.4e-6，
    所以容差按量级放大：max(EPS, max(|a|,|b|,1) * 4.8e-7)。
    整数比较（1 vs 0）差值远大于容差，仍然判不等。
    """
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return a == b
    if fa == fb:
        return True
    scale = max(abs(fa), abs(fb), 1.0)
    return abs(fa - fb) <= max(EPS, scale * 4.8e-7)

# ---------------- MC · FX3U-ENET-ADP（A 兼容 1E 帧） ----------------
# 驱动来自 Hermes 时期验证过的 fx3u_adp_mc.py（2026-11-09 装进平台）。
# 关键事实：ADP 只支持 1E 帧，pymcprotocol 的 3E 帧会被 ADP 拒绝并静默返回 0
# （实测：真值 2.653，3E 帧读回 [0,0] 不报错）——FX3U 设备绝不能走 pymcprotocol。
# 字/位软元件分类在 shared/addr.py（MC_WORD_DEVS / mc_is_word），这里不重复定义。


def mc_use_1e(series, proto_params):
    """这台 MC 设备该不该走 A 兼容 1E 帧（fx3u_adp_mc 驱动）。

    FX3U/FX3G 挂 FX3U-ENET-ADP 只认 1E 帧：ADP 收到 3E 帧不报错，直接把
    数据读成 0，看着"连上了"其实全是假值（2026-11-09 实测复现）。
    所以「系列是 FX」或「协议参数里显式选了 1E」都走 1E 帧；
    Q/L/iQ-R 内置以太网的 3E/4E 走 pymcprotocol。"""
    if "fx" in (series or "").lower():
        return True
    return str((proto_params or {}).get("frame") or "").upper() == "1E"


def s7_rack_slot(series, rack, slot):
    """S7-200 SMART 的 rack/slot 恒为 0/1，别信库里存的数。

    实测（2026-11-09，x.x.x.x）：rack=1/slot=0 时无论 PG 还是 OP 都被
    PLC 直接 RST；rack=0/slot=1 时 OP/S7basic 正常读数。S7-200 SMART 是整体式
    CPU，没有机架，设备表里这两个字段被人填过 1/0 → 测试连接必挂，
    而采集端一直写死 0/1，两边参数不一致更难查。这里统一归一。"""
    if "200smart" in (series or "").lower():
        return 0, 1
    return rack or 0, slot if slot is not None else 1


def s7_conn_type(proto_params):
    """取连接类型，缺省 OP（S7-200 SMART 上 OP 最稳，见 s7_200smart.py 注释）"""
    return str((proto_params or {}).get("conn_type") or "OP").strip() or "OP"


def plan_mc_requests(points):
    """MC 版块规划：按软元件字母分组，字软元件（D 等）按字连续合并（≤64 点），
    位软元件（M 等）按编号连续合并（≤256 点）。返回与 Modbus 版相同的
    「点位列表块」结构，read_block_mc 按首末点算跨度。"""
    def k(p):
        d, n, w = _mc3(p["addr"])
        return (d, 0 if w else 1, n)
    pts = sorted(points, key=k)
    blocks, cur = [], []
    for p in pts:
        if not cur:
            cur = [p]; continue
        d0, w0, n0 = k(cur[0])
        dl, wl, nl = k(cur[-1])
        dp_, wp_, np_ = k(p)
        if (dp_, wp_) == (d0, w0):
            if wp_ == 0:      # 字软元件
                span = np_ - n0 + max(1, type_size(p["dtype"]) // 2)
                gap = np_ - nl - max(1, type_size(cur[-1]["dtype"]) // 2)
                if 0 <= gap <= 4 and span <= 64:
                    cur.append(p); continue
            else:             # 位软元件
                gap = np_ - nl - 1
                if 0 <= gap <= 16 and (np_ - n0 + 1) <= 256:
                    cur.append(p); continue
        blocks.append(cur); cur = [p]
    if cur:
        blocks.append(cur)
    return blocks

def decode_mc(dtype, words, byte_order=None):
    """MC 寄存器数组 -> 数值。FX3U 的 32 位量默认低字在前（手册 + 实测 44.33=CDAB）；
    decode_val 的 float32+CDAB 恰好就是低字在前语义，直接复用；
    int32/uint32 decode_val 不认 byte_order，这里自己换字序。"""
    bo = (byte_order or "CDAB").upper()
    if dtype == "float32":
        return decode_val("float32", words, bo)
    if dtype in ("int32", "uint32"):
        return decode_val(dtype, words if bo == "ABCD" else words[::-1])
    return decode_val(dtype, words)

# ---------------- S7 · S7-200 SMART（S7comm，python-snap7 3.x） ----------------
# 驱动来自 Hermes 时期验证过的 s7_200smart.py（2026-11-09 装进平台）。
# 关键事实：V 区=DB1、rack0/slot1、大端（VD1000=44.335 用 >f）；
# connect 内部的 0x8104（USERDATA，200SMART 不支持 CPU 信息查询）要容错；
# python-snap7 的 Client.connect 第 4 参是 TCP 端口——旧代码把 pdu_size 传进去了，
# 全部 S7 测试连接都在连 480 端口（这就是"S7 测试地址填 VD 没反应"的真凶）。

S7_KIND_SIZE = {"X": 1, "B": 1, "W": 2, "D": 4}   # 兼容旧引用（shared/addr.py 同表）

def decode_s7(dtype, data, bit=None):
    """S7 字节序是**大端**（skill 实测：42 31 57 0A 用 >f 是 44.335，用 <f 是 0）"""
    if bit is not None:
        return float((data[0] >> bit) & 1)
    if dtype == "byte":
        # 无符号 8 位，取单字节（VB 寻址）
        return float(data[0])
    if dtype in ("uint16", "int16", "bool"):
        v = struct.unpack(">H", data[:2])[0]
        if dtype == "int16" and v >= 0x8000:
            v -= 0x10000
        return float(v)
    if dtype == "float32":
        return struct.unpack(">f", data[:4])[0]
    if dtype in ("int32", "uint32"):
        v = struct.unpack(">I", data[:4])[0]
        if dtype == "int32" and v >= 0x80000000:
            v -= 0x100000000
        return float(v)
    return float(data[0])

def plan_s7_requests(points):
    """S7 版块规划：按 (区, 是否位) 分组。字按字节偏移连续合并（gap≤8B、块≤200B，
    REAL/DINT 4 字节对齐整体读绝不拆跨请求）；位按字节偏移合并（≤200B），
    读整字节再取位。"""
    def k(p):
        area, _db, off, size, bit = s7_span(p)
        return (area, 1 if bit is not None else 0, off, size)
    pts = sorted(points, key=k)
    blocks, cur = [], []
    for p in pts:
        if not cur:
            cur = [p]; continue
        a0, b0, o0, _s0 = k(cur[0])
        al, bl, ol, sl = k(cur[-1])
        ap, bp, op, sp = k(p)
        if (ap, bp) == (a0, b0):
            if bp == 0:      # 字
                need = op - o0 + sp
                gap = op - ol - sl
                if 0 <= gap <= 8 and need <= 200:
                    cur.append(p); continue
            else:            # 位
                # 同一个字节里的不同位（I0.0 / I0.1）`off` 是相同的（位号在 bit 里），
                # 直接算 op-ol-1 会得到 -1，被判成"不连续"，于是每一位单独成块。
                # 251 个点位时这会炸成 174 个块、每轮 732ms。
                # 同字节 → gap 记 0；跨字节 → 按字节差减 1。
                gap = 0 if op == ol else (op - ol - 1)
                if 0 <= gap <= 16 and (op - o0 + 1) <= 200:
                    cur.append(p); continue
        blocks.append(cur); cur = [p]
    if cur:
        blocks.append(cur)
    return blocks

def plan_by_period(points, plan_fn):
    """按点位 poll_ms 分组，各组独立做块规划。

    为什么要分组：块是把"地址连续"的点位合并成一次请求。如果快慢点位混在一个块里，
    这个块只能用最快那条的周期去读 —— 慢的那条就被无辜拖快了（白烧通讯）。
    所以周期不同的点位**绝不能合进同一个块**，宁可多一次请求。

    返回 (blocks, periods)：blocks 还是原来那种 list[list[point]]，
    periods[i] 是 blocks[i] 的采集周期（毫秒）。两者一一对应，
    这样读取链路（read_block 等）完全不用改。
    """
    groups = {}
    for p in points:
        try:
            pm = int(p.get("poll_ms") or 0)
        except (TypeError, ValueError):
            pm = 0
        if pm <= 0:
            pm = SITE_POLL_MS        # 点位没填就跟随站点级默认
        groups.setdefault(pm, []).append(p)

    blocks, periods = [], []
    for pm in sorted(groups):
        for b in plan_fn(groups[pm]):
            blocks.append(b)
            periods.append(pm)
    return blocks, periods


# ---------------- 采集核心 ----------------
class Collector:
    def __init__(self):
        self.rc = None
        # 09 改造：键是站点编号（一站点一台 PLC），unit["site"] 就是键本身
        self.sites = {}     # site_id -> {site, client, points, blocks, poll_ms, online, ...}
        self.tasks = []       # 每个站点一个采集协程；/api/reload 时整组重建
        self._site_tasks = {} # site_id -> 协程；/internal/reload?site= 单站重建用
        self._reload_lock = None
        self.gen = 0          # 代际标记：reload 后旧协程看到代数变了会自行退出
        self.td = httpx.AsyncClient(timeout=10, auth=(TD_USER, TD_PWD))
        self.last_hist = {}   # (site, code) -> val（deadband 判断）
        self.last_q = {}      # (site, code) -> 上次质量码
        # (site, code) -> 上次真正写入历史的时刻：点位级 hist_interval 判断用。
        # 只在真正 append 之后刷新（和 last_hist_ts 一个道理，空跑不能刷新）
        self.last_hist_point_ts = {}
        self.last_q_ts = {}   # (site, code) -> 上次写入时间
        self.last_hist_ts = 0
        self.hist_written = 0  # 累计入库行数（供 /api/status 观测）
        self._conn = None      # 复用 MySQL 连接
        self.alarm_state = {}  # (site, code) -> "上限"/"下限"/None
        self.alarm_ids = {}    # (site, code) -> alarm.id
        # 提示词 10：心跳（在线/离线判定）——状态变化才回调写库
        self.hb = Heartbeat(self._hb_on_change)

    async def _hb_on_change(self, sid: str, state: str):
        """心跳状态变化：只在这里写库/Redis/事件（每轮 UPDATE 会打爆 MySQL）。"""
        online = state == HB_ONLINE
        dev = self.sites.get(sid)
        if dev:
            dev["hb_state"] = state
        code = 1 if online else 2
        # Redis：site:status:{id}（1 在线 / 2 离线）
        try:
            await self.rc.set(f"site:status:{sid}", code)
            await self.rc.xadd("stream:status",
                               {"site": sid, "status": str(code), "state": state,
                                "ts": str(int(time.time() * 1000))},
                               maxlen=10000, approximate=True)
        except Exception as e:
            log.warning("心跳状态写 Redis 失败 %s: %s", sid, e)
        try:
            await asyncio.to_thread(self._write_site_status, sid, code)
        except Exception as e:
            log.warning("心跳状态写库失败 %s: %s", sid, e)
        log.info("站点 %s 心跳判定 → %s（site.status=%d）", sid, state, code)

    def _write_site_status(self, sid: str, code: int):
        conn = self._db()
        cur = conn.cursor()
        cur.execute("update site set status=%s where id=%s", (code, sid))
        conn.commit()
        conn.close()

    async def load_config(self, only_site: str = None):
        """启动/全量重载：一次性把 enabled=1 的站点（=PLC）和点位加载进内存，
        运行期间不查数据库（提示词 09 第 4 节）。
        only_site 给 /internal/reload 用：只重载一个站点，别的站点采集不中断。"""
        import pymysql
        conn = pymysql.connect(host=MYSQL_HOST, port=int(MYSQL_PORT),
                               user="root", password=MYSQL_ROOT_PWD,
                               database="plant", charset="utf8mb4")
        cur = conn.cursor(pymysql.cursors.DictCursor)
        # 只加载属于本网关的站点（site.gateway_id）。没指定网关的站点谁都不采，
        # 这是刻意的：多网关一起抢同一台 PLC 会先把连接槽打满，
        # 表现成"平台和编程软件都连不上"，比不采更难查。
        where = "where enabled = 1 and gateway_id = %s"
        params = [GATEWAY_ID]
        if only_site:
            where += " and id = %s"
            params.append(only_site)
        cur.execute("""select id, name, gateway_id, plc_protocol, plc_ip, plc_port, slave_id,
                              rack, slot,
                              brand, series, comm_mode, proto_params,
                              offline_threshold, merge_addr, max_batch,
                              heartbeat_mode, hb_write_addr, hb_read_addr,
                              hb_max_value, hb_cycles, ping_interval_ms,
                              hb_write_port, hb_read_port, hb_interval_s
                       from site """ + where, tuple(params))
        rows = cur.fetchall()
        if only_site:
            # 增量：只清这一个站点（先关长连接，ADP 的 MC 口很金贵）
            old = self.sites.get(only_site)
            if old and old.get("client"):
                try:
                    old["client"].close()
                except Exception:
                    pass
            self.sites.pop(only_site, None)
            self._clear_hist_cache(only_site)
            self.hb.drop(only_site)      # 心跳状态机重置，重载后重新判定
        else:
            for old in self.sites.values():
                if old.get("driver") in ("mc1e", "s7smart") and old.get("client"):
                    try:
                        old["client"].close()
                    except Exception:
                        pass
            for sid in list(self.sites):
                self._clear_hist_cache(sid)
                self.hb.drop(sid)
            self.sites.clear()
        total_pts = 0
        new_ids = []
        for d in rows:
            unit = self._build_unit(cur, d)
            if unit is None:
                continue
            self.sites[d["id"]] = unit
            new_ids.append(d["id"])
            total_pts += len(unit["points"])
        conn.close()
        # 新点位在 Redis 里建 field（初始 null|0|1：值是 null，画面显示「无数据」不是 0）
        if new_ids:
            try:
                await self._seed_rt_fields(new_ids)
            except Exception as e:
                log.warning("Redis 初始化新点位 field 失败（不影响采集）: %s", e)
        if only_site:
            log.info("站点 %s 已重载：%d 点，请求块数 %d",
                     only_site, total_pts, len(self.sites.get(only_site, {}).get("blocks", [])))
        else:
            log.info("已加载 %d 个站点 / %d 个点位；请求块数: %s",
                     len(self.sites), total_pts,
                     {k: len(u["blocks"]) for k, u in self.sites.items()})

    def _build_unit(self, cur, d):
        """一行 site → 一个采集单元（驱动分派 + 点位加载 + 块规划）"""
        try:
            pp = d["proto_params"] if isinstance(d["proto_params"], dict) else \
                (json.loads(d["proto_params"]) if d["proto_params"] else {})
        except Exception:
            pp = {}
        proto = (d["plc_protocol"] or "").lower()
        # MC · FX3U-ENET-ADP：A 兼容 1E 帧（系列含 FX 或参数里 frame=1E 都算）
        # S7 · S7-200 SMART：S7comm（V 区=DB1、大端、0x8104 容错）
        is_fx = proto in ("mc", "mc_1e", "mc_3e") and mc_use_1e(d["series"], pp)
        is_s7smart = proto == "s7" and "200smart" in (d["series"] or "").lower()
        # 其余协议（MC-Q/FINS/OPC UA/非 200SMART 的 S7）站点照常录入、测试连接
        # 可用，但不进采集循环——不装作能采，免得刷一屏假错误
        if proto not in ("modbus_tcp", "modbus_rtu") and not (is_fx or is_s7smart):
            log.warning("站点 %s 协议 %s 采集驱动未接入，跳过采集；测试连接不受影响",
                        d["id"], proto)
            return None
        driver = "mc1e" if is_fx else ("s7smart" if is_s7smart else "modbus")
        unit = {
            "site": d["id"], "protocol": proto if proto != "mc_1e" else "mc",
            "ip": d["plc_ip"], "port": d["plc_port"],
            "slave_id": d["slave_id"] or 1,
            "driver": driver,
            "brand": d["brand"], "series": d["series"], "proto_params": pp,
            "merge_addr": d["merge_addr"], "max_batch": d["max_batch"],
            "offline_threshold": d["offline_threshold"] or 3,
            "poll_ms": SITE_POLL_MS,
            "timeout_ms": COMM_TIMEOUT_MS,
            # 心跳（提示词 10）：none / modbus_echo / ping
            "hb_mode": (d.get("heartbeat_mode") or "none").lower(),
            "hb_write_addr": d.get("hb_write_addr") or 0,
            "hb_read_addr": d.get("hb_read_addr") if d.get("hb_read_addr") is not None else 1,
            "hb_max_value": d.get("hb_max_value") or 2000,
            "hb_cycles": d.get("hb_cycles") or 3,
            # 双端口回环：NULL/0 表示回落站点 plc_port
            "hb_write_port": d.get("hb_write_port"),
            "hb_read_port": d.get("hb_read_port"),
            # >0 时心跳按自己的秒级节奏跑，不跟每轮采集绑死
            "hb_interval_s": d.get("hb_interval_s") or 0,
            "ping_interval_ms": d.get("ping_interval_ms") or 5000,
            "hb_state": "unknown", "last_poll_ok": False,
            "points": [], "client": None, "online": False,
            "last_err": "",
            "stat": [],   # (ts, ok, latency_ms) 滑窗，最近 5 分钟
            "round_requests": 0, "values": {}}
        # poll_ms 必须查出来：块规划要按点位周期分组（快慢点位不能合进同一块）
        # hist_interval：点位级历史入库间隔（秒）。网关之前从不读这个字段，
        # 实际按全局 SAMPLE_INTERVAL=5 入库 —— 200 站 × 1000 点会撑不住。
        cur.execute("""select code, name, addr, dtype, byte_order, unit,
                              scale_min, scale_max, decimals, rw, deadband, save_history,
                              poll_ms, hist_interval
                       from point where site_id = %s and enabled = 1""", (d["id"],))
        pts = [p for p in cur.fetchall() if p["dtype"] != "string"]  # string 本期不采
        unit["points"] = pts
        if driver == "mc1e":
            unit["blocks"] = plan_mc_requests(pts)
            unit["plan_fn"] = plan_mc_requests
            # 1E 帧同步 socket，poll 里 to_thread；连接懒建，断了重连
            unit["client"] = FX3U_ADP(unit["ip"], unit["port"] or 4999,
                                      timeout=COMM_TIMEOUT_S)
        elif driver == "s7smart":
            unit["blocks"] = plan_s7_requests(pts)
            unit["plan_fn"] = plan_s7_requests
            # S7-200 SMART 固定 rack0/slot1；连接类型取协议参数（PG 被占时驱动自己回退）
            _r, _s = s7_rack_slot(unit["series"], d["rack"] or 0,
                                  d["slot"] if d["slot"] is not None else 1)
            # TSAP / PDU 由界面填（可留空=自动）。填了就走显式 TSAP 且不回退，
            # 填错 PLC 直接 RST —— 这是要的效果，能立刻定位到参数错误。
            _pp = unit["proto_params"] or {}
            unit["client"] = S7200SMART(unit["ip"], rack=_r, slot=_s,
                                        port=unit["port"] or 102,
                                        timeout_s=COMM_TIMEOUT_S,
                                        conn_type=s7_conn_type(_pp),
                                        local_tsap=_pp.get("local_tsap"),
                                        remote_tsap=_pp.get("remote_tsap"),
                                        pdu_size=_pp.get("pdu_size"),
                                        max_conn=_pp.get("max_conn"))
        else:
            unit["blocks"] = plan_requests(pts, unit["protocol"])
            unit["plan_fn"] = lambda ps: plan_requests(ps, unit["protocol"])
            unit["client"] = AsyncModbusTcpClient(unit["ip"], port=unit["port"],
                                                  timeout=COMM_TIMEOUT_S)
        # ---- 按点位周期调度（用户 2026-11-13 要求）----
        # 每个点位按自己 poll_ms 到期；同一时刻到期的点位合并成一次读取。
        # 基准 = 所有点位里最小的 poll_ms；没填 poll_ms 的点位跟随基准。
        _raw = []
        for _p in pts:
            try:
                _pm = int(_p.get("poll_ms") or 0)
            except (TypeError, ValueError):
                _pm = 0
            _raw.append(_pm if _pm > 0 else 0)
        _pos = [x for x in _raw if x > 0]
        _base = min(_pos) if _pos else SITE_POLL_MS
        unit["base_ms"] = _base
        unit["point_periods"] = {}
        unit["point_due"] = {}
        # 站点级 IO 互斥：S7 / MC 都是单连接、严格串行的协议。
        # 采集协程和 HTTP 写入 handler 会并发摸同一个 client，
        # 并发一发生就 Stale packet / Receive timeout，那一块点位停更几秒，
        # 前端 boundState 判 stale 直接显示 "--"（用户看到的「只显示不刷新」）。
        unit["io_lock"] = asyncio.Lock()
        for _p, _pm in zip(pts, _raw):
            _code = _p["code"]
            unit["point_periods"][_code] = _pm if _pm > 0 else _base
            unit["point_due"][_code] = 0.0        # 启动即全部到期
        return unit

    async def _seed_rt_fields(self, site_ids):
        """新点位建 Redis field：HSETNX rt:{site} code "null|0|1"——只建缺失的，
        不覆盖已有值。画面读到 null 显示「无数据」（不是 0）。"""
        pipe = self.rc.pipeline()
        for sid in site_ids:
            u = self.sites.get(sid)
            if not u:
                continue
            for p in u["points"]:
                pipe.hsetnx(f"rt:{sid}", p["code"], "null|0|1")
        await pipe.execute()

    async def read_block(self, dev, block):
        """一个合并块一次读（Modbus）；返回 {code: val}"""
        c: AsyncModbusTcpClient = dev["client"]
        proto = dev["protocol"]
        start = _mb_reg(proto, block[0]["addr"])
        need = (_mb_reg(proto, block[-1]["addr"]) - start) * 2 \
               + type_size(block[-1]["dtype"])
        nreg = (need + 1) // 2
        rr = await c.read_holding_registers(start, nreg, slave=dev["slave_id"])
        if rr.isError():
            raise IOError(f"read {start}x{nreg} fail")
        out = {}
        for p in block:
            off = _mb_reg(proto, p["addr"]) - start
            regs = rr.registers[off:]
            out[p["code"]] = decode_val(p["dtype"], regs, p.get("byte_order") or "ABCD")
        return out

    def read_block_mc(self, dev, block):
        """MC 1E 帧：一个块一次读（同步 socket，poll_once_mc 里走 to_thread）。
        字软元件按字读，decode_mc 解码；位软元件按位读。"""
        c = dev["client"]
        dev0, num0, is_word = _mc3(block[0]["addr"])
        out = {}
        if is_word:
            _, numL, _ = _mc3(block[-1]["addr"])
            span = numL - num0 + max(1, type_size(block[-1]["dtype"]) // 2)
            words = c.read_words(dev0, num0, span)
            for p in block:
                off = _mc3(p["addr"])[1] - num0
                out[p["code"]] = decode_mc(p["dtype"], words[off:], p.get("byte_order"))
        else:
            _, numL, _ = _mc3(block[-1]["addr"])
            bits = c.read_bits(dev0, num0, numL - num0 + 1)
            for p in block:
                off = _mc3(p["addr"])[1] - num0
                out[p["code"]] = float(bits[off])
        return out

    def _mc_round(self, dev, blocks=None):
        """读指定块（None = 全站静态块）。同一连接内连续读，省握手。"""
        vals = {}
        sel = blocks if blocks is not None else dev["blocks"]
        for block in sel:
            vals.update(self.read_block_mc(dev, block))
        return vals

    def read_block_s7smart(self, dev, block):
        """S7-200 SMART 一个块一次读（同步 socket，poll_once_s7 里走 to_thread）。
        字：按首末点字节偏移读整段再切；位：读整字节再取位。大端解码。"""
        c = dev["client"]
        a0, _db0, off0, _sz0, bit0 = s7_span(block[0])
        out = {}
        if bit0 is not None:
            _a, _d, offL, _s, _b = s7_span(block[-1])
            data = c.read_raw(a0, off0, offL - off0 + 1)
            for p in block:
                _a, _d, off, _s, bit = s7_span(p)
                out[p["code"]] = float((data[off - off0] >> bit) & 1)
        else:
            _a, _d, offL, szL, _b = s7_span(block[-1])
            data = c.read_raw(a0, off0, offL - off0 + szL)
            for p in block:
                _a, _d, off, sz, bit = s7_span(p)
                out[p["code"]] = decode_s7(p["dtype"], data[off - off0:], bit)
        return out

    def _s7_round(self, dev, blocks=None):
        """读指定块（None = 全站静态块）。同一连接内连续读，省握手。

        注意：整轮读 251 个点位要 1.3 秒，如果整轮持 io_lock，
        期间所有写入/回读都要排队 1.2 秒（实测 IOPROF）。
        因此采集侧改成逐块调用（见 poll_once_s7smart），本函数只保留给
        "一次读完全部块"的兼容路径。
        """
        vals = {}
        sel = blocks if blocks is not None else dev["blocks"]
        for block in sel:
            vals.update(self.read_block_s7smart(dev, block))
        return vals

    async def _io_call(self, dev, fn, *a):
        """所有对 PLC 的同步读写都从这里走：按站点串行。

        为什么必须串行：S7comm / MC 1E 都是「单 TCP 连接、一问一答」的协议。
        采集协程和 HTTP 写入 handler 同时用一个 client，第二个请求的响应会
        和第一个错序，驱动层报 Stale packet 或 Receive timeout，然后退避 5 秒 ——
        这几秒里该块的点位全都不更新，前端 boundState 判 stale 显示 "--"。
        snap7 自己的 max_parallel 只管库内并发，管不了「协程 vs HTTP」。
        """
        lock = dev.get("io_lock")
        if lock is None:
            return await asyncio.to_thread(fn, *a)
        async with lock:
            return await asyncio.to_thread(fn, *a)

    async def _finish_poll(self, dev, vals, ok, n_blocks=None):
        """poll 通用收尾：写 Redis + 变化流 + 报警判定（Modbus / MC 共用）

        n_blocks：本轮实际读了多少块（按周期调度后，一轮只读到期的那几块）。
        不传就按全部块算，兼容旧调用。
        """
        dev["online"] = ok
        if ok:
            dev["last_err"] = ""
        dev["round_requests"] = n_blocks if n_blocks is not None else len(dev["blocks"])
        ts = int(time.time() * 1000)
        prev = dev["values"]
        pipe = self.rc.pipeline()
        changed = 0
        for code, v in vals.items():
            pipe.hset(f"rt:{dev['site']}", code, f"{v}|{ts}|0")
            # 只有真变了才进变化流：200 站点时能砍掉绝大部分 Redis 写入与 SSE 流量
            old = prev.get(code)
            if old is None or abs(v - old) > EPS:
                pipe.xadd("stream:changes",
                          {"site": dev["site"], "point": code, "val": f"{v:.6g}",
                           "ts": str(ts), "q": "0"}, maxlen=100000, approximate=True)
                changed += 1
        await pipe.execute()
        # 按周期调度后，一轮只读到期的那几块 —— 这里必须「合并」而不是「覆盖」，
        # 否则没读到的点位会从内存里消失，下一轮轮到它们时 prev 取不到值，
        # 会被当成"从无到有"推一条假变化，慢周期点位越多假变化越多。
        merged = dict(dev.get("values") or {})
        merged.update(vals)
        dev["values"] = merged
        dev["changed"] = changed
        # 报警判定
        await self.check_alarms(dev, vals)
        # 心跳判定（提示词 10）：modbus_echo 每轮写 N 读回比对；ping 模式叠加 ping 结果。
        # 判定失败不影响本轮采集，只是状态机记账。
        dev["last_poll_ok"] = ok
        # 心跳不在这里判定了：由独立的 _hb_loop 一直跑（用户 2026-11 要求）

    async def poll_blocks(self, sid, blocks=None):
        """读指定块。blocks=None → 读全站静态规划的全部块。

        _loop 每轮把「这一 tick 到期的点位」动态规划成块传进来，
        不同 tick 的块可能完全不同（这点只有 A1，下一点 A1+A2）。
        """
        dev = self.sites[sid]
        if blocks is not None and not blocks:
            return
        drv = dev.get("driver")
        if drv == "mc1e":
            return await self.poll_once_mc(sid, blocks)
        if drv == "s7smart":
            return await self.poll_once_s7smart(sid, blocks)
        return await self.poll_once(sid, blocks)

    async def poll_once(self, sid, blocks=None):
        dev = self.sites[sid]
        if dev.get("driver") == "mc1e":
            return await self.poll_once_mc(sid)
        if dev.get("driver") == "s7smart":
            return await self.poll_once_s7smart(sid)
        site = dev["site"]
        c = dev["client"]
        if not c.connected:
            await c.connect()
        if not c.connected:
            dev["online"] = False
            dev["last_err"] = "连接失败（Modbus TCP）"
            return
        vals = {}
        ok = True
        sel = blocks if blocks is not None else dev["blocks"]
        for block in sel:
            try:
                vals.update(await self.read_block(dev, block))
            except Exception as e:
                log.warning("%s 读块失败: %s", site, e)
                ok = False
                dev["last_err"] = str(e)[:250]
                await c.close()
                await asyncio.sleep(1)
                await c.connect()
        await self._finish_poll(dev, vals, ok, n_blocks=len(sel))

    async def poll_once_mc(self, sid, blocks=None):
        """FX3U 1E 帧轮询：同步 socket 丢线程池；失败后退避重连。

        🔴 ADP 只有 3 个 MC 连接槽（+1 MELSOFT 留给 GX Works），且对半开连接
        释放得很慢——2026-11-09 实测：每秒重连几分钟就把槽打满，之后谁都连不上
        （连 1E 真驱动也 0 字节无响应）。所以失败必须指数退避：5s→10s→…→30s。"""
        dev = self.sites[sid]
        site = dev["site"]
        c = dev["client"]
        if not dev["points"]:
            dev["online"] = True
            dev["last_err"] = ""
            dev["last_poll_ok"] = True
            return
        # 退避窗口内本轮直接跳过（保持上一轮的 online 状态，不刷错误）
        if time.monotonic() < dev.get("drv_retry_after", 0):
            return
        if not c.sock:
            try:
                await asyncio.to_thread(c.connect)
            except Exception as e:
                dev["online"] = False
                dev["last_err"] = f"连接失败（MC 1E）：{e}"[:250]
                self._drv_backoff(dev)
                return
        try:
            # MC 的块通常只有 1 个，暂不拆分；S7 侧才是 251 点位的大块
            vals = await self._io_call(dev, self._mc_round, dev, blocks)
        except Exception as e:
            dev["online"] = False
            dev["last_err"] = str(e)[:250]
            log.warning("%s MC 读块失败: %s（退避 %ds）",
                        site, e, dev.get("drv_backoff_s", 5))
            await asyncio.to_thread(c.close)   # 连接可能已坏，退避后重建
            self._drv_backoff(dev)
            return
        dev["drv_backoff_s"] = 5              # 成功一轮就归零
        dev["drv_retry_after"] = 0
        await self._finish_poll(dev, vals, True,
                                n_blocks=len(blocks) if blocks is not None else len(dev["blocks"]))

    @staticmethod
    def _drv_backoff(dev):
        """失败退避：5s 起，每连败一次翻倍，封顶 30s（ADP 释放半开连接要时间）"""
        nxt = min(int(dev.get("drv_backoff_s") or 5) * 2, 30)
        dev["drv_backoff_s"] = nxt
        dev["drv_retry_after"] = time.monotonic() + nxt

    async def poll_once_s7smart(self, sid, blocks=None):
        """S7-200 SMART 轮询：与 MC 同一套语义——长连接 + 失败退避，不动 Redis"""
        dev = self.sites[sid]
        site = dev["site"]
        c = dev["client"]
        if not dev["points"]:
            dev["online"] = True
            dev["last_err"] = ""
            dev["last_poll_ok"] = True
            return
        if time.monotonic() < dev.get("drv_retry_after", 0):
            return
        if not c.cli:
            try:
                await self._io_call(dev, c.connect)   # 0x8104 已在驱动内容错
            except Exception as e:
                dev["online"] = False
                dev["last_err"] = f"连接失败（S7comm）：{e}"[:250]
                self._drv_backoff(dev)
                return
        try:
            # 逐块加锁：整轮 1.3 秒的锁会把写入卡住 1.2 秒（见 _s7_round 注释）。
            # 每块一个 io_call，块间让出锁，写请求可在块间隙插队。
            sel_blocks = blocks if blocks is not None else dev["blocks"]
            vals = {}
            for _blk in sel_blocks:
                vals.update(await self._io_call(dev, self.read_block_s7smart, dev, _blk))
        except Exception as e:
            dev["online"] = False
            dev["last_err"] = str(e)[:250]
            log.warning("%s S7 读块失败: %s（退避 %ds）",
                        site, e, dev.get("drv_backoff_s", 5))
            await asyncio.to_thread(c.close)
            self._drv_backoff(dev)
            return
        dev["drv_backoff_s"] = 5
        dev["drv_retry_after"] = 0
        await self._finish_poll(dev, vals, True,
                                n_blocks=len(blocks) if blocks is not None else len(dev["blocks"]))

    def _db(self):
        """复用一条 pymysql 连接（原来每个站点每轮都新建连接，20 站就把 MySQL 打满）"""
        import pymysql
        try:
            if self._conn and self._conn.open:
                self._conn.ping(reconnect=True)
                return self._conn
        except Exception:
            pass
        self._conn = pymysql.connect(host=MYSQL_HOST, port=int(MYSQL_PORT), user="root",
                                     password=MYSQL_ROOT_PWD, database="plant",
                                     charset="utf8mb4", autocommit=True)
        return self._conn

    async def load_alarm_state(self):
        """启动时把未恢复的报警载入内存状态机，避免重复产生报警"""
        try:
            cur = self._db().cursor()
            cur.execute("select site_id, point_code, id, val, threshold from alarm "
                        "where state in (0,1)")
            for site, code, aid, val, thr in cur.fetchall():
                direction = "上限" if (thr is None or (val or 0) >= (thr or 0)) else "下限"
                self.alarm_state[(site, code)] = direction
                self.alarm_ids[(site, code)] = aid
            log.info("载入未恢复报警 %d 条", len(self.alarm_ids))
        except Exception as e:
            log.warning("载入报警状态失败: %s", e)

    async def check_alarms(self, dev, vals):
        """内存状态机：只有状态翻转才落库，正常时零查询"""
        site = dev["site"]
        try:
            conn = self._db()
        except Exception as e:
            log.warning("报警判定连库失败: %s", e)
            return
        cur = conn.cursor()
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        for p in dev["points"]:
            v = vals.get(p["code"])
            if v is None:
                continue
            smax, smin = p["scale_max"], p["scale_min"]
            exceeded = None
            if smax is not None and v > smax + 1e-9:
                exceeded = ("上限", smax)
            elif smin is not None and v < smin - 1e-9 and smin > 0:
                exceeded = ("下限", smin)
            key = (site, p["code"])
            prev = self.alarm_state.get(key)
            if (exceeded[0] if exceeded else None) == prev:
                # 状态没变：只更新活跃报警的数值（合并成一次 UPDATE，避免刷库）
                if prev and self.alarm_ids.get(key):
                    cur.execute("update alarm set val=%s,last_ts=%s where id=%s",
                                (v, now, self.alarm_ids[key]))
                continue
            try:
                if exceeded:
                    if prev:
                        cur.execute("update alarm set state=0,val=%s,last_ts=%s,count=count+1 "
                                    "where id=%s", (v, now, self.alarm_ids[key]))
                    else:
                        cur.execute(
                            "insert into alarm(site_id,point_code,level,state,val,threshold,"
                            "msg,first_ts,last_ts,count) values (%s,%s,2,0,%s,%s,%s,%s,%s,1)",
                            (site, p["code"], v, exceeded[1],
                             f"{p['name'] or p['code']} 超出{exceeded[0]} {exceeded[1]}",
                             now, now))
                        aid = cur.lastrowid
                        self.alarm_ids[key] = aid
                        cur.execute("insert into alarm_event(alarm_id,site_id,point_code,"
                                    "action,val,ts) values (%s,%s,%s,'raise',%s,%s)",
                                    (aid, site, p["code"], v, now))
                        log.info("[报警产生] %s.%s = %s", site, p["code"], v)
                    self.alarm_state[key] = exceeded[0]
                else:
                    if prev:
                        cur.execute("update alarm set state=2,val=%s,last_ts=%s where id=%s",
                                    (v, now, self.alarm_ids.get(key)))
                        cur.execute("insert into alarm_event(alarm_id,site_id,point_code,"
                                    "action,val,ts) values (%s,%s,%s,'recover',%s,%s)",
                                    (self.alarm_ids.get(key), site, p["code"], v, now))
                        log.info("[报警恢复] %s.%s = %s", site, p["code"], v)
                    self.alarm_state[key] = None
            except Exception as e:
                log.warning("报警写库失败 %s.%s: %s", site, p["code"], e)

    def _clear_hist_cache(self, sid: str):
        """站点重载时清掉它的历史缓存（last_hist/last_q/last_q_ts）。
        点位删除后重建（编号相同）时，残留的 last_hist 会让死区判定
        「值没变」而永不写历史——实测踩过：子表被 DROP 后再也建不回来。"""
        for d in (self.last_hist, self.last_q, self.last_q_ts, self.last_hist_point_ts):
            for key in [k for k in d if k[0] == sid]:
                del d[key]

    def _collect_history_rows(self):
        """按站点/点位挑出本次要入库的采样点：死区过滤 + 断线 q=1 + 心跳兜底
           返回 [(site, code, val, q), ...]"""
        now = time.time()
        rows = []
        hb = now - self.last_hist_ts > HISTORY_HEARTBEAT
        for dev in self.sites.values():
            site = dev["site"]
            site_off = not dev["online"]
            for p in dev["points"]:
                # ---- store 开关：save_history=0 的点位完全不进历史（含断线补写）----
                if not p.get("save_history"):
                    continue
                code = p["code"]
                key = (site, code)
                # ---- 点位级入库间隔：没到自己的 hist_interval 就跳过 ----
                # 主循环仍每 SAMPLE_INTERVAL(5s) 跑一次做判断，这里只是不写历史，
                # 采集/实时值/SSE 完全不受影响。心跳(hb)不受间隔限制。
                iv = float(p.get("hist_interval") or HIST_INTERVAL_DEFAULT)
                if iv < 1:
                    iv = HIST_INTERVAL_DEFAULT
                if not hb and (now - self.last_hist_point_ts.get(key, 0)) < iv:
                    continue
                v = dev["values"].get(code)
                # ---- 断线保护：取不到值写 q=1，不写 0 冒充有效值 ----
                if v is None or site_off:
                    if self.last_q.get(key) != 1 or now - self.last_q_ts.get(key, 0) > HISTORY_HEARTBEAT:
                        rows.append((site, code, 0.0, 1))
                        self.last_q[key] = 1
                        self.last_q_ts[key] = now
                        self.last_hist_point_ts[key] = now
                    continue
                # ---- 死区：变化幅度小于 deadband（按量程百分比）不入库 ----
                last = self.last_hist.get(key)
                db_pct = float(p.get("deadband") or 0)
                span = max(abs(p.get("scale_max") or 100) + abs(p.get("scale_min") or 0), 1.0)
                if db_pct <= 0:
                    # 死区为 0（开关量）：只有真的变了才入库，避免每 5 秒刷一遍
                    changed = last is None or abs(v - last) > 1e-9
                else:
                    changed = last is None or (abs(v - last) / span * 100.0) >= db_pct
                if changed or hb or self.last_q.get(key) != 0:
                    rows.append((site, code, v, 0))
                    self.last_hist[key] = v
                    self.last_q[key] = 0
                    self.last_q_ts[key] = now
                    self.last_hist_point_ts[key] = now
        return rows

    async def _td_insert(self, rows):
        """一次批量插入（每批 HISTORY_BATCH 条），失败重试 3 次并记日志"""
        for i in range(0, len(rows), HISTORY_BATCH):
            chunk = rows[i:i + HISTORY_BATCH]
            parts = []
            for site, code, v, q in chunk:
                tbl = f"plant.d_{site}_{code}".lower()      # 子表名：小写、下划线
                parts.append(f"{tbl} using plant.samples tags('{site}','{code}') "
                             f"values (now, {v:.6f}, {q})")
            sql = "insert into " + " ".join(parts)
            for attempt in range(1, 4):
                try:
                    r = await self.td.post(TD_REST + "/rest/sql?db=plant", content=sql.encode())
                    data = r.json()
                    if data.get("code") == 0:
                        break
                    log.warning("TDengine 写入失败(第%d次) 站点=%s 点位=%s 返回=%s",
                                attempt, chunk[0][0], f"{chunk[0][1]}等{len(chunk)}点", data)
                except Exception as e:
                    log.warning("TDengine 写入异常(第%d次) 站点=%s 点位=%s 原因=%s",
                                attempt, chunk[0][0], f"{chunk[0][1]}等{len(chunk)}点", e)
                await asyncio.sleep(1.0 * attempt)

    async def write_history(self):
        """历史只进 TDengine：5s 一批，带死区 / 断线标记 / 重试 / 分批。
        last_hist_ts 只在真正写了行之后才刷新——否则每轮空跑也刷新，
        心跳兜底（60s 强制写一条）永远不会触发（实测踩过）。"""
        rows = self._collect_history_rows()
        if rows:
            await self._td_insert(rows)
            self.hist_written += len(rows)
            self.last_hist_ts = time.time()
            log.info("历史入库 %d 条（累计 %d）", len(rows), self.hist_written)

    async def run(self):
        self.rc = aioredis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)
        while True:
            try:
                await self.load_config()
                await self.load_alarm_state()
                break
            except Exception as e:
                log.warning("加载配置失败，10s 重试: %s", e)
                await asyncio.sleep(10)
        self._reload_lock = asyncio.Lock()
        # 心跳先起、采集后起：心跳是采集的前提（用户 2026-11 要求）
        self.hb_tasks = [asyncio.create_task(self._hb_loop(k)) for k in self.sites]
        self.tasks = [asyncio.create_task(self._loop(k)) for k in self.sites]
        self._site_tasks = dict(zip(self.sites, self.tasks))
        if not getattr(self, "_stats_started", False):
            self._stats_started = True
            asyncio.create_task(self._stats_loop())
        if not getattr(self, "_hb_started", False):
            self._hb_started = True
            asyncio.create_task(self.hb.ping_loop(lambda: self.sites))
        while True:
            try:
                await self.write_history()
            except Exception as e:
                log.warning("历史写入异常: %s", e)
            await asyncio.sleep(SAMPLE_INTERVAL)

    async def reload_config(self):
        """全量热重载：重读 site/point、整组重建采集协程（改配置后不用重启容器）

        不能 gather 干等：个别协程可能卡在 connect() 一类的底层调用上对取消
        不敏感，等到天荒地老配置也没换上。所以只等 15 秒，等不到就放行——
        旧协程带着代际标记，发现 gen 变了会自己退出，不会双份采集。
        """
        async with self._reload_lock:
            self.gen += 1
            old = list(self.tasks)
            self.tasks = []
            self._site_tasks = {}
            for t in old:
                t.cancel()
            if old:
                done, pending = await asyncio.wait(old, timeout=15)
                if pending:
                    log.warning("热重载：%d 个旧协程 15 秒未退出，不再等待", len(pending))
                else:
                    log.info("热重载：旧协程已全部退出")
            await self.load_config()
            await self.load_alarm_state()
            self.tasks = [asyncio.create_task(self._loop(k)) for k in self.sites]
            self.hb_tasks = [asyncio.create_task(self._hb_loop(k)) for k in self.sites]
            self._site_tasks = dict(zip(self.sites, self.tasks))
            log.info("配置已热重载：%d 个站点", len(self.sites))

    async def reload_site(self, sid: str):
        """单站点增量热重载（/internal/reload?site=，提示词 09 第 4 节）：
        只重建这一个站点的协程，别的站点采集不中断，站点闪断 <1s。"""
        async with self._reload_lock:
            old_task = self._site_tasks.pop(sid, None)
            if old_task:
                old_task.cancel()
            await self.load_config(only_site=sid)
            u = self.sites.get(sid)
            if not u:
                log.info("站点 %s 已停用/删除，采集协程退出", sid)
                return {"ok": True, "site": sid, "running": False}
            t = asyncio.create_task(self._loop(sid))
            self._site_tasks[sid] = t
            self.tasks.append(t)
            return {"ok": True, "site": sid, "running": True,
                    "points": len(u["points"]), "blocks": len(u["blocks"])}

    async def _hb_loop(self, sid):
        """独立心跳任务（用户 2026-11 要求：心跳挂在采集成功之前，站点建立后一直执行）。

        为什么不挂在采集之后：采集一停 → on_poll 不被调用 → hb_state 卡在 unknown →
        采集永远恢复不了（实测死锁）。心跳是采集的前提，必须独立于采集循环。

        modbus_echo：_echo() 用自建 Modbus 连接（hb_write_port/hb_read_port），
                     不占采集长连接，可安全独立跑；节流由 on_poll 内部的
                     hb_interval_s 负责。
        ping       ：由 hb.ping_loop 独立巡检，这里不重复。
        none       ：没有心跳，直接跳过（该站点永远不采集，见 _loop）。
        """
        dev = self.sites.get(sid)
        if dev is None:
            return
        gen = self.gen
        while self.gen == gen:
            try:
                mode = (dev.get("hb_mode") or "none").lower()
                if mode == "modbus_echo":
                    await self.hb.on_poll(dev, True)
            except Exception as e:
                log.warning("%s 心跳循环异常: %s", dev.get("site"), e)
            await asyncio.sleep(1.0)

    async def _loop(self, sid):
        """按**每个点位自己的采集周期**调度（用户 2026-11-13 要求）。

        规则：
          - 每个点位按自己 poll_ms 到期；没填 poll_ms 的跟随全站最小周期
          - 同一时刻到期的点位，**合并成一次读取**（块规划动态生成）
          - 例：A1=100ms / A2=300ms / A3=500ms
              t=100 → 只读 A1
              t=200 → 只读 A1
              t=300 → 读 A1 + A2（一起读，一次请求）
              t=400 → 只读 A1
              t=500 → 读 A1 + A3（一起读）
        这样既保证每个点位按自己的周期刷新，又不浪费合并读取的机会。
        """
        dev = self.sites[sid]
        site = dev["site"]
        gen = self.gen
        periods = dev.get("point_periods") or {}
        due = dev.get("point_due") or {}
        plan_fn = dev.get("plan_fn")
        by_code = {p["code"]: p for p in dev["points"]}
        if not periods or plan_fn is None:
            log.warning("%s 没有点位周期信息，跳过采集协程", site)
            return
        while self.gen == gen:
            # 站点离线：一律不执行采集（用户 2026-11 要求）。
            # 判定用独立心跳通道的 hb_state，不看采集自己的成功/失败：
            #   offline  → 明确离线，跳过本轮，不发任何 PLC 请求
            #   unknown  → 刚启动、心跳还没出结果，继续尝试（否则永远等不到恢复）
            #   online   → 正常采集
            # 恢复靠 hb.ping_loop，心跳回到 online 后这里自然继续。
            hb_mode = dev.get("hb_mode") or "none"
            # 采集的唯一前提：站点配了心跳，且心跳当前是 online（用户 2026-11 要求）。
            #   没配心跳（none）        → 永远不采集，一次 PLC 请求都不发
            #   心跳 offline / unknown  → 停采，等心跳自己恢复
            #   心跳 online             → 正常按 poll_ms 采集
            # 恢复完全依赖独立的 hb.ping_loop，采集侧不做任何探活重试。
            hb_state = dev.get("hb_state") or "unknown"
            if hb_mode == "none":
                dev["last_err"] = "站点未配置心跳，不采集"
                await asyncio.sleep(1.0)
                continue
            if hb_state != HB_ONLINE:
                # 停采点位，但**心跳探测必须继续**：否则 hb_state 永远停在 unknown，
                # 采集永远恢复不了（死锁，实测踩过）。
                # modbus_echo 的 _echo() 是自建连接，不占用采集长连接，可以独立跑；
                # ping 模式本来就由 ping_loop 独立巡检，这里不用管。
                dev["last_err"] = f"心跳 {hb_state}，采集已暂停"
                await asyncio.sleep(0.5)
                continue
            now = time.monotonic()
            ready = [c for c, t in due.items() if now >= t]
            if ready:
                # 到期点位 → 当场合并成最少的块（块规划是纯内存操作，微秒级）
                sel_pts = [by_code[c] for c in ready if c in by_code]
                blocks = plan_fn(sel_pts) if sel_pts else []
                t0 = time.monotonic()
                try:
                    if blocks:
                        await self.poll_blocks(sid, blocks)
                except Exception as e:
                    dev["online"] = False
                    dev["last_err"] = str(e)[:250]
                    log.warning("%s 采集异常: %s", site, e)
                cost = time.monotonic() - t0
                done_ts = time.monotonic()
                # 到期时间从"本轮读完"起算，慢点位不会越拖越后
                for c in ready:
                    pm = periods.get(c) or dev.get("base_ms") or SITE_POLL_MS
                    due[c] = done_ts + pm / 1000.0
                dev["stat"].append((time.time(), 1 if dev["online"] else 0,
                                    round(cost * 1000)))
                cut = time.time() - 300
                while dev["stat"] and dev["stat"][0][0] < cut:
                    dev["stat"].pop(0)
                dev["scan_ms"] = round(cost * 1000)
                dev["rounds"] = int(dev.get("rounds") or 0) + 1
            # 睡到最近的到期点（上限 0.5 秒，保证配置重载/退出能及时响应）
            nxt = min(due.values()) if due else time.monotonic() + 1.0
            await asyncio.sleep(min(0.5, max(0.001, nxt - time.monotonic())))

    async def _stats_loop(self):
        """02 通讯诊断：每 60s 把每个站点的成功率/响应写回 site 并落 comm_log；
        失败时即时补一行失败记录（去重到每分钟一条，防止一直失败刷爆表）。
        comm_log 只留 7 天，每小时清一次。"""
        while True:
            try:
                await asyncio.sleep(60)
                if not self.sites:
                    continue
                conn = self._db()
                cur = conn.cursor()
                now = time.strftime("%Y-%m-%d %H:%M:%S")
                for dev in self.sites.values():
                    stat = dev.get("stat") or []
                    ok_n = sum(1 for _, o, _ in stat if o)
                    total = len(stat)
                    succ = round(ok_n * 100.0 / total, 1) if total else None
                    lat = round(sum(l for _, _, l in stat) / total) if total else None
                    err = (dev.get("last_err") or "")[:250]
                    cur.execute("update site set succ_rate=%s, last_err=%s where id=%s",
                                (succ, err or None, dev["site"]))
                    cur.execute("insert into comm_log (site_id, ts, ok, latency_ms, err) "
                                "values (%s,%s,%s,%s,%s)",
                                (dev["site"], now, 1 if dev["online"] else 0, lat,
                                 err or None))
                conn.commit()
                conn.close()
                # 每小时清一次 7 天前的日志
                if time.strftime("%M") < "02" or not getattr(self, "_last_clean", 0):
                    self._last_clean = time.time()
                    conn = self._db()
                    cur = conn.cursor()
                    cur.execute("delete from comm_log where ts < date_sub(now(), interval 7 day)")
                    conn.commit()
                    conn.close()
            except Exception as e:
                log.warning("统计落库失败（不影响采集）: %s", e)

collector = Collector()

# ---------------- HTTP 服务 ----------------
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# —— 通讯参数内置常量（2026-11-12 起不再暴露给用户配置）——
# 为什么去掉：协议两端能通、能判在线/离线就够了。
# 采集周期/超时/重试/重连这四项，现场配错只会让采集变慢或打死 PLC 连接槽
# （506/507 排障时就吃过亏：UI 填 500，驱动里 max(1.0,...) 静默按 1000 跑，
#  用户以为设了 500 其实是 1000 —— 这种"静默改写"比不让配更糟）。
# 现在统一内置，UI 上不再出现，也不存在「改了没生效」。
COMM_TIMEOUT_MS = 3000        # 单次请求超时（毫秒）
COMM_TIMEOUT_S = 3.0          # 同上，秒
SITE_POLL_MS = 1000           # 站点采集循环间隔（毫秒）

app = FastAPI(title="Plant Gateway")

class WriteIn(BaseModel):
    site: str
    point: str
    value: float

@app.get("/api/ping")
async def ping():
    """轻量探活：不序列化实时值，供 /api/health 用"""
    return {"ok": True, "sites": len(collector.sites),
            "points": sum(len(d["points"]) for d in collector.sites.values()),
            "hist_written": collector.hist_written}


@app.get("/api/status")
async def status(full: int = 0):
    """采集状态；full=1 才带上全部实时值（20 万点位时序列化很贵，默认不带）。
    09 改造：一站点一台 PLC，输出键是 sites（backend /api/sites/status 按它消费）"""
    sites = []
    for sid in sorted(collector.sites):
        dev = collector.sites[sid]
        # 心跳模式开启时，在线状态以心跳判定为准（提示词 10）；none 沿用采集结果
        hb_mode = dev.get("hb_mode") or "none"
        online = (dev.get("hb_state") == HB_ONLINE) if hb_mode != "none" else dev["online"]
        d = {"site": sid, "online": online,
             "hb_mode": hb_mode, "hb_state": dev.get("hb_state") or "unknown",
             "round_requests": dev["round_requests"],
             # 上一轮整站扫描耗时（毫秒）—— 连续采集模式下这就是实际扫描周期
             "scan_ms": dev.get("scan_ms") or 0,
             "rounds": int(dev.get("rounds") or 0),
             "points": len(dev["points"]),
             "value_count": len(dev["values"]),
             "last_err": dev.get("last_err") or ""}
        if full:
            d["values"] = {k: round(v, 3) for k, v in dev["values"].items()}
        sites.append(d)
    return {"sites": sites, "ts": int(time.time() * 1000),
            "hist_written": collector.hist_written,
            "sample_interval": SAMPLE_INTERVAL}

@app.post("/write")
async def write_point(body: WriteIn):
    """写 PLC + 200ms 后回读校验（浮点用 eps 比较）。
    09 改造：一站点一台 PLC，站点即单元，不再有 device_id。"""
    dev = collector.sites.get(body.site)
    if not dev:
        # 最常见的原因不是"站点没了"，而是站点的「所属网关」不是本网关。
        # 直接说清是哪个网关在采、本网关是谁，比报「站点不存在」好查一百倍。
        raise HTTPException(
            404,
            f"本网关（{GATEWAY_ID}）没有采集站点 {body.site}。"
            f"请到「站点管理」确认该站点的「所属网关」是不是 {GATEWAY_ID}，"
            f"以及那个网关的容器是否在运行")
    p = next((x for x in dev["points"] if x["code"] == body.point), None)
    if not p:
        raise HTTPException(
            404,
            f"点位 {body.point} 不在站点 {body.site} 的采集列表里"
            f"（共 {len(dev['points'])} 个点位）。"
            f"可能是点位被停用，或网关加载的还是旧配置——改完点位后请重新保存一次站点触发重载")
    if p["rw"] != 1:
        raise HTTPException(400, "点位只读")

    # ---- S7 · S7-200 SMART：S7comm 同步 socket 丢线程池，写后同样 200ms 回读校验 ----
    if dev.get("driver") == "s7smart":
        sc = dev["client"]

        def _s7_write():
            area, db, off, sz, bit = s7_span(p)
            if bit is not None or p["dtype"] == "bool":
                sc.write_bit_raw(area if area != "DB" else "V", off,
                                 bit if bit is not None else 0, bool(body.value))
                return
            if sz == 1:
                # byte / bool 走 1 字节。不处理会掉到下面的 float32 分支，
                # 一次写 4 个字节，把后面 3 个字节的现场数据全部踩掉。
                data = struct.pack(">B", int(body.value) & 0xFF)
            elif sz == 2:
                data = struct.pack(">H", int(body.value) & 0xFFFF if p["dtype"] == "uint16"
                                   else int(body.value))
            else:
                data = (struct.pack(">i", int(body.value))
                        if p["dtype"] in ("int32", "uint32")
                        else struct.pack(">f", float(body.value)))
            if area == "V":
                sc.write_v(off, data)
            elif area == "DB":
                sc.write_db(db, off, data)
            else:
                sc.write_raw(area, off, data)

        def _s7_readback():
            area, db, off, sz, bit = s7_span(p)
            if area == "V":
                raw = sc.read_v(off, sz)
            elif area == "DB":
                raw = sc.read_db(db, off, sz)
            else:
                raw = sc.read_raw(area, off, sz)
            return decode_s7(p["dtype"], raw, bit)

        # 不能只判 sc.cli 是否 None：断线后对象还在，但 get_connected() 是 False，
        # 这时直接写会被 _need() 抛「未连接，先 connect()」。
        if not sc.cli or not sc.cli.get_connected():
            try:
                await collector._io_call(dev, sc.connect)
            except Exception as e:
                raise HTTPException(502, f"S7 连接失败：{e}")
        try:
            await collector._io_call(dev, _s7_write)
        except HTTPException:
            raise
        except Exception as e:
            # snap7 的 get_connected() 在 TCP 半开连接上仍然返回 True，
            # 只有真写的时候才抛 Not connected。这种情况重连一次再写，
            # 比直接把「未连接，先 connect()」丢给现场操作员有用得多。
            msg = str(e).lower()
            if "not connected" in msg or "未连接" in msg:
                try:
                    await collector._io_call(dev, sc.connect)
                    await collector._io_call(dev, _s7_write)
                except Exception as e2:
                    raise HTTPException(500, f"写入失败（自动重连后仍失败）：{e2}")
            else:
                raise HTTPException(500, f"写入失败：{e}")
        await asyncio.sleep(0.2)
        try:
            back = await collector._io_call(dev, _s7_readback)
        except Exception as e:
            # 网络刚恢复的一瞬间 socket 还是半开的（EAGAIN / Not connected），
            # 回读同样需要重连重试 —— 否则写成功了却因为回读失败报错，
            # 现场会以为没写进去，实际已经写进去了。
            try:
                await collector._io_call(dev, sc.connect)
                await asyncio.sleep(0.05)
                back = await collector._io_call(dev, _s7_readback)
            except Exception as e2:
                raise HTTPException(500, f"回读失败（自动重连后仍失败）：{e2}")
        if not near(back, float(body.value)):
            raise HTTPException(400, f"回读不一致：写入{body.value} 读回{back}")
        return {"ok": True, "value": back}

    # ---- MC · FX3U 1E 帧：同步 socket 丢线程池，写后同样 200ms 回读校验 ----
    if dev.get("driver") == "mc1e":
        mc = dev["client"]

        def _mc_write():
            dev_, num, is_word = _mc3(p["addr"])
            if not is_word:
                mc.write_bit(dev_, num, bool(body.value))
                return
            if p["dtype"] in ("uint16", "int16", "byte"):
                mc.write_words(dev_, num, [int(body.value) & 0xFFFF])
            elif p["dtype"] == "float32":
                w0, w1 = struct.unpack("<HH", struct.pack("<f", float(body.value)))
                mc.write_words(dev_, num, [w0, w1])
            else:
                raise HTTPException(400, "该点位类型暂不支持写入")

        def _mc_readback():
            dev_, num, is_word = _mc3(p["addr"])
            if not is_word:
                return float(mc.read_bits(dev_, num, 1)[0])
            words = mc.read_words(dev_, num, max(1, type_size(p["dtype"]) // 2))
            return decode_mc(p["dtype"], words, p.get("byte_order"))

        # socket 对象还在但连接已断（fileno 变 -1）时也要重连，
        # 否则 sendall 会抛 BrokenPipe 而不是给出可操作的错误。
        _mdead = (mc.sock is None) or (getattr(mc.sock, "fileno", lambda: -1)() < 0)
        if _mdead:
            try:
                await collector._io_call(dev, mc.connect)
            except Exception as e:
                raise HTTPException(502, f"MC 连接失败：{e}")
        try:
            await collector._io_call(dev, _mc_write)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"写入失败：{e}")
        await asyncio.sleep(0.2)
        try:
            back = await collector._io_call(dev, _mc_readback)
        except Exception as e:
            raise HTTPException(500, f"回读失败：{e}")
        if not near(back, float(body.value)):
            raise HTTPException(400, f"回读不一致：写入{body.value} 读回{back}")
        return {"ok": True, "value": back}

    c: AsyncModbusTcpClient = dev["client"]
    addr = _mb_reg(dev["protocol"], p["addr"])
    if p["dtype"] in ("uint16", "int16", "bool", "byte"):
        raw = int(body.value)
        rr = await c.write_register(addr, raw, slave=dev["slave_id"])
    else:
        raise HTTPException(400, "该点位类型暂不支持写入")
    if rr.isError():
        raise HTTPException(500, "写入失败")
    await asyncio.sleep(0.2)
    rb = await c.read_holding_registers(addr, 1, slave=dev["slave_id"])
    if rb.isError():
        raise HTTPException(500, "回读失败")
    back = float(rb.registers[0])
    if not near(back, float(body.value)):
        raise HTTPException(400, f"回读不一致：写入{body.value} 读回{back}")
    return {"ok": True, "value": back}

@app.post("/api/reload")
async def reload_cfg():
    """全量热重载：重读 site/point、整组重建采集协程，不用重启容器"""
    if collector._reload_lock is None:
        return {"ok": False, "error": "采集循环还没启动"}
    await collector.reload_config()
    return {"ok": True, "sites": len(collector.sites),
            "points": sum(len(d["points"]) for d in collector.sites.values())}


@app.post("/internal/reload")
async def reload_one(site: str = ""):
    """后端配置变更后的通知入口（backend notify_reload 调这里）：
    带 site 参数只重载该站点（其他站点采集不中断）；不带参数全量重载。"""
    if collector._reload_lock is None:
        return {"ok": False, "error": "采集循环还没启动"}
    if site:
        return await collector.reload_site(site)
    await collector.reload_config()
    return {"ok": True, "sites": len(collector.sites),
            "points": sum(len(d["points"]) for d in collector.sites.values())}

@app.on_event("startup")
async def startup():
    asyncio.create_task(collector.run())


# ---------------- 02 通讯诊断 / 测试连接 ----------------

@app.get("/api/devstatus")
async def devstatus():
    """按站点粒度的实时状态（列表页状态点、诊断页用）。
    09 改造：一站点一台 PLC，id 就是站点编号。"""
    items = []
    for sid in sorted(collector.sites):
        dev = collector.sites[sid]
        stat = dev.get("stat") or []
        total = len(stat)
        ok_n = sum(1 for _, o, _ in stat if o)
        hb_mode = dev.get("hb_mode") or "none"
        items.append({
            "id": sid, "site": sid,
            "online": (dev.get("hb_state") == HB_ONLINE) if hb_mode != "none" else dev["online"],
            "hb_mode": hb_mode, "hb_state": dev.get("hb_state") or "unknown",
            "round_requests": dev["round_requests"],
            "succ_rate": round(ok_n * 100.0 / total, 1) if total else None,
            "latency_ms": round(sum(l for _, _, l in stat) / total) if total else None,
            "last_err": dev.get("last_err") or "",
            "points": len(dev["points"])})
    return {"items": items}


class TestConnIn(BaseModel):
    """测试连接入参：表单里现填的参数直接测（不要求先保存设备）"""
    protocol: str            # modbus_tcp / s7 / mc / fins / opcua / cip
    ip: str
    port: int = 0
    slave_id: int = 1
    rack: int = 0
    slot: int = 1
    series: str = ""
    proto_params: dict = {}
    addr: str = ""           # 测试地址；空则按协议给默认
    dtype: str = "float32"   # 手动选的数据类型：bool/uint16/int16/uint32/int32/float32
    timeout_ms: int = COMM_TIMEOUT_MS   # 固定值，测试不再让人填


def _hint(e, protocol, ip, port):
    """把底层异常翻译成一句现场能执行的排查建议——"未知错误"帮不了任何人"""
    msg = str(e)
    low = msg.lower()
    if isinstance(e, ConnectionRefusedError) or "refused" in low:
        return f"IP {ip} 可达但端口 {port} 拒绝连接：检查 PLC 以太网模块端口设置与防火墙"
    if "unreachable" in low or "no route" in low or "network is unreachable" in low:
        return f"到 {ip} 没有路由：检查网线/交换机/VLAN/网关配置"
    if isinstance(e, (TimeoutError, asyncio.TimeoutError)) or "timed out" in low or "timeout" in low:
        return f"连接/读数超时：ping {ip} 确认可达；确认端口 {port}、协议与品牌匹配（不是别的协议占着这个端口）"
    if "connection" in low and "reset" in low:
        if protocol == "s7":
            return ("PLC 在 102 口把 S7 会话重置了：①协议参数里「连接类型」换成 OP"
                    "（PG 连接资源常被 Micro/WIN SMART 在线占满）②S7-200 SMART 的"
                    " rack/slot 必须 0/1 ③确认没连错设备（用浏览器开 http://IP/ 看是不是西门子）")
        return "连接被对端重置：多半是协议不对（用 Modbus 客户端去连了 S7 口之类）或连接数超限"
    if "module" in low and "not installed" in low:
        return "驱动库未安装，容器内 pip install 后重建网关镜像"
    return "检查 IP/端口/协议/从站号是否与现场一致；用 PLC 编程软件确认通讯参数"


async def _test_modbus(ip, port, p):
    from pymodbus.client import AsyncModbusTcpClient
    tmo = max(1.0, (getattr(p, "timeout_ms", 3000) or 3000) / 1000)
    c = AsyncModbusTcpClient(ip, port=port or 502, timeout=tmo)
    if not await c.connect():
        raise ConnectionError(f"无法建立到 {ip}:{port or 502} 的 TCP 连接")
    try:
        a = p.addr or "40001"
        n = int("".join(ch for ch in a if ch.isdigit()) or 0)
        base = int((p.proto_params or {}).get("reg_base") or 0)
        off = n - 40001 + base if 40001 <= n < 50000 else n
        nreg = {"bool": 1, "byte": 1, "uint16": 1, "int16": 1, "uint32": 2,
                "int32": 2, "float32": 2, "float64": 4}.get(p.dtype, 2)
        rr = await c.read_holding_registers(off, nreg, slave=p.slave_id)
        if rr.isError():
            raise IOError(f"读保持寄存器 {off} 失败: {rr}")
        order = (p.proto_params or {}).get("byte_order") or "CDAB"
        return {"read_value": round(float(decode_val(p.dtype, rr.registers, order)), 3),
                "raw": list(rr.registers)}
    finally:
        c.close()   # pymodbus 3.7 异步客户端的 close() 是同步方法，await 它 = await None


def _test_s7(ip, rack, slot, p):
    """S7-200 SMART 用 skill 驱动（S7200SMART）：V 区=DB1、大端、0x8104 容错。
    旧实现的坑都修掉：
    1) Client.connect 第 4 参是 TCP 端口，旧代码传了 pdu_size=480 → 全部连不上；
    2) `from snap7.type import Areas` 在 3.x 不存在 → M/I/Q 直接崩；
    3) 浮点用 <f 小端解 → VD 真值读成 ~0；
    4) 协议参数里的「连接类型」没被使用 → 死用 PG，PG 被 PLC 重置就误报连不上；
    5) rack/slot 直接信设备表 → 填成 1/0 时必挂（S7-200 SMART 恒为 0/1）。"""
    from s7_200smart import S7200SMART, S7Error
    addr = (p.addr or "VD0").strip()
    dtype = p.dtype or "float32"
    try:
        # 字节数按「地址写法」与「数据类型」取大（VB1006 + uint16 要读 2 字节）
        area, db, off, sz, bit = s7_span({"addr": addr, "dtype": dtype})
    except ValueError as e:
        return {"ok": False, "error": str(e),
                "hint": "合法示例：VD1000 / VW100 / VB0 / V1000.3 / M10.1 / IW0 / QW2 / DB1.DBW0"}
    rack, slot = s7_rack_slot(p.series, rack, slot)
    want_conn = s7_conn_type(p.proto_params)
    # 超时用测试弹窗里填的临时值（不再写死 3 秒：改了超时时间必须有反应）
    try:
        to_s = max(1.0, float(getattr(p, "timeout_ms", 3000) or 3000) / 1000.0)
    except (TypeError, ValueError):
        to_s = 3.0
    plc = S7200SMART(ip, rack=rack, slot=slot, port=102, timeout_s=to_s,
                     conn_type=want_conn)
    try:
        plc.connect()
    except S7Error as e:
        return {"ok": False, "error": str(e),
                "hint": "PLC 在 102 口把连接重置了（TCP 能通、S7 会话被拒）。"
                        "常见：①PG 连接资源被 Micro/WIN SMART 在线占满 → 参数里把"
                        "「连接类型」改成 OP；②rack/slot 不是 0/1；③CPU 系统块里禁用了"
                        "S7 通讯或连接资源设成 0"}
    try:
        if area == "V":
            raw = plc.read_v(off, sz)
        elif area == "DB":
            raw = plc.read_db(db, off, sz)
        else:
            raw = plc.read_raw(area, off, sz)
        val = decode_s7(dtype, raw, bit)
        out = {"read_value": round(float(val), 3), "raw": list(raw),
               "conn_type": plc.conn_type_used}
        if plc.conn_type_used and plc.conn_type_used != want_conn:
            out["note"] = ("首选 %s 连接被 PLC 重置，已自动改用 %s 连上"
                           % (want_conn, plc.conn_type_used))
        return out
    except S7Error as e:
        return {"ok": False, "error": str(e), "hint": "S7 读数失败：确认 PLC 在 RUN、"
                "V 区偏移没越界（V 区总量见 Micro/WIN SMART 系统块）"}
    finally:
        plc.close()   # 单连接，测完必关（S7comm 连接资源同样有限）


def _test_mc(ip, port, p):
    """MC 测试连接分两条路：
    - FX3U/FX5U（ENET-ADP）：只支持 A 兼容 1E 帧，必须走 fx3u_adp_mc.FX3U_ADP。
      pymcprotocol 的 3E 帧会被 ADP 静默拒绝（真值 2.653 读回 [0,0] 不报错），
      绝不能用于 FX3U——2026-11-09 实测踩过。判定见 mc_use_1e()：系列是 FX
      或协议参数里帧格式选了 1E 都算。
    - Q/L/iQ-R 系列：pymcprotocol 3E/4E 帧。"""
    import struct as _s
    if mc_use_1e(p.series, p.proto_params):
        from fx3u_adp_mc import FX3U_ADP, MCError
        # 🔴 ADP 的每个 MC 口只认一个连接：采集循环长连接占着一个口时，
        # 测试连接同口会得到 0 字节响应。按 4999/5000/5001 轮着试，谁通用谁。
        want = port or 4999
        ports = [want] + [q for q in (4999, 5000, 5001) if q != want]
        last_err = None
        for pt in ports:
            plc = FX3U_ADP(ip, pt, timeout=3.0)
            try:
                plc.connect()
                addr = p.addr or "D0"
                dev, num, is_word = _mc3(addr)
                if not is_word:
                    bits = plc.read_bits(dev, num, 1)
                    return {"read_value": bits[0], "raw": bits, "port": pt}
                if p.dtype == "bool":
                    return {"read_value": plc.read_words(dev, num, 1)[0] & 1,
                            "raw": None, "port": pt}
                n = 2 if p.dtype in ("uint32", "int32", "float32") else 1
                words = plc.read_words(dev, num, n)
                if n == 1:
                    v = words[0]
                    if p.dtype == "int16" and v >= 0x8000:
                        v -= 0x10000
                    return {"read_value": v, "raw": words, "port": pt}
                # 三菱 32 位量低字在前
                fmt = {"float32": "<f", "int32": "<i", "uint32": "<I"}[p.dtype]
                val = _s.unpack(fmt, _s.pack("<HH", words[0], words[1]))[0]
                return {"read_value": round(float(val), 3), "raw": words, "port": pt}
            except MCError as e:
                last_err = e
                if "0 字节" not in str(e):
                    # 协议级拒绝（56H/57H…），换口也没用，直接报
                    return {"ok": False, "error": str(e), "hint": "1E 帧被 PLC 拒绝："
                            "检查 ADP 通信数据代码是否为二进制、软元件名/编号是否正确"}
                # 0 字节 = 这个口被占（多半是采集长连接），换下一个口
            finally:
                plc.close()   # 单连接，测完必关（ADP 只有 3 个 MC 槽）
        return {"ok": False, "error": str(last_err),
                "hint": "4999/5000/5001 三个口都无响应：ADP 的 3 个 MC 连接可能全被占用"
                        "（采集循环 + 其他客户端），等几秒再试；或确认 PLC 在 RUN"}
    import pymcprotocol
    mc = pymcprotocol.Type3E()
    if (p.proto_params or {}).get("frame") == "4E":
        mc = pymcprotocol.Type4E()
    mc.connect(ip, port or 5000)
    try:
        addr = p.addr or "D0"
        prefix = "".join(ch for ch in addr if ch.isalpha()).upper() or "D"
        num = int("".join(ch for ch in addr if ch.isdigit()) or 0)
        n = 2 if p.dtype in ("uint32", "int32", "float32") else 1
        words = mc.batchread_wordunits(f"{prefix}{num}", n)
        if n == 1:
            v = words[0]
            if p.dtype == "int16" and v >= 0x8000:
                v -= 0x10000
            return {"read_value": v, "raw": words}
        fmt = {"float32": "<f", "int32": "<i", "uint32": "<I"}[p.dtype]
        val = _s.unpack(fmt, _s.pack("<2H", words[0], words[1]))[0]
        return {"read_value": round(float(val), 3), "raw": words}
    finally:
        mc.close()


def _test_fins(ip, port, p):
    from fins import FinsClient
    fc = FinsClient(host=ip, port=port or 9600, timeout=4,
                    mode=(p.proto_params or {}).get("transport") or "tcp")
    fc.connect()
    try:
        addr = p.addr or "D0"
        r = fc.memory_area_read(addr, 2)
        data = bytes(getattr(r, "data", r) or b"")
        import struct as _s
        val = _s.unpack(">f", data[:4])[0] if len(data) >= 4 else None
        return {"read_value": round(val, 3) if val is not None and abs(val) < 1e12 else None,
                "raw": list(data[:8])}
    finally:
        fc.close()


@app.post("/api/testconn")
async def testconn(p: TestConnIn):
    """测试连接：按协议用现成库真连一次、真读一次。同步库放线程池，别堵事件循环。"""
    t0 = time.monotonic()
    proto = (p.protocol or "").lower()
    if proto in ("mc_1e", "mc_3e"):      # 协议别名归一（前端下拉存的写法）
        proto = "mc"
    try:
        if proto in ("modbus_tcp", "modbus_rtu"):
            out = await _test_modbus(p.ip, p.port, p)
        elif proto == "s7":
            out = await asyncio.to_thread(_test_s7, p.ip, p.rack, p.slot, p)
        elif proto == "mc":
            out = await asyncio.to_thread(_test_mc, p.ip, p.port, p)
        elif proto == "fins":
            out = await asyncio.to_thread(_test_fins, p.ip, p.port, p)
        elif p.protocol == "opcua":
            from asyncua import Client
            url = (p.proto_params or {}).get("endpoint") or f"opc.tcp://{p.ip}:{p.port or 4840}"
            async with Client(url=url, timeout=4) as cl:
                node = cl.get_node((p.proto_params or {}).get("nodeid_prefix", "ns=2;s=") + (p.addr or "Demo.Static"))
                v = await node.read_value()
            out = {"read_value": v if isinstance(v, (int, float)) else str(v), "raw": None}
        else:
            raise HTTPException(400, f"暂不支持测试的协议: {p.protocol}")
        # 驱动自己判失败（返回 ok:False）时不能再盖成 True——
        # 之前 out.update(ok=True) 把 MCError 的失败洗成成功，read_value 也丢了
        lat = round((time.monotonic() - t0) * 1000)
        if out.get("ok") is False:
            out.setdefault("latency_ms", lat)
            out.setdefault("error", "读取失败")
            out.setdefault("hint", "")
        else:
            out.update(ok=True, latency_ms=lat, error="", hint="")
        return out
    except Exception as e:
        return {"ok": False, "latency_ms": round((time.monotonic() - t0) * 1000),
                "read_value": None, "error": str(e)[:300], "hint": _hint(e, p.protocol, p.ip, p.port)}
