FROM python:3.11-slim
WORKDIR /app
ENV TZ=Asia/Shanghai
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true
# 采集只需要 python 运行时；ffmpeg / iputils-ping 是开发期「假视频流 + ping 降级」用的，已移除
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*
COPY gateway/requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
COPY gateway/ ./
# 09：shared/addr.py 是地址解析唯一源码（backend/gateway 同一份），落到 /app/addr.py
COPY shared/addr.py ./addr.py
COPY shared/edition.py ./edition.py
# 生产只跑采集服务。
# 开发期的 sim_modbus.py（Modbus 模拟器）/ mock_stream.sh（ffmpeg 假视频流）已归档到 _debug/：
#   - 它们常驻后台，ffmpeg 会周期性 Bus error (core dumped) 污染日志
#   - 生产环境的 PLC 和相机都是真设备，不需要模拟器
# 需要联调时单独 docker run 起来即可，不要塞进生产镜像的启动命令。
CMD ["uvicorn", "collector:app", "--host", "0.0.0.0", "--port", "8090"]
