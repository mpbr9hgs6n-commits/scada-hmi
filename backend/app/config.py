import os
from urllib.parse import quote_plus

MYSQL_HOST = os.getenv("MYSQL_HOST", "mysql")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_ROOT_PWD = os.getenv("MYSQL_ROOT_PWD", "")   # 必须在 .env 里设置
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
TDENGINE_REST = os.getenv("TDENGINE_REST", "http://tdengine:6041")
TD_USER = os.getenv("TD_USER", "root")
# 口令只从环境变量取（.env 的 TDENGINE_PWD），代码里不留默认值——
# 拿不到就认证失败，宁可启动即报错，也不要悄悄退回出厂口令 taosdata
TD_PWD = os.getenv("TDENGINE_PWD") or os.getenv("TD_PWD") or ""
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://gateway:8090")
ZLM_URL = os.getenv("VIDEO_ZLM_URL", "http://zlm:80")
ZLM_SECRET = os.getenv("ZLM_SECRET", "035c73f7-bb6b-4889-a715-d9eb2d1925cc")
JWT_SECRET = os.getenv("JWT_SECRET", "")          # 必须在 .env 里设置（改它会让所有登录态失效）
JWT_ALG = "HS256"
JWT_EXP_H = 12

# 视频流 token（03 整改）：ZLM hook 用它校验播放/推流权限
VIDEO_TOKEN_SECRET = os.getenv("VIDEO_TOKEN_SECRET") or JWT_SECRET
VIDEO_TOKEN_TTL = int(os.getenv("VIDEO_TOKEN_TTL", "300"))   # 播放 token 5 分钟
PUBLISH_TOKEN = os.getenv("PUBLISH_TOKEN", "")               # 内部推流固定口令

def mysql_url(db="plant"):
    pwd = quote_plus(MYSQL_ROOT_PWD)
    return f"mysql+pymysql://root:{pwd}@{MYSQL_HOST}:{MYSQL_PORT}/{db}?charset=utf8mb4"


def gateway_api_url(gw_id: str = None) -> str:
    """网关 HTTP 地址（后端调 /internal/reload、/api/testconn 用）。

    约定：容器服务名 gateway-{gw_id}；gw1 沿用现有的 gateway 服务，
    保持单网关部署零改动。需要换地址时设环境变量 GATEWAY_URL_GW2 等覆盖。
    """
    import os as _os
    if not gw_id:
        return GATEWAY_URL.rstrip("/")
    env = _os.getenv("GATEWAY_URL_" + str(gw_id).upper().replace("-", "_"))
    if env:
        return env.rstrip("/")
    if str(gw_id) == "gw1":
        return GATEWAY_URL.rstrip("/")
    return f"http://gateway-{gw_id}:8090"


def tdengine_url_of(gw_id: str = None) -> str:
    """按网关标识**自动生成**它专属 TDengine 的 REST 地址。

    规则与 compose 的服务名约定一致：
      gw1 → http://tdengine:6041        （沿用现有的那套）
      gwN → http://tdengine-gwN:6041    （每个网关一套独立实例）

    特殊情况用环境变量覆盖，例如 TDengine 部署在另一台机器：
      TDENGINE_URL_GW2=http://10.0.0.5:6041
    """
    gid = str(gw_id or "").strip()
    if not gid:
        return TDENGINE_REST.rstrip("/")
    key = "TDENGINE_URL_" + gid.upper().replace("-", "_")
    env = _os_getenv(key)
    if env:
        return env.rstrip("/")
    if gid.lower() == "gw1":
        return TDENGINE_REST.rstrip("/")
    return f"http://tdengine-{gid.lower()}:6041"


def _os_getenv(k: str) -> str:
    import os as _o
    return _o.getenv(k) or ""


def _require_env():
    """启动自检：关键环境变量缺失时立即失败，不要带着空密码跑起来。"""
    missing = []
    if not MYSQL_ROOT_PWD:
        missing.append("MYSQL_ROOT_PWD")
    if not JWT_SECRET:
        missing.append("JWT_SECRET")
    if missing:
        raise RuntimeError(
            "缺少环境变量 %s。请复制 .env.example 为 .env 并填写。" % ", ".join(missing))


_require_env()
