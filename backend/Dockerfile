FROM python:3.11-slim
WORKDIR /app
ENV TZ=Asia/Shanghai
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true
# default-mysql-client：备份功能要用 mysqldump（第 04 章）
RUN apt-get update && apt-get install -y --no-install-recommends gcc default-mysql-client && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple uv
COPY backend/requirements.txt .
RUN uv pip install --system --no-cache -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
COPY backend/app ./app
# migrations 是一次性脚本（跑过就不用了），已归档到 _debug/，不打进镜像
COPY backend/tests ./tests
# 09：shared/addr.py 是地址解析唯一源码，构建时落到 app/core/addr.py
COPY shared/addr.py ./app/core/addr.py
COPY shared/edition.py ./app/core/edition.py
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
