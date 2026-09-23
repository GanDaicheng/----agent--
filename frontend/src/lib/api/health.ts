/**
 * 服务健康检查（GET /api/v1/health）的客户端。
 *
 * 这个接口探的是**后端进程 + 数据库连接**两件事，返回体里有 status / database / service。
 * 它**不**代表模型服务、embedding 服务是否可用——那两个是外部供应商，
 * 后端不探测它们。所以页面上的文案必须写「后端与数据库」，不能简写成「服务正常」。
 *
 * 与其它三个客户端不同，这里**不抛错**（除了取消）：
 * 「数据库连不上」是这次探测的一个正常结果，不是探测本身失败。
 * 把它抛成异常，调用方就得靠 catch 来区分「探测失败」和「数据库不可用」，很容易写反。
 */

import { buildApiUrl, isAbortError, isRecord } from "./http";

const ENDPOINT_PATH = "/api/v1/health";

/** 后端返回体里 detail 文案的长度上限，超了就不展示（正常文案都很短）。 */
const MAX_DETAIL_CHARS = 200;

export type HealthState =
  /** 后端与数据库都正常。 */
  | "ok"
  /** 后端活着，但它连不上数据库（接口返回 503）。 */
  | "database-unavailable"
  /** 请求根本没发出去或没回来：后端没启动、端口不通、被浏览器拦掉。 */
  | "unreachable"
  /** 有响应，但不认识：可能是别的进程占用了 8000 端口。 */
  | "unexpected";

export type HealthProbe = {
  state: HealthState;
  /** 后端给出的受控说明（503 时是它自己的文案）。拿不到时为 null。 */
  detail: string | null;
};

function readDetail(payload: unknown): string | null {
  if (!isRecord(payload)) return null;
  const { message } = payload;
  if (typeof message !== "string") return null;
  const trimmed = message.trim();
  if (!trimmed || trimmed.length > MAX_DETAIL_CHARS) return null;
  return trimmed;
}

/**
 * 探测一次健康状态。
 *
 * **只探一次，不做轮询**：轮询会把「用户主动确认一下」变成持续的后台流量，
 * 而这个页面并没有需要实时监控的东西。什么时候探由用户点按钮决定。
 */
export async function probeHealth(signal?: AbortSignal): Promise<HealthProbe> {
  let response: Response;

  try {
    response = await fetch(buildApiUrl(ENDPOINT_PATH), {
      method: "GET",
      // 健康检查不能被浏览器缓存住，否则第二次点「检查服务」看到的还是旧结果
      cache: "no-store",
      signal,
    });
  } catch (error) {
    // 取消是用户的正常操作，原样往上抛，由调用方自己处理
    if (isAbortError(error)) throw error;
    return { state: "unreachable", detail: null };
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return { state: "unexpected", detail: null };
  }

  if (!isRecord(payload)) {
    return { state: "unexpected", detail: null };
  }

  // service 字段是后端专门加来做身份确认的：8000 端口上如果不是我们的后端，
  // 它就不会返回 "backend"。不确认这一点的话，任何占用 8000 的进程
  // 只要回一段 JSON，就会被页面显示成「服务正常」。
  if (payload.service !== "backend") {
    return { state: "unexpected", detail: null };
  }

  if (response.ok && payload.status === "ok" && payload.database === "connected") {
    return { state: "ok", detail: null };
  }

  // 503 是后端「活着但连不上数据库」时的正式答复，属于探测成功、结果为降级
  if (response.status === 503 && payload.database === "unavailable") {
    return { state: "database-unavailable", detail: readDetail(payload) };
  }

  return { state: "unexpected", detail: readDetail(payload) };
}
