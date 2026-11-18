# -*- coding: utf-8 -*-
"""版本额度（社区版 / 商业版）。

社区版（开源）硬上限：
    每网关最多 2 台 PLC（= 2 个站点）
    全平台最多 8 路视频通道

商业版把这两个值改成 None 即为不限。改这里一处，后端和网关同时生效
（两边镜像都 COPY 了这个文件，见 Dockerfile）。

为什么限制做在"新增入口 + 网关加载"两处：
    只在 API 拦，直接改库就能绕过；
    只在网关拦，用户会先建出 10 个站点再发现只有 2 个在采，体验更差。
    两处都做：UI 直接告诉用户额度用完了，网关也不会偷偷多采。
"""

EDITION = "community"

# 每网关最多站点数（一个站点 = 一台 PLC）。None = 不限
MAX_SITES = 2

# 全平台最多视频通道数。None = 不限
MAX_CAMERAS = 8

# 每台 PLC（每个站点）最多采集点数。None = 不限
MAX_POINTS_PER_SITE = 1000


def sites_full(current: int) -> bool:
    """还能不能再加一个站点。"""
    return MAX_SITES is not None and int(current or 0) >= MAX_SITES


def cameras_full(current: int) -> bool:
    """还能不能再加一路视频。"""
    return MAX_CAMERAS is not None and int(current or 0) >= MAX_CAMERAS


def sites_message(current: int) -> str:
    return (f"社区版每台网关最多接入 {MAX_SITES} 台 PLC（当前已有 {current} 台）。"
            f"需要接入更多 PLC、更多站点，请联系商业授权。")


def points_full(current: int) -> bool:
    """该站点还能不能再加点位。"""
    return MAX_POINTS_PER_SITE is not None and int(current or 0) >= MAX_POINTS_PER_SITE


def points_message(current: int, adding: int = 0) -> str:
    tail = f"，本次要加 {adding} 个" if adding else ""
    return (f"社区版每台 PLC 最多 {MAX_POINTS_PER_SITE} 个采集点"
            f"（当前已有 {current} 个{tail}）。需要更多点位，请联系商业授权。")


def cameras_message(current: int) -> str:
    return (f"社区版最多 {MAX_CAMERAS} 路视频通道（当前已有 {current} 路）。"
            f"需要接入更多摄像头，请联系商业授权。")
