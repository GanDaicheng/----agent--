# 后端生产镜像：只装生产依赖 + 后端源码，不带测试工具和 .env。
#
# 构建必须在项目根目录执行，因为构建上下文是根目录：
#   docker build --file backend/Dockerfile --tag data-platform-agent-backend:local .
#
# 基础镜像版本要和本机开发用的大版本保持一致，否则会出现
# 「本机跑得好、容器里行为不同」的诡异问题。

FROM python:3.14-slim

# PYTHONDONTWRITEBYTECODE：不生成 .pyc，镜像里不留下 __pycache__ 垃圾
# PYTHONUNBUFFERED：日志不缓冲，docker logs 能实时看到输出，而不是攒一批才吐
# PIP_NO_CACHE_DIR：不保留 pip 下载缓存，镜像更小
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先只复制依赖清单并安装。只要 requirements.txt 没变，
# 这一层就命中缓存，改代码时不会每次都重装一遍依赖。
COPY requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# 单独复制 app 源码。故意不写 `COPY backend ./`：
# 那样会把 tests/ 和 requirements-dev.txt 一起带进生产镜像。
COPY backend/app ./app

EXPOSE 8000

# 生产不用 --reload：热重载是开发期特性，会常驻文件监听进程，且行为不稳定。
# host 必须是 0.0.0.0 而不是 127.0.0.1，否则容器外（宿主机、Compose 网络）访问不到。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
