"""Redis 实时值封装：rt:{site} Hash + stream:changes Stream"""
import json, time
from .. import config

def rt_key(site_id: str) -> str:
    return f"rt:{site_id}"

async def hset_value(rc, site_id, code, val, ts_ms, q=0):
    await rc.hset(rt_key(site_id), code, f"{val}|{ts_ms}|{q}")
    await rc.xadd("stream:changes",
                  {"site": site_id, "point": code, "val": str(val),
                   "ts": str(ts_ms), "q": str(q)},
                  maxlen=100000, approximate=True)

async def hget_all(rc, site_id):
    raw = await rc.hgetall(rt_key(site_id))
    out = {}
    for code, s in raw.items():
        try:
            v, ts, q = s.split("|")
            out[code] = {"val": float(v), "ts": int(ts), "q": int(q)}
        except Exception:
            continue
    return out

# —— 报警事件总线 ——
# 报警是「事件」不是「量测」：轮询 5 秒的后果是操作员看到报警时已经过去 5 秒。
# 状态机（alarm_engine）在每次 commit 后 XADD 一条，SSE 端点 XREAD 消费。
# 用同步客户端：状态机本身跑在同步的请求/网关线程里，这里再 await 一次没有意义，
# 而且 XADD 是 O(1)，失败也只吞掉——报警已经落库了，推送失败不能反过来影响状态机。
_alarm_redis = None


def publish_alarm(payload: dict):
    global _alarm_redis
    try:
        import redis as _redis
        if _alarm_redis is None:
            _alarm_redis = _redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT,
                                        decode_responses=True, socket_timeout=2)
        flat = {}
        for k, v in (payload or {}).items():
            flat[k] = "" if v is None else str(v)
        _alarm_redis.xadd("stream:alarms", flat, maxlen=5000, approximate=True)
    except Exception:
        pass


def merge_by_point(items):
    """SSE 100ms 窗口合并：同点位只保留最新"""
    merged = {}
    for item in items:
        d = item[1]
        code = d.get(b"point", b"").decode() if isinstance(d.get(b"point"), bytes) else d.get("point", "")
        site = d.get(b"site", b"").decode() if isinstance(d.get(b"site"), bytes) else d.get("site", "")
        val = d.get(b"val", b"").decode() if isinstance(d.get(b"val"), bytes) else d.get("val", "")
        ts = d.get(b"ts", b"").decode() if isinstance(d.get(b"ts"), bytes) else d.get("ts", "")
        q = d.get(b"q", b"").decode() if isinstance(d.get(b"q"), bytes) else d.get("q", "")
        merged[f"{site}:{code}"] = {"site": site, "code": code, "val": val, "ts": ts, "q": q}
    return list(merged.values())
