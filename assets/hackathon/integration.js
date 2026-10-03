/* Mounts hackathon.v1 modules into the existing retail app shell. */
(function installHackathonIntegration(window, document) {
  "use strict";

  const SCRIPT_URL = document.currentScript && document.currentScript.src
    ? document.currentScript.src
    : window.location.href;
  const ASSET_BASE = new URL("./", SCRIPT_URL);
  const PREVIEW = new URLSearchParams(window.location.search).get("hackathonPreview") === "1";
  const ROUTES = new Set(["decision-entry", "execution-followup"]);
  const CONTEXT_KEYS = [
    "tenantId", "scenarioId", "branchId", "snapshotId", "asOf", "dataVersion", "factVersion",
    "isDemo", "sourceRefs", "missingFields", "area", "horizonStart", "horizonEnd", "assumptionIds",
    "riskId", "storeId", "skuId", "lotId", "actorId", "proposalId", "proposalVersion", "taskId",
    "businessInputs",
  ];
  const HOST_CONTEXT_KEYS = ["tenantId", "snapshotId", "asOf", "dataVersion", "factVersion", "isDemo", "sourceRefs", "missingFields"];
  const PREVIEW_CONTEXT = Object.freeze({
    tenantId: "demo",
    scenarioId: "S01",
    branchId: "transfer_80",
    snapshotId: "SNAP-20261003-BASE",
    asOf: "2026-10-03T09:30:00+08:00",
    dataVersion: "retail-v2.1",
    factVersion: 1,
    isDemo: true,
    sourceRefs: [],
    missingFields: [],
    area: "transfer",
    horizonStart: "2026-10-03",
    horizonEnd: "2026-10-25",
    assumptionIds: [],
    riskId: null,
    storeId: "ST-001",
    skuId: "SKU-001",
    lotId: "LOT-001-001",
    actorId: "manager-demo",
    proposalId: null,
    proposalVersion: 0,
    taskId: null,
    businessInputs: {},
  });

  let context = PREVIEW ? { ...PREVIEW_CONTEXT } : readHostContext();
  let mounted = null;
  let mountedRoute = null;
  let routeGeneration = 0;
  let contextGeneration = 0;
  let decisionModulePromise = null;
  const apiClients = new Map();

  function readHostContext() {
    const supplied = window.RetailHackathonHost && typeof window.RetailHackathonHost.getContext === "function"
      ? window.RetailHackathonHost.getContext()
      : {};
    return normalizeContext(supplied);
  }

  function normalizeContext(input) {
    const source = input || {};
    const output = {};
    CONTEXT_KEYS.forEach((key) => {
      if (Object.prototype.hasOwnProperty.call(source, key)) output[key] = source[key];
      else output[key] = key === "sourceRefs" || key === "missingFields" || key === "assumptionIds" ? []
        : key === "businessInputs" ? {}
          : key === "tenantId" ? "demo" : null;
    });
    output.sourceRefs = Array.isArray(output.sourceRefs) ? [...output.sourceRefs] : [];
    output.missingFields = Array.isArray(output.missingFields) ? [...output.missingFields] : [];
    output.assumptionIds = Array.isArray(output.assumptionIds) ? [...output.assumptionIds] : [];
    output.businessInputs = output.businessInputs && typeof output.businessInputs === "object" ? { ...output.businessInputs } : {};
    return output;
  }

  function mergeContext(nextContext) {
    const next = normalizeContext({ ...context, ...(nextContext || {}) });
    if (JSON.stringify(next) !== JSON.stringify(context)) contextGeneration += 1;
    context = next;
    return { ...context };
  }

  function getApiClient(tenantId, actorId) {
    if (!window.HackathonApiClient) throw new Error("未加载 Hackathon 共享 API 客户端。");
    const key = tenantId || "demo";
    const actor = actorId || "";
    const cacheKey = `${key}\u0000${actor}`;
    if (!apiClients.has(cacheKey)) apiClients.set(cacheKey, window.HackathonApiClient.createApiClient({ tenantId: key, actorId: actor || null }));
    return apiClients.get(cacheKey);
  }

  function mapContextFromApi(result, base) {
    const source = result && result.context || {};
    const selection = result && result.selection || {};
    const target = selection.target || {};
    return normalizeContext({
      ...base,
      tenantId: source.tenant_id,
      scenarioId: source.scenario_id,
      branchId: source.branch_id,
      snapshotId: source.snapshot_id,
      asOf: source.as_of,
      dataVersion: source.data_version,
      factVersion: source.fact_version,
      isDemo: source.is_demo,
      sourceRefs: source.source_refs,
      missingFields: source.missing_fields,
      storeId: base.storeId || target.store_id,
      skuId: base.skuId || target.sku_id,
      lotId: base.lotId || target.lot_id,
      horizonStart: base.horizonStart || (source.as_of || "").slice(0, 10),
      horizonEnd: base.horizonEnd || selection.evaluation_end,
      actorId: base.actorId || (source.is_demo === true ? "manager-demo" : null),
    });
  }

  async function resolveModuleContext(base) {
    const api = getApiClient(base.tenantId, base.actorId);
    const scenarioId = base.scenarioId || "S01";
    const branchId = base.branchId || (scenarioId === "S01" ? "transfer_80" : null);
    if (!branchId) throw new Error("当前场景需要明确 branchId，无法安全读取事实。");
    const response = await api.getContext({ scenario_id: scenarioId, branch_id: branchId });
    const resolved = mapContextFromApi(response, { ...base, scenarioId, branchId });
    mergeContext(resolved);
    return resolved;
  }

  function navigate(route, nextContext) {
    if (!ROUTES.has(route)) return;
    mergeContext(nextContext);
    if (window.location.hash !== `#${route}`) window.location.hash = route;
    else mounted?.updateContext?.({ ...context });
  }

  function hostFor(route) {
    return document.querySelector(route === "decision-entry" ? "#hackathon-decision-host" : "#hackathon-followup-host");
  }

  function dispose() {
    if (!mounted) {
      mountedRoute = null;
      return;
    }
    try { mounted.destroy(); } catch (error) { console.error("Hackathon 模块卸载失败", error); }
    mounted = null;
    mountedRoute = null;
  }

  function setPreviewNotice(route) {
    const view = document.querySelector(`.module-view[data-view="${route}"]`);
    const notice = view && view.querySelector("[data-hackathon-preview-note]");
    if (notice) notice.hidden = !PREVIEW;
    if (view) view.toggleAttribute("data-hackathon-fixture-preview", PREVIEW);
  }

  async function loadDecisionModule() {
    if (!decisionModulePromise) {
      decisionModulePromise = import(new URL("decision/decision-workbench.mjs?v=20261004-context-fix", ASSET_BASE).href);
    }
    return decisionModulePromise;
  }

  async function mountDecision(host, mountContext) {
    const decision = await loadDecisionModule();
    if (PREVIEW) {
      const fixtureModule = await import(new URL("decision/preview-fixtures.mjs", ASSET_BASE).href);
      const api = window.HackathonApiClient.createApiClient({ mode: "fixture", fixtures: fixtureModule.createDecisionPreviewFixtures() });
      return decision.mount(host, { api, context: mountContext, navigate });
    }
    return decision.mount(host, { api: getApiClient(mountContext.tenantId, mountContext.actorId), context: mountContext, navigate });
  }

  function mountFollowup(host, mountContext) {
    if (!window.HackathonFollowup || typeof window.HackathonFollowup.mount !== "function") {
      throw new Error("未加载任务框 6 跟进模块。");
    }
    const options = PREVIEW
      ? { preview: { enabled: true }, context: mountContext, navigate }
      : { api: getApiClient(mountContext.tenantId, mountContext.actorId), context: mountContext, navigate };
    return window.HackathonFollowup.mount(host, options);
  }

  async function transition(route) {
    const generation = ++routeGeneration;
    if (!ROUTES.has(route)) {
      dispose();
      return;
    }
    if (mountedRoute === route && mounted) return;
    dispose();
    setPreviewNotice(route);
    const host = hostFor(route);
    if (!host) return;
    host.replaceChildren();
    const mountContextGeneration = contextGeneration;
    try {
      const mountContext = PREVIEW ? { ...context } : await resolveModuleContext({ ...context });
      if (generation !== routeGeneration || window.location.hash.slice(1) !== route) return;
      const instance = route === "decision-entry"
        ? await mountDecision(host, mountContext)
        : mountFollowup(host, mountContext);
      if (generation !== routeGeneration || window.location.hash.slice(1) !== route) {
        instance.destroy();
        return;
      }
      if (mountContextGeneration !== contextGeneration) instance.updateContext?.({ ...context });
      mounted = instance;
      mountedRoute = route;
    } catch (error) {
      if (generation !== routeGeneration) return;
      host.innerHTML = `<div class="hackathon-host-error" role="alert"><strong>模块暂时无法挂载</strong><p>${escapeHTML(error.message || "未知错误")}</p><small>这表示模块加载失败；不会将本地模拟结果记作接口成功。</small></div>`;
      console.error("Hackathon 模块挂载失败", error);
    }
  }

  function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
  }

  function routeFromLocation() { return window.location.hash.replace(/^#/, ""); }

  function refreshContext() {
    if (!PREVIEW) {
      const hostContext = readHostContext();
      const update = {};
      HOST_CONTEXT_KEYS.forEach((key) => { update[key] = hostContext[key]; });
      mergeContext(update);
      mounted?.updateContext?.({ ...context });
    }
  }

  window.addEventListener("retail:route-change", (event) => transition(event.detail && event.detail.route));
  window.addEventListener("hackathon:context-change", (event) => {
    const detail = event.detail || {};
    mergeContext(detail.patch || detail.context || {});
  });
  window.RetailHackathonIntegration = Object.freeze({
    refreshContext,
    getContext: () => ({ ...context }),
  });

  function boot() { transition(routeFromLocation()); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true });
  else boot();
})(window, document);
