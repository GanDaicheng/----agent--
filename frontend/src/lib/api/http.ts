/**
 * 三个业务客户端共用的请求基础设施。
 *
 * 只放真正重复的东西：地址拼接、取消判断、对象判断。
 * **不放**字段校验、错误文案和错误类型——那些是各条链路自己的业务约定，
 * 合到一起只会让「改一条链路牵动另一条」。
 */

/** 后端监听的端口。前端固定跑在 3000，后端固定跑在 8000。 */
const API_PORT = "8000";

/**
 * 拼接后端地址。
 *
 * 用当前页面的协议和主机名 + 固定端口 8000，而不是写死 IP：
 * 从 localhost:3000 打开的页面会请求 localhost:8000，
 * 从 127.0.0.1:3000 打开的会请求 127.0.0.1:8000。
 * 这样既不会把某台机器的 IP 固化进代码，也顺带满足了后端的 CORS 白名单
 * （它是按来源逐个列出的，写死 IP 反而会被拦）。
 *
 * **只能在浏览器里调用**：服务端渲染时没有 window。
 */
export function buildApiUrl(path: string): string {
  const { protocol, hostname } = window.location;
  return `${protocol}//${hostname}:${API_PORT}${path}`;
}

/** fetch 被 AbortController 取消时抛的就是这个，用它把「取消」和「失败」分开。 */
export function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
