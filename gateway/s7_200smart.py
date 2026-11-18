# -*- coding: utf-8 -*-
"""
西门子 S7-200 SMART 采集驱动（S7comm over TCP 102）

实测参数：x.x.x.x，rack=0，slot=1，端口 102
V 区 = DB1，偏移 = V 地址号（VD1000 → db_read(1, 1000, 4)）
字节序：大端（ABCD），REAL 用 >f

连接类型：PG / OP / S7basic 三种，远程 TSAP 不同
    PG(1)      → 0x0100 + rack*0x20 + slot
    OP(2)      → 0x0200 + rack*0x20 + slot
    S7basic(3) → 0x0300 + rack*0x20 + slot
2026-11-09 实测（x.x.x.x）：PG 被 PLC 直接 RST（Connection reset by peer），
OP / S7basic 均能连上并读到 DB1.DBD1000。所以 connect() 按「首选 → OP → PG → S7basic」
依次回退，不再因为一个连接类型被拒就判定"连不上"。

实测：VD1000 = 44.335（历史值），2026-11-09 现场为 32.768
"""
import logging
import struct
import time

log = logging.getLogger("s7_200smart")

try:
    from snap7 import Client, Area
except ImportError as e:      # pragma: no cover
    raise ImportError("需要 python-snap7：pip install python-snap7") from e

try:
    from snap7.type import Parameter      # 3.4+ 才有；老的没有就按驱动默认超时
except ImportError:                       # pragma: no cover
    Parameter = None

# snap7 的 Cli_SetConnectionType：1=PG、2=OP、3=basic
CONN_TYPES = {"PG": 1, "OP": 2, "S7BASIC": 3, "BASIC": 3, "S7_BASIC": 3}
CONN_TYPE_NAMES = {1: "PG", 2: "OP", 3: "S7basic"}
# 回退顺序：首选之外，先 OP（实测 S7-200 SMART 上最稳），再 PG，最后 basic
FALLBACK_ORDER = ("OP", "PG", "S7basic")


def norm_conn_type(v):
    """把界面上的连接类型字符串归一成 PG / OP / S7basic；空值默认 OP"""
    s = str(v or "").strip().upper().replace("-", "").replace(" ", "")
    if s in ("PG",):
        return "PG"
    if s in ("OP",):
        return "OP"
    if s in ("S7BASIC", "BASIC", "S7_BASIC"):
        return "S7basic"
    return "OP"


class S7Error(Exception):
    pass


def parse_tsap(v):
    """'0x0201' / '0x201' / 513 / '513' → int；空 → None（None = 交给 snap7 自动算）

    为什么允许 None：不填 TSAP 时按 rack/slot/conn_type 自动算（snap7 的标准行为），
    填了就用填的、且不再回退连接类型 —— 填错就该连不上，不做"自动纠正"。
    """
    if v is None or v == "":
        return None
    if isinstance(v, int):
        return v if 0 <= v <= 0xFFFF else None
    t = str(v).strip()
    if not t:
        return None
    try:
        n = int(t, 16) if t.lower().startswith("0x") else int(t)
    except ValueError:
        return None
    return n if 0 <= n <= 0xFFFF else None


class S7200SMART:
    """S7-200 SMART 客户端（V 区 / M / I / Q）

    用法:
        plc = S7200SMART("x.x.x.x")
        plc.connect()
        print(plc.read_real(1000))      # VD1000 = 44.335
        print(plc.read_int(1000))       # VW1000
        print(plc.read_bit(1000, 0))    # V1000.0
        plc.close()
    """

    DB_V = 1          # S7-200 SMART 的 V 区固定映射到 DB1


    def __init__(self, ip, rack=0, slot=1, port=102, timeout_s=3.0, conn_type="OP",
                 local_tsap=None, remote_tsap=None, pdu_size=None, max_conn=1):
        self.ip = ip
        self.rack = rack
        self.slot = slot
        self.port = port
        self.timeout_s = timeout_s
        self.conn_type = norm_conn_type(conn_type)   # 首选连接类型
        # 显式 TSAP（None = 按 rack/slot/conn_type 自动算，snap7 标准行为）
        self.local_tsap = parse_tsap(local_tsap)
        self.remote_tsap = parse_tsap(remote_tsap)
        # PDU 提议值（None = snap7 默认 480）；PLC 仍会回自己的上限，取小的
        try:
            self.pdu_size = int(pdu_size) if pdu_size not in (None, "") else None
        except (TypeError, ValueError):
            self.pdu_size = None
        # 最大连接数（驱动层并发度）。默认 1 = 严格串行。
        # S7-200 SMART 的以太网口对编程/HMI 连接数有限制，多个连接同时问同一个
        # CPU 会让响应错序（Stale packet），所以默认压到 1，允许站点里按实际组态调大。
        try:
            self.max_conn = max(1, int(max_conn or 1))
        except (TypeError, ValueError):
            self.max_conn = 1
        self.conn_type_used = None                   # 实际连上的类型
        self.conn_tried = []                         # 依次试过哪些、各自的错误
        self.cli = None
        self.last_error = ""

    # ---------- 连接 ----------

    def connect(self):
        """按「首选 → OP → PG → S7basic」依次试，谁通用谁。

        S7-200 SMART 每种连接类型各占一份连接资源，PG 资源常被 Micro/WIN SMART
        在线占用，此时新 PG 连接会被 PLC 直接重置（RST，无任何 COTP 回应）。
        只试一种就会误报"连不上"，这里必须回退。
        """
        self.close()
        # 显式填了 TSAP 就只试填的那一种连接类型：
        # TSAP 里已经编了连接类型（0x01xx=PG / 0x02xx=OP / 0x03xx=basic），
        # 回退到别的类型但 TSAP 不变 → 必然连不上，只会把错误信息搅乱。
        # 用户要求"填写错误直接通讯失败"，这里就按他的意思来。
        explicit = (self.local_tsap is not None and self.remote_tsap is not None)
        if explicit:
            order = [self.conn_type]
        else:
            order = [self.conn_type] + [n for n in FALLBACK_ORDER if n != self.conn_type]
        self.conn_tried = []
        # 单次尝试卡 2s 上限：PLC 拒连时表现为 TCP 连接超时，三种类型全试一遍
        # 不能拖到 15s（后端代理 20s 超时，会变成 502 而不是可读的失败原因）
        per_try_ms = int(min(max(self.timeout_s, 1.0), 2.0) * 1000)
        for name in order:
            cli = Client()
            try:
                cli.set_connection_type(CONN_TYPES[name])
            except Exception:
                pass      # 老版本绑定没有这个接口，按驱动默认走
            for param in ("SendTimeout", "RecvTimeout"):
                try:
                    cli.set_param(getattr(Parameter, param), per_try_ms)
                except Exception:
                    pass
            # PDU 提议值要在建会话之前设：_setup_communication() 用它当 ClientPduLength
            if self.pdu_size:
                try:
                    cli.pdu_length = self.pdu_size
                except Exception:
                    pass
            try:
                if explicit:
                    # set_connection_params 之后再调 connect() 会被覆盖（client.py:451 重算
                    # remote_tsap），所以走 _connect()：它明确用已设的 TSAP 建会话。
                    cli.set_connection_params(self.ip, self.local_tsap, self.remote_tsap)
                    cli._connect(self.ip, self.rack, self.slot, self.port)
                else:
                    cli.connect(self.ip, self.rack, self.slot, self.port)
            except Exception as e:
                # 有些版本 connect 内部会查 CPU 信息（USERDATA 0x8104），
                # S7-200 SMART 不支持；此时 COTP 其实已建立，二次确认后继续
                self.last_error = "%s: %s" % (type(e).__name__, e)
                try:
                    ok = bool(cli.get_connected())
                except Exception:
                    ok = False
                if not ok:
                    self.conn_tried.append("%s→%s" % (name, self.last_error))
                    try:
                        cli.destroy()
                    except Exception:
                        pass
                    continue
            # 强制串行：snap7 3.4 会按协商出的 PDU 大小自动调并行度
            # （PDU=240 时给 2），多块读取就背靠背发两个 PDU。
            # S7-200 SMART 缓冲小，第二个响应会和第一个错序，触发
            # "Stale packet: expected sequence X, got Y" → 重试 → Receive timeout，
            # 那一块的所有点位就停更了，前端判 stale 显示 "--"。
            # S7 协议本身是「单连接严格串行」的，这里必须压回 1。
            try:
                cli.max_parallel = self.max_conn
                log.info("[S7] max_parallel 设为 %d（站点配置 max_conn=%s）",
                         self.max_conn, self.max_conn)
            except Exception as e:
                log.warning("[S7] 设置 max_parallel 失败: %s", e)
            self.cli = cli
            self.conn_type_used = name
            return self
        detail = "；".join(self.conn_tried) or "无响应"
        raise S7Error("连接失败（已依次尝试 %s）：%s" % ("/".join(order), detail))

    def close(self):
        if self.cli is not None:
            try:
                self.cli.disconnect()
            except Exception:
                pass
            try:
                self.cli.destroy()
            except Exception:
                pass
            self.cli = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *a):
        self.close()

    def _need(self):
        if self.cli is None or not self.cli.get_connected():
            raise S7Error("未连接，先 connect()")

    # ---------- V 区（DB1）----------
    def read_v(self, offset, size):
        """读 V 区原始字节（offset = 字节地址，如 VB1000 → 1000）"""
        self._need()
        try:
            return self.cli.db_read(self.DB_V, offset, size)
        except Exception as e:
            raise S7Error("读 V%d(%d字节) 失败：%s" % (offset, size, e))

    def write_v(self, offset, data):
        self._need()
        try:
            self.cli.db_write(self.DB_V, offset, data)
        except Exception as e:
            raise S7Error("写 V%d 失败：%s" % (offset, e))

    # ---------- 类型化读 ----------
    def read_real(self, offset):
        """VD → 单精度浮点（大端 IEEE754）"""
        return struct.unpack(">f", self.read_v(offset, 4))[0]

    def read_dint(self, offset):
        return struct.unpack(">i", self.read_v(offset, 4))[0]

    def read_dword(self, offset):
        return struct.unpack(">I", self.read_v(offset, 4))[0]

    def read_int(self, offset):
        return struct.unpack(">h", self.read_v(offset, 2))[0]

    def read_word(self, offset):
        return struct.unpack(">H", self.read_v(offset, 2))[0]

    def read_bool(self, offset, bit=0):
        """V1000.0 → read_bool(1000, 0)"""
        byte = self.read_v(offset, 1)[0]
        return bool(byte & (1 << bit))

    def read_reals(self, offset, count):
        """一次读 count 个连续 REAL（减少请求数）"""
        data = self.read_v(offset, 4 * count)
        return list(struct.unpack(">" + "f" * count, data))

    def read_words(self, offset, count):
        data = self.read_v(offset, 2 * count)
        return list(struct.unpack(">" + "H" * count, data))

    def read_string(self, offset, max_len=32):
        """V 区字符串（首字节为长度）"""
        raw = self.read_v(offset, max_len + 2)
        n = min(raw[1], max_len)
        return raw[2:2 + n].decode("gbk", errors="replace")

    # ---------- 类型化写 ----------
    def write_real(self, offset, value):
        self.write_v(offset, struct.pack(">f", float(value)))

    def write_dint(self, offset, value):
        self.write_v(offset, struct.pack(">i", int(value)))

    def write_int(self, offset, value):
        self.write_v(offset, struct.pack(">h", int(value)))

    def write_bool(self, offset, bit, on=True):
        cur = bytearray(self.read_v(offset, 1))
        if on:
            cur[0] |= (1 << bit)
        else:
            cur[0] &= ~(1 << bit)
        self.write_v(offset, bytes(cur))

    # ---------- M / I / Q ----------
    def read_m(self, start, size):
        self._need()
        return self.cli.read_area(Area.MK, 0, start, size)

    def read_i(self, start, size):
        self._need()
        return self.cli.read_area(Area.PE, 0, start, size)

    def read_q(self, start, size):
        self._need()
        return self.cli.read_area(Area.PA, 0, start, size)

    def read_m_bool(self, byte_addr, bit):
        return bool(self.read_m(byte_addr, 1)[0] & (1 << bit))

    # ---------- 平台扩展（collector 用）：任意区原始读写 ----------
    AREAS = None     # 惰性解析：{"V":("DB",1),"M":("MK",0),"I":("PE",0),"Q":("PA",0)}

    def read_raw(self, area, offset, size):
        """area: 'V'/'M'/'I'/'Q'；返回 bytearray。V 区固定映射 DB1（实测确认）。"""
        self._need()
        from snap7 import Area
        if area == "V":
            return bytearray(self.cli.db_read(self.DB_V, offset, size))
        amap = {"M": Area.MK, "I": Area.PE, "Q": Area.PA}
        return bytearray(self.cli.read_area(amap[area], 0, offset, size))

    def write_raw(self, area, offset, data):
        self._need()
        from snap7 import Area
        if area == "V":
            self.cli.db_write(self.DB_V, offset, bytes(data))
            return
        amap = {"M": Area.MK, "I": Area.PE, "Q": Area.PA}
        self.cli.write_area(amap[area], 0, offset, bytes(data))

    def read_db(self, db, offset, size):
        self._need()
        return bytearray(self.cli.db_read(db, offset, size))

    def write_db(self, db, offset, data):
        self._need()
        self.cli.db_write(db, offset, bytes(data))

    def write_bit_raw(self, area, offset, bit, on=True):
        """任意区的位写（读-改-写一个字节）"""
        cur = bytearray(self.read_raw(area, offset, 1))
        if on:
            cur[0] |= (1 << bit)
        else:
            cur[0] &= ~(1 << bit)
        self.write_raw(area, offset, cur)

    # ---------- 自检 ----------
    def selftest(self, probe_offset=None, expect=None, tol=0.01):
        """握手自检
        probe_offset/expect 给定时校验该 REAL 是否在容差内；
        否则只验证能读到 4 字节且不是全 0。
        """
        raw = self.read_v(probe_offset if probe_offset is not None else 1000, 4)
        if len(raw) != 4:
            raise S7Error("自检失败：返回 %d 字节" % len(raw))
        val = struct.unpack(">f", raw)[0]
        if expect is not None:
            if abs(val - expect) > tol:
                raise S7Error("自检失败：读到 %.4f，期望 %.4f（字序可能是 CDAB）" % (val, expect))
            return val
        if raw == b"\x00\x00\x00\x00":
            raise S7Error("自检失败：读到全 0 —— 该地址无数据或 PLC 在 STOP")
        return val


if __name__ == "__main__":
    IP = "x.x.x.x"
    with S7200SMART(IP) as plc:
        print("VD1000 =", round(plc.read_real(1000), 4))
        print("VW1000 =", plc.read_int(1000))
        print("V1000.0 =", plc.read_bool(1000, 0))
        print("自检:", round(plc.selftest(1000, 44.335), 4))
