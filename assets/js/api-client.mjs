export class ApiError extends Error {
  constructor(message, { status = 0, code = "request_failed", outcomeUnknown = false } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.outcomeUnknown = outcomeUnknown;
  }
}

function errorMessage(payload, status) {
  const detail = payload?.detail ?? payload?.message;
  if (Array.isArray(detail)) {
    return detail.map((item) => `${(item.loc || []).filter((part) => part !== "body").join(".")}: ${item.msg || "输入无效"}`).join("；");
  }
  return typeof detail === "string" ? detail : `请求失败（${status}）`;
}

// All API responses must be JSON. A disconnected write is never automatically retried.
export function createApiClient({ baseUrl = "/api/v1", fetchImpl = globalThis.fetch, timeoutMs = 15000 } = {}) {
  return async function api(path, options = {}) {
    if (!baseUrl) throw new ApiError("请通过本地服务打开页面（运行 start.bat 或 python server.py）", { code: "service_required" });
    const controller = new AbortController();
    const write = !["GET", "HEAD"].includes((options.method || "GET").toUpperCase());
    const abort = () => controller.abort();
    options.signal?.addEventListener("abort", abort, { once: true });
    if (options.signal?.aborted) abort();
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; abort(); }, timeoutMs);
    try {
      const headers = new Headers(options.headers);
      if (options.body != null && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
      const response = await fetchImpl(`${baseUrl}${path}`, { ...options, headers, signal: controller.signal });
      let payload;
      try { payload = await response.json(); }
      catch {
        throw new ApiError(response.ok ? "服务返回了无效 JSON，未采用该结果" : `请求失败（${response.status}），服务未返回 JSON 错误详情`, {
          status: response.status, code: "invalid_json", outcomeUnknown: write,
        });
      }
      if (!response.ok) throw new ApiError(errorMessage(payload, response.status), {
        status: response.status, code: "http_error", outcomeUnknown: write && response.status >= 500,
      });
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
        throw new ApiError("接口响应格式不符合约定，未采用该结果", { status: response.status, code: "invalid_response", outcomeUnknown: write });
      }
      return payload;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(timedOut ? "请求超时，请检查服务状态" : controller.signal.aborted ? "请求已取消" : "无法连接服务，请检查本地服务与网络", {
        code: timedOut ? "timeout" : controller.signal.aborted ? "aborted" : "network_error", outcomeUnknown: write,
      });
    } finally {
      clearTimeout(timeout);
      options.signal?.removeEventListener("abort", abort);
    }
  };
}
