# 第三方组件许可证声明 / Third-Party Notices

本项目的部分功能依赖以下第三方组件。分发本项目（或其衍生作品）时，请一并保留本文件及下列各组件的许可证文本。

This project depends on the following third-party components. When distributing this project (or a derivative work), please retain this file together with the license texts listed below.

---

## 一、Python 依赖 / Python dependencies

### 宽松许可（MIT / BSD / Apache-2.0）— 无需额外义务

| 组件 | 许可证 | 用途 |
|---|---|---|
| FastAPI | MIT | Web 框架（后端与网关） |
| Uvicorn | BSD-3-Clause | ASGI 服务器 |
| Starlette | BSD-3-Clause | FastAPI 底层 |
| Pydantic | MIT | 数据校验 |
| SQLAlchemy | MIT | ORM |
| PyMySQL | MIT | MySQL 驱动 |
| redis-py | MIT | Redis 客户端 |
| taospy | MIT | TDengine 客户端 |
| python-jose | MIT | JWT |
| passlib | BSD | 密码哈希 |
| bcrypt | Apache-2.0 | 密码哈希后端 |
| APScheduler | MIT | 定时任务 |
| HTTPX | BSD-3-Clause | HTTP 客户端 |
| python-multipart | Apache-2.0 | 表单上传 |
| pymodbus | BSD-3-Clause | Modbus TCP/RTU |
| python-snap7 | MIT | S7comm Python 封装 |
| pymcprotocol | MIT | 三菱 MC 协议 |
| fins-driver | MIT | 欧姆龙 FINS |

### asyncua — **LGPL-3.0**

```
asyncua (FreeOpcUa)
GNU Lesser General Public License v3.0
```

本项目仅通过 `import` 使用 asyncua，未修改其源码。LGPL-3.0 允许闭源软件动态引用该库，条件是：

1. 保留其版权声明与许可证文本（本文件即为声明）
2. 允许最终用户用修改过的 asyncua 替换原库（本项目以独立 Python 包形式引入，满足此条件）

如需替换：`pip install asyncua==<your-version>` 覆盖即可，无需重新编译本项目。

### libsnap7 — **LGPL-3.0**

```
snap7 (原生库, python-snap7 通过 ctypes 调用)
GNU Lesser General Public License v3.0
```

同样为动态调用（ctypes），未修改、未静态链接。替换方式同上。

---

## 二、前端依赖 / Frontend dependencies

| 组件 | 许可证 |
|---|---|
| Vue 3 | MIT |
| Vue Router | MIT |
| Pinia | MIT |
| Element Plus | MIT |
| @element-plus/icons-vue | MIT |
| ECharts | Apache-2.0 |
| flv.js | Apache-2.0 |
| Vite | MIT |
| @vitejs/plugin-vue | MIT |

Apache-2.0 组件（ECharts、flv.js、bcrypt、python-multipart）要求分发时附带 Apache-2.0 许可证全文，并在修改过的文件中注明修改。

---

## 三、外部服务 / External services

以下组件以**独立进程**方式运行，本项目通过网络协议（HTTP/MySQL 协议）访问，**不链接其库、不修改其源码**，因此不构成衍生作品。

### TDengine — **AGPL-3.0**

```
TDengine Community Edition
GNU Affero General Public License v3.0
```

本项目通过 **REST 接口**（`http://tdengine:6041/rest/sql`）访问 TDengine，为独立进程通信，不构成衍生作品。AGPL-3.0 的义务（修改后对外提供网络服务需开源）针对的是 TDengine 自身的修改，与本项目无关。

⚠ **注意**：如果将来把 TDengine 的代码嵌入本项目并编译分发，AGPL-3.0 将传染到被嵌入的部分。

### MySQL Community Server — **GPL-2.0**

通过标准 MySQL 协议（TCP）访问，独立服务，不构成衍生作品。

### ZLMediaKit — **MIT**

以独立容器运行，通过 HTTP API 与 RTSP/HTTP-FLV 交互。

### Nginx — **BSD-2-Clause**

以独立容器运行。

### Redis — **BSD-3-Clause**

（Redis 7.4 起新版本改用 RSALv2/SSPL 双许可，请按实际使用的版本核对）

---

## 四、本项目自身 / This project

```
Copyright (c) 2026 张家口陆祺智控工程技术有限责任公司
                   Zhangjiakou Luche Intelligent Control Engineering Technology Co., Ltd.
Licensed under the GNU Affero General Public License v3.0 (see LICENSE)
```

---

## 五、合规提示 / Compliance notes

1. **分发时必须保留本文件**及各许可证原文（Apache-2.0 与 LGPL-3.0 的强制要求）。
2. **不要移除**依赖包内的版权头、NOTICE 文件。
3. 若修改了 asyncua 或 libsnap7 的源码，**必须开源修改部分**（LGPL-3.0）。
4. 若修改了 TDengine 并对外提供服务，**必须开源修改部分**（AGPL-3.0）。
5. 本文件不构成法律意见；商业交付前建议由法务复核。
