# -*- coding: utf-8 -*-
"""提示词 10 第 2 节：在线/离线判定（modbus_echo 回环 / ping），统一状态机。

两种方式二选一（site.heartbeat_mode）：
  none         不判定，沿用采集成功/失败（老行为）
  modbus_echo  每轮写 hb_write_addr=N，读 hb_read_addr，相等=在线。
               同时验证 TCP 通、PLC 在 RUN、数据区可写（PLC 停机时 MOV 不执行 →
               读回旧值 → 判定离线）。只对 modbus_tcp 有效，其他协议后端自动降级 ping。
  ping         每 ping_interval_ms 探测一次；连续 hb_cycles 次失败 → 离线；
               恢复要求「ping 通 + 一次采集成功」同时满足。

状态机（online / suspect / offline，初始 unknown）：
    online --1 次失败--> suspect --连续 N 次--> offline
    任意一次成功 --> online
状态只在**变化时**回写 site.status / Redis，避免每轮 UPDATE 打爆 MySQL。
"""
import asyncio
import logging
import shutil
import socket
import struct
import subprocess
import time

log = logging.getLogger("hb")


class MbTcp:
    """极简 Modbus TCP 客户端（只做 FC3 读 / FC6 写），同步 socket 跑在线程池里。

    🔴 两个坑都是用 S7-200 SMART（x.x.x.x:506/507）实测撞出来的：
    1) pymodbus 3.7.4 在这台 PLC 上「请求发出后要等满 timeout 才返回」
       （手搓报文只要几毫秒）→ 心跳每轮卡 3~6 秒、3 次重试全超时，一律判离线。
    2) asyncio.open_connection 的流式套接字连得上、读 readexactly 却永远等不到数据；
       同样的报文字节用同步 socket 发就秒回。
    所以这里用同步 socket（asyncio.to_thread 包一层），报文格式与手搓验证脚本完全一致。
    """

    def __init__(self, sock, slave=1):
        self.s = sock
        self.slave = slave
        self.tid = 0

    @classmethod
    async def open(cls, ip, port, timeout=3, slave=1):
        def _conn():
            s = socket.create_connection((ip, int(port)), timeout=timeout)
            s.settimeout(timeout)
            try:
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except Exception:
                pass
            return s

        return cls(await asyncio.to_thread(_conn), slave)

    def alive(self):
        return self.s is not None

    def _recv(self, n):
        b = b""
        while len(b) < n:
            c = self.s.recv(n - len(b))
            if not c:
                raise ConnectionError("连接被对端关闭")
            b += c
        return b

    def _sync_req(self, pdu, timeout):
        self.s.settimeout(timeout)
        self.tid = (self.tid + 1) & 0xFFFF
        self.s.sendall(struct.pack(">HHHB", self.tid, 0, len(pdu) + 1, self.slave) + pdu)
        hdr = self._recv(7)
        ln = struct.unpack(">H", hdr[4:6])[0]
        return self._recv(max(1, ln - 1))

    async def read_hr(self, addr, count=1, timeout=2):
        b = await asyncio.to_thread(
            self._sync_req, struct.pack(">BHH", 3, addr, count), timeout)
        if b[0] >= 0x80:
            raise IOError("Modbus 异常码 0x%02X" % b[1])
        n = b[1]
        return [struct.unpack(">H", b[2 + i * 2:4 + i * 2])[0] for i in range(n // 2)]

    async def write_hr(self, addr, value, timeout=2):
        b = await asyncio.to_thread(
            self._sync_req, struct.pack(">BHH", 6, addr, value), timeout)
        if b[0] >= 0x80:
            raise IOError("Modbus 异常码 0x%02X" % b[1])
        return True

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass
        self.s = None

ONLINE, SUSPECT, OFFLINE, UNKNOWN = "online", "suspect", "offline", "unknown"


class StatusMachine:
    """纯状态机（不依赖 IO，可单测）。feed(ok) 返回变化后的状态，None=没变化。"""

    def __init__(self, cycles=3):
        # None / 空 / 非数字 → 默认 3；0 和负数 → 夹到 1（宁可快速判离线，不要永不判）
        try:
            n = int(cycles)
        except (TypeError, ValueError):
            n = 3
        self.cycles = max(1, n)
        self.state = UNKNOWN
        self.fails = 0

    def feed(self, ok):
        prev = self.state
        if ok:
            self.fails = 0
            self.state = ONLINE
        else:
            self.fails += 1
            if self.fails >= self.cycles:
                self.state = OFFLINE
            elif self.state == ONLINE:
                self.state = SUSPECT
        return None if prev == self.state else self.state


def ping_host(ip, port=None, timeout_s=1):
    """ICMP ping 一次。镜像里没有 ping 二进制时退化为 TCP 连接（端口缺省 502）。

    注意：TCP 兜底只证明「网络可达」，不能证明 PLC 在 RUN —— 这就是为什么
    modbus_echo 优先：它能验证 PLC 程序在跑。
    """
    exe = shutil.which("ping")
    if exe:
        try:
            r = subprocess.run([exe, "-c", "1", "-W", str(max(1, int(timeout_s))), ip],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=timeout_s + 2)
            return r.returncode == 0
        except Exception:
            pass
    try:
        with socket.create_connection((ip, int(port or 502)), timeout=timeout_s):
            return True
    except Exception:
        return False


class Heartbeat:
    """每站点一个状态机；on_change(site, state) 由采集器提供（写库/Redis/事件）。"""

    def __init__(self, on_change):
        self.on_change = on_change
        self.machines = {}     # sid -> StatusMachine
        self.ping_ok = {}      # sid -> 最近一次 ping 结果
        self.seq = {}          # sid -> 回环写入值
        self.next_ping = {}    # sid -> monotonic 下次 ping 时间
        self.clients = {}      # "{sid}:w" / "{sid}:r" -> 双端口回环专用连接
        self.next_echo = {}    # sid -> monotonic 下次回环时间（hb_interval_s>0 时生效）
        self.fails = {}        # "{sid}:w" -> 连续失败次数（够 3 次才重建连接）

    # ---------- 生命周期 ----------
    def drop(self, sid):
        self.machines.pop(sid, None)
        self.ping_ok.pop(sid, None)
        self.seq.pop(sid, None)
        self.next_ping.pop(sid, None)
        self.next_echo.pop(sid, None)
        self.fails.pop(f"{sid}:w", None)
        for role in ("w", "r"):
            c = self.clients.pop(f"{sid}:{role}", None)
            if c is not None:
                try:
                    c.close()
                except Exception:
                    pass

    def machine(self, dev):
        sid = dev["site"]
        cycles = int(dev.get("hb_cycles") or 3)
        m = self.machines.get(sid)
        if m is None or m.cycles != cycles:
            m = StatusMachine(cycles)
            self.machines[sid] = m
        return m

    # ---------- 每轮采集后调用 ----------
    async def on_poll(self, dev, poll_ok):
        mode = (dev.get("hb_mode") or "none").lower()
        if mode == "none":
            return None
        m = self.machine(dev)
        if mode == "modbus_echo":
            # 独立节奏：hb_interval_s>0 时不等每轮采集，到点才跑一次。
            # 没到点返回 None —— 不改判状态（「还没测」不能当成「测失败」）。
            iv = int(dev.get("hb_interval_s") or 0)
            if iv > 0:
                now = time.monotonic()
                if now < self.next_echo.get(dev["site"], 0):
                    return None
                self.next_echo[dev["site"]] = now + iv
            ok = await self._echo(dev)
        else:
            # ping 模式：ping 通 + 本轮采集成功才算「健康」；两个条件缺一不可
            ok = bool(poll_ok and self.ping_ok.get(dev["site"], False))
        st = m.feed(ok)
        if st:
            await self.on_change(dev["site"], st)
        return st

    async def _echo(self, dev):
        """写 N 读回比对。写、读可以走**不同端口**（hb_write_port / hb_read_port）。

        为什么要两个端口：现场常把「可写区」和「只读镜像区」挂在两个 Modbus 服务端口上
        （例如 506 写、507 读），PLC/网关侧负责把写入值搬到读地址。
        只配了地址不配端口时，两者都回落到站点 plc_port，复用采集长连接，不多开 TCP。
        """
        sid = dev["site"]
        ip = dev.get("ip")
        base_port = int(dev.get("port") or 502)
        wcfg = dev.get("hb_write_port")
        rcfg = dev.get("hb_read_port")
        wport = int(wcfg or base_port)
        rport = int(rcfg or base_port)
        slave = int(dev.get("slave_id") or 1)
        # 心跳一律用自建连接（MbTcp），不复用采集的 pymodbus 长连接：
        # 采集那条在部分 PLC 上会「等满 timeout 才返回」，心跳等不起。
        # 超时内置 3 秒（站点参数里不再有这一项）。原来 max(1.0, min(10.0, ...)) 会把用户填的值静默夹到 1~10 秒，改不了还不如不给配。
        timeout = 3.0
        try:
            cw = await self._conn(f"{sid}:w", ip, wport, timeout, slave)
            cr = cw if rport == wport else await self._conn(f"{sid}:r", ip, rport, timeout, slave)
            if cw is None or cr is None:
                return False

            mx = max(1, min(2000, int(dev.get("hb_max_value") or 2000)))
            n = self.seq.get(sid, 0) % mx + 1      # 1..mx 循环：到 mx 后下一个回到 1
            self.seq[sid] = n
            # 🔴 不能用 `x or 默认值`：0 是合法寄存器地址，但 0 在 Python 里是假值，
            #    会把「读回地址 0」悄悄变成 1 —— 用户配读 0、代码却去读 hr1，
            #    读到的是 MOV 搬来的上一次的值，永远对不上 → 一直判离线。
            _w = dev.get("hb_write_addr")
            _r = dev.get("hb_read_addr")
            waddr = 0 if _w is None or _w == "" else int(_w)
            raddr = 1 if _r is None or _r == "" else int(_r)

            await cw.write_hr(waddr, n, timeout)
            # 写入后不要立刻下结论：PLC 的「MOV 写地址→读地址」要等扫描周期，
            # 立即读往往还是上一次的值。实测 450ms 窗口不够（读回地址走 MOV 时
            # 约 60% 判失败），放宽到 5 次 × 400ms ≈ 2 秒，覆盖慢扫描周期。
            seen = []
            for attempt in range(5):
                got = await cr.read_hr(raddr, 1, timeout)
                cur = got[0] if got else None
                seen.append(cur)
                if cur is not None and int(cur) == n:
                    self.fails.pop(f"{sid}:w", None)
                    return True
                if attempt < 4:
                    await asyncio.sleep(0.4)
            # 读回来的值和写入值对不上：把实际值打出来，现场据此判断是
            # 「PLC 没搬」「地址不对」还是「搬得太慢」
            log.warning("%s 心跳不匹配: 写入 w=%d@%s:%d, 读 r=%s:%d, 5次读到=%s",
                        sid, n, ip, waddr, ip, raddr, seen)
            return False
        except Exception as e:
            log.warning("%s 回环心跳失败(%s:%s→%s:%s): %s", sid, ip, wport, ip, rport, e)
            # 🔴 不要每次失败都拆连接重建：S7-200 SMART 的 Modbus 连接槽很少
            # （实测把 2 个槽耗光后，连正常读都全部超时，要等二十多秒才恢复）。
            # 连续失败 3 次才重建一次，中间这几次原地重试。
            k = f"{sid}:w"
            self.fails[k] = self.fails.get(k, 0) + 1
            if self.fails[k] >= 3:
                for role in ("w", "r"):
                    c = self.clients.pop(f"{sid}:{role}", None)
                    if c is not None:
                        c.close()
                self.fails[k] = 0
            return False

    async def _conn(self, key, ip, port, timeout, slave=1):
        """按 (站点, 角色) 缓存一条 Modbus 连接；断了重建。"""
        c = self.clients.get(key)
        if c is not None and c.alive():
            return c
        if c is not None:
            c.close()
        try:
            c = await MbTcp.open(ip, port, timeout, slave)
            self.clients[key] = c
            return c
        except Exception as e:
            log.warning("%s 心跳连接失败 %s:%s %s", key, ip, port, e)
            self.clients.pop(key, None)
            return None

    # ---------- ping 巡检（所有 ping 模式站点共用一个协程） ----------
    async def ping_loop(self, sites_getter):
        while True:
            try:
                now = time.monotonic()
                for dev in list(sites_getter().values()):
                    if (dev.get("hb_mode") or "none").lower() != "ping":
                        continue
                    sid = dev["site"]
                    if now < self.next_ping.get(sid, 0):
                        continue
                    iv = max(1000, int(dev.get("ping_interval_ms") or 5000)) / 1000
                    self.next_ping[sid] = now + iv
                    ok = await asyncio.to_thread(ping_host, dev["ip"],
                                                 dev.get("port"), 1)
                    self.ping_ok[sid] = ok
                    # ping 本身也是一次判定：不过要叠加「最近一轮采集成功」
                    m = self.machine(dev)
                    st = m.feed(bool(ok and dev.get("last_poll_ok")))
                    if st:
                        await self.on_change(sid, st)
                await asyncio.sleep(1)
            except Exception as e:
                log.warning("ping 心跳巡检异常: %s", e)
                await asyncio.sleep(3)
