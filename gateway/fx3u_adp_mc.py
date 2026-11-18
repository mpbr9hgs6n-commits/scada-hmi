# -*- coding: utf-8 -*-
"""
FX3U + FX3U-ENET-ADP 的 MC 协议驱动（A 兼容 1E 帧，二进制）

⚠️ 关键：ADP 用的是「A 兼容 1E 帧」，与 Q 系列的 3E 帧在字节级完全不同。
   1E 帧没有：网络号、模块IO号、站号、请求数据长度、命令/子命令
   固定 12 字节结构（手册 7.3 / p66 实例）：
     副标题1 + PC号1 + 定时器(L,H)2 + 起始编号4(小端) + 软元件名2(空格+字母) + 点数2

实测：x.x.x.x:4999  D1000/D1001 → 2.6530
"""
import socket
import struct
import time

# 命令/响应种类（手册 7.4）
KIND_READ_BIT = 0x00    # 成批读出·位单位（X/Y/M/S/T/C）
KIND_READ_WORD = 0x01   # 成批读出·字单位（位软元件按16点、字软元件按1点）
KIND_WRITE_BIT = 0x02   # 成批写入·位单位
KIND_WRITE_WORD = 0x03  # 成批写入·字单位

END_CODE = {
    0x00: "正常",
    0x50: "副标题的命令/响应种类不是规定(00~05H,13~16H)",
    0x54: "ASCII 模式下收到无法转换的数据",
    0x56: "对方设备指定的软元件有误",
    0x57: "点数超限 / 起始编号+点数越界 / 字节长度不符",
    0x58: "起始软元件号超出范围 / 位命令指定了字软元件",
    0x5B: "PLC 与 ADP 无法通信（见异常代码）",
    0x60: "ADP 与 PLC 通信超时（加大监视定时器）",
}

# 位软元件上限（一次通信，手册 7.4）
MAX_BIT = 256
MAX_WORD = 64


class MCError(Exception):
    pass


class FX3U_ADP:
    """FX3U + FX3U-ENET-ADP 客户端

    用法:
        plc = FX3U_ADP("x.x.x.x", 4999)
        plc.connect()
        print(plc.read_words("D", 1000, 2))    # [51905, 16425]
        print(plc.read_real("D", 1000))        # 2.6530
        print(plc.read_bits("M", 8013, 8))     # [1,0,0,0,...]
        plc.write_words("D", 7000, [1234])
        plc.close()
    """

    def __init__(self, ip, port=4999, timeout=3.0, timer_ms=2500):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.timer = max(1, min(0xFFFF, timer_ms // 250))   # 单位 250ms
        self.sock = None
        self.last_request_hex = ""
        self.last_response_hex = ""

    # ---------- 连接 ----------
    def connect(self):
        self.close()
        try:
            self.sock = socket.create_connection((self.ip, self.port), timeout=self.timeout)
            self.sock.settimeout(self.timeout)
            return self
        except Exception:
            self.close()
            raise

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *a):
        self.close()

    # ---------- 组帧 ----------
    def _frame(self, kind, dev, head, count, pc=0xFF):
        if not dev or len(dev) != 1:
            raise ValueError("dev 必须是单个字母，如 'D' / 'M' / 'X' / 'Y'")
        f = bytes([kind, pc])
        f += struct.pack("<H", self.timer)        # 定时器 L,H
        f += struct.pack("<I", head)              # 起始编号 4 字节小端
        f += bytes([0x20, ord(dev)])              # 软元件名：空格 + 字母
        f += struct.pack("<H", count)             # 点数 2 字节小端
        return f

    # ---------- 收发 ----------
    def _exchange(self, frame):
        if not self.sock:
            raise MCError("未连接，先 connect()")
        self.last_request_hex = frame.hex(" ")
        self.sock.sendall(frame)
        buf = b""
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
            if len(buf) >= 2:                     # 收到 副标题+结束码 就够判断
                if buf[1] != 0:                   # 异常，无数据区
                    break
                # 正常时数据区长度由点数决定，交给上层校验
                if len(buf) >= 2 + self._expect_len:
                    break
        self.last_response_hex = buf.hex(" ")
        return buf

    def _request(self, kind, dev, head, count):
        # 预计算期望的数据字节数（位：ceil(n/2)；字：n*2）
        if kind in (KIND_READ_BIT,):
            self._expect_len = (count + 1) // 2
        else:
            self._expect_len = count * 2
        frame = self._frame(kind, dev, head, count)
        resp = self._exchange(frame)

        if len(resp) < 2:
            raise MCError(
                "响应过短(%d 字节)：%s —— 检查 PLC 是否 RUN、ADP 连接是否打开"
                % (len(resp), resp.hex(" ") or "(无响应)")
            )
        sub, end = resp[0], resp[1]
        if end != 0:
            raise MCError("PLC 返回结束码 0x%02X：%s" % (end, END_CODE.get(end, "未知")))
        return resp[2:]

    # ---------- 读 ----------
    def read_words(self, dev, head, count):
        """字单位读，返回 list[int]（0~65535）"""
        if not 1 <= count <= MAX_WORD:
            raise ValueError("字单位一次最多 %d 点" % MAX_WORD)
        data = self._request(KIND_READ_WORD, dev, head, count)
        n = min(count, len(data) // 2)
        return list(struct.unpack("<" + "H" * n, data[:n * 2]))

    def read_bits(self, dev, head, count):
        """位单位读，返回 list[int]（0/1）。每字节含 2 点，高半字节在前。"""
        if not 1 <= count <= MAX_BIT:
            raise ValueError("位单位一次最多 %d 点" % MAX_BIT)
        data = self._request(KIND_READ_BIT, dev, head, count)
        bits = []
        for byte in data:
            bits.append((byte >> 4) & 0x0F)       # 高半字节 = 前一个点
            bits.append(byte & 0x0F)              # 低半字节 = 后一个点
        return [1 if b else 0 for b in bits][:count]

    def read_real(self, head, dev="D"):
        """32 位浮点：低字在前（D1000=低16位，D1001=高16位）"""
        w = self.read_words(dev, head, 2)
        return struct.unpack("<f", struct.pack("<HH", w[0], w[1]))[0]

    def read_dint(self, head, dev="D"):
        w = self.read_words(dev, head, 2)
        return struct.unpack("<i", struct.pack("<HH", w[0], w[1]))[0]

    # ---------- 写 ----------
    def write_words(self, dev, head, values):
        """字单位写"""
        if not 1 <= len(values) <= MAX_WORD:
            raise ValueError("字单位一次最多 %d 点" % MAX_WORD)
        body = b"".join(struct.pack("<H", v & 0xFFFF) for v in values)
        f = self._frame(KIND_WRITE_WORD, dev, head, len(values)) + body
        self._expect_len = 0
        resp = self._exchange(f)
        if len(resp) < 2:
            raise MCError("写入无响应")
        if resp[1] != 0:
            raise MCError("写入失败 0x%02X：%s" % (resp[1], END_CODE.get(resp[1], "未知")))
        return True

    def write_bit(self, dev, addr, on=True):
        """单点位写"""
        f = self._frame(KIND_WRITE_BIT, dev, addr, 1) + (b"\x01" if on else b"\x00")
        self._expect_len = 0
        resp = self._exchange(f)
        if len(resp) < 2 or resp[1] != 0:
            raise MCError("位写入失败: %s" % (resp.hex(" ") if resp else "无响应"))
        return True

    # ---------- 自检 ----------
    def selftest(self, samples=8, gap=0.25):
        """握手自检：M8013 是 1 秒时钟，多次采样必须出现 0/1 变化"""
        vals = []
        for _ in range(samples):
            vals.append(self.read_bits("M", 8013, 1)[0])
            time.sleep(gap)
        if len(set(vals)) == 1:
            raise MCError("自检失败：M8013 未翻转(%s) —— PLC 可能未 RUN 或 MC 通道异常" % vals)
        return vals


if __name__ == "__main__":
    IP, PORT = "x.x.x.x", 4999
    with FX3U_ADP(IP, PORT) as plc:
        print("自检 M8013 翻转:", plc.selftest())
        w = plc.read_words("D", 1000, 2)
        print("D1000/D1001 =", w, " REAL =", round(plc.read_real(1000), 4))
