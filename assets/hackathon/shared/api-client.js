/* Shared HTTP adapter for the parallel hackathon components.
 * Real HTTP is the default. Fixture responses are only available through an
 * explicit createApiClient({ mode: "fixture", fixtures }) call.
 */
(function installHackathonApiClient(global) {
  "use strict";

  const CONTRACT_VERSION = "hackathon.v1";
  const DEFAULT_BASE_URL = global.location && global.location.protocol !== "file:"
    ? "/api/v1"
    : null;

  class ApiError extends Error {
    constructor({ status = 0, code = "request_failed", message = "请求失败", detail = null, payload = null } = {}) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.code = code;
      this.detail = detail;
      this.payload = payload;
    }
  }

  function cloneFixture(value) {
    if (typeof global.structuredClone === "function") return global.structuredClone(value);
    return JSON.parse(JSON.stringify(value));
  }

  function queryString(params) {
    const search = new URLSearchParams();
    Object.entries(params || {}).forEach(([key, value]) => {
      if (value === undefined || value === null || value === "") return;
      if (Array.isArray(value)) value.forEach((item) => search.append(key, String(item)));
      else search.set(key, String(value));
    });
    const encoded = search.toString();
    return encoded ? `?${encoded}` : "";
  }

  function errorFromResponse(status, payload) {
    const detail = payload && Object.prototype.hasOwnProperty.call(payload, "detail")
      ? payload.detail
      : null;
    const data = detail && typeof detail === "object" ? detail : payload;
    const message = (data && (data.message || data.detail))
      || (typeof detail === "string" ? detail : null)
      || (payload && payload.message)
      || `请求失败（${status}）`;
    const code = (data && data.code) || `http_${status}`;
    return new ApiError({ status, code, message: String(message), detail, payload });
  }

  function makeClient(request, mode) {
    const client = {
      mode,
      contractVersion: CONTRACT_VERSION,
      request,

      queryFacts: (body) => request("/hackathon/facts/query", { method: "POST", body }),
      assessRisks: (body) => request("/hackathon/risks/assess", { method: "POST", body }),
      compareProposals: (body) => request("/hackathon/proposals/compare", { method: "POST", body }),
      extractMaterial: (input, idempotencyKey) => {
        const source = input || {};
        const context = source.context || {
          tenant_id: source.tenant_id,
          scenario_id: source.scenario_id,
          branch_id: source.branch_id,
          snapshot_id: source.snapshot_id,
          as_of: source.as_of,
          data_version: source.data_version,
          fact_version: source.fact_version,
          is_demo: source.is_demo,
          source_refs: source.source_refs,
          missing_fields: source.missing_fields,
        };
        if (source.file) {
          const form = new FormData();
          form.append("context", JSON.stringify(context));
          Object.entries(source).forEach(([key, value]) => {
            if (["context", "file"].includes(key) || value === undefined || value === null) return;
            form.append(key, typeof value === "string" ? value : JSON.stringify(value));
          });
          form.append("file", source.file, source.file.name || "material");
          return request("/hackathon/materials/extract", { method: "POST", body: form, idempotencyKey });
        }
        return request("/hackathon/materials/extract", {
          method: "POST",
          body: { ...source, context },
          idempotencyKey,
        });
      },
      confirmMaterial: (draftId, body, idempotencyKey) => request(
        `/hackathon/materials/${encodeURIComponent(draftId)}/confirm`,
        { method: "POST", body, idempotencyKey },
      ),
      startAgentRun: (body) => request("/hackathon/agent-runs", { method: "POST", body }),
      getAgentRun: (runId, afterSequence = 0) => request(
        `/hackathon/agent-runs/${encodeURIComponent(runId)}${queryString({ after_sequence: afterSequence })}`,
      ),
      saveProposal: (body, idempotencyKey) => request(
        "/hackathon/proposals",
        { method: "POST", body, idempotencyKey },
      ),
      confirmProposal: (proposalId, body, idempotencyKey) => request(
        `/hackathon/proposals/${encodeURIComponent(proposalId)}/confirm`,
        { method: "POST", body, idempotencyKey },
      ),
      listProposals: (params = {}) => request(`/hackathon/proposals${queryString(params)}`),
      listTasks: (params = {}) => request(`/hackathon/tasks${queryString(params)}`),
      getOverview: (params = {}) => request(`/hackathon/overview${queryString(params)}`),
      getTask: (taskId) => request(`/hackathon/tasks/${encodeURIComponent(taskId)}`),
      recordChannelAction: (taskId, body, idempotencyKey) => request(
        `/hackathon/tasks/${encodeURIComponent(taskId)}/channel-actions`,
        { method: "POST", body, idempotencyKey },
      ),
      recordBusinessEvents: (taskId, body, idempotencyKey) => request(
        `/hackathon/tasks/${encodeURIComponent(taskId)}/events`,
        { method: "POST", body, idempotencyKey },
      ),
      advanceReplay: (body, idempotencyKey) => request(
        "/hackathon/replays/advance",
        { method: "POST", body, idempotencyKey },
      ),
      getAccounting: (params = {}) => request(`/hackathon/accounting${queryString(params)}`),
      getCase: (caseId) => request(`/hackathon/cases/${encodeURIComponent(caseId)}`),
    };
    return Object.freeze(client);
  }

  function createApiClient(options = {}) {
    if (options.mode === "fixture") return createFixtureClient(options.fixtures || {});
    if (options.mode && options.mode !== "http") {
      throw new TypeError('mode must be "http" or the explicit "fixture" mode');
    }

    const baseUrl = options.baseUrl === undefined ? DEFAULT_BASE_URL : options.baseUrl;
    const fetchImpl = options.fetch || global.fetch;
    const tenantId = options.tenantId || null;
    if (typeof fetchImpl !== "function") throw new TypeError("Fetch API is unavailable");

    const request = async (path, requestOptions = {}) => {
      if (!baseUrl) {
        throw new ApiError({
          code: "api_unavailable",
          message: "当前页面没有 HTTP 服务地址，请通过本地服务打开系统",
        });
      }
      const method = String(requestOptions.method || "GET").toUpperCase();
      const headers = { ...(requestOptions.headers || {}) };
      if (tenantId) headers["X-Tenant-Id"] = tenantId;
      if (requestOptions.idempotencyKey) headers["Idempotency-Key"] = requestOptions.idempotencyKey;

      const init = { method, headers, credentials: "same-origin" };
      if (requestOptions.body !== undefined) {
        if (typeof FormData !== "undefined" && requestOptions.body instanceof FormData) {
          init.body = requestOptions.body;
        } else {
          headers["Content-Type"] = headers["Content-Type"] || "application/json";
          init.body = JSON.stringify(requestOptions.body);
        }
      }

      let response;
      try {
        const prefix = String(baseUrl).replace(/\/$/, "");
        response = await fetchImpl(`${prefix}${path}`, init);
      } catch (error) {
        throw new ApiError({
          code: "network_error",
          message: "服务连接失败；已保留当前输入，请检查本地服务后重试",
          detail: error && error.message ? error.message : null,
        });
      }

      let payload = null;
      if (response.status !== 204) {
        const text = await response.text();
        if (text) {
          try { payload = JSON.parse(text); }
          catch (_) { payload = { message: text }; }
        }
      }
      if (!response.ok) throw errorFromResponse(response.status, payload);
      return payload;
    };

    return makeClient(request, "http");
  }

  function createFixtureClient(fixtures = {}) {
    const request = async (path, requestOptions = {}) => {
      const method = String(requestOptions.method || "GET").toUpperCase();
      const key = `${method} ${path}`;
      if (!Object.prototype.hasOwnProperty.call(fixtures, key)) {
        throw new ApiError({
          status: 501,
          code: "fixture_missing",
          message: `没有为 ${key} 提供显式开发 fixture`,
        });
      }
      const result = fixtures[key];
      if (result instanceof Error) throw result;
      const value = typeof result === "function"
        ? await result({ path, method, body: requestOptions.body, headers: requestOptions.headers || {} })
        : result;
      if (value === undefined) {
        throw new ApiError({ status: 501, code: "fixture_empty", message: `fixture ${key} 未提供响应` });
      }
      return cloneFixture(value);
    };
    return makeClient(request, "fixture");
  }

  global.HackathonApiClient = Object.freeze({
    ApiError,
    CONTRACT_VERSION,
    createApiClient,
    createFixtureClient,
  });
})(window);
