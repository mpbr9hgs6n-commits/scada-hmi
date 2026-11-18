from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import redis.asyncio as aioredis
import httpx
from . import config

engine = create_engine(config.mysql_url(), pool_pre_ping=True, pool_recycle=1800)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()

redis_client = aioredis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT,
                              decode_responses=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def td_exec(sql: str, td_url: str = None):
    """TDengine REST 执行。

    td_url 为空时用全局默认（config.TDENGINE_REST）。
    多网关方案下，历史数据分实例存放，读的时候必须按站点路由到它所属网关的库。
    """
    url = (td_url or config.TDENGINE_REST).rstrip("/") + "/rest/sql"
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(url, content=sql.encode("utf-8"),
                         auth=(config.TD_USER, config.TD_PWD))
        return r.json()


async def td_query(sql: str, td_url: str = None):
    data = await td_exec(sql, td_url)
    if data.get("code") != 0:
        raise RuntimeError(f"TDengine error {data.get('code')}: {data.get('desc')}")
    return data


def td_url_for_site(db, site_id: str) -> str:
    """按站点找它所属网关的 TDengine 地址。

    一个网关一套独立 TDengine：站点 S001 在 gw1，它的历史就只在 gw1 的库里，
    去别的库查会得到空结果（不报错，更难查）。所以读取端必须先解析归属。
    任何一环缺失都回落全局默认，保证老数据/单网关部署照常可查。
    """
    try:
        from .models import Gateway, Site
        s = db.query(Site).filter(Site.id == site_id).first()
        if s and getattr(s, "gateway_id", None):
            g = db.query(Gateway).filter(Gateway.id == s.gateway_id).first()
            if g and g.tdengine_url:
                return g.tdengine_url
    except Exception:
        pass
    return config.TDENGINE_REST
