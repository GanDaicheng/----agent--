# 前端生产镜像：多阶段构建，最终镜像只保留 standalone 产物，不带源码和开发依赖。
#
# 构建必须在项目根目录执行，因为构建上下文是根目录：
#   docker build --file frontend/Dockerfile --tag data-platform-agent-frontend:local .
#
# 三个阶段的分工：
#   dependencies —— 只装依赖。package.json 和 package-lock.json 单独先复制，
#                   只要锁文件没变这层就命中缓存，改代码时不必重装依赖。
#   builder      —— 装好依赖 + 源码，跑 next build。
#   runner       —— 只拿构建产物，体积最小。

FROM node:24-alpine AS dependencies

WORKDIR /app

# 必须先复制 lock 文件再用 npm ci：ci 会严格按锁文件安装并校验一致性，
# 保证容器里装到的版本和本机开发时完全一致。用 npm install 则可能悄悄升级版本。
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

FROM node:24-alpine AS builder

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

# 依赖直接从上一阶段搬过来，不在这一层重装。
# 注意：宿主机的 frontend/node_modules 已被根目录 .dockerignore 排除，
# 不会被复制进来 —— 那是 Windows 平台的二进制，装到 Alpine 里根本跑不起来。
COPY --from=dependencies /app/node_modules ./node_modules
COPY frontend/ ./
RUN npm run build

FROM node:24-alpine AS runner

WORKDIR /app

# HOSTNAME 必须是 0.0.0.0：默认只监听 127.0.0.1 的话，容器外访问不到。
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

# standalone 产物自带 server.js 和它需要的那部分 node_modules。
# 但 Next.js 官方说明 server.js 默认不包含 public 和 .next/static，
# 这两个必须手动放到对应位置（standalone 根目录下的 public 和 .next/static），
# 放对之后 server.js 会自动服务它们；漏掉的话页面能开但样式和图片会 404。
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000

# 用 standalone 自带的 server.js 启动，而不是 npx next start：
# next start 需要完整的 node_modules，最终镜像里并没有。
CMD ["node", "server.js"]
