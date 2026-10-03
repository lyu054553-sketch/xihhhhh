import "./decision-workbench.mjs";
import { createDecisionPreviewFixtures } from "./preview-fixtures.mjs";

if (!window.HackathonApiClient || !window.HackathonDecision) {
  throw new Error("预览需要先加载共享 HackathonApiClient 和决策组件。");
}

const api = window.HackathonApiClient.createApiClient({
  mode: "fixture",
  fixtures: createDecisionPreviewFixtures(),
});

const mounted = window.HackathonDecision.mount(document.querySelector("#decision-app"), {
  api,
  navigate: (route, context) => {
    const note = document.querySelector(".d-preview-note span");
    if (note) note.textContent = `预览导航：${route} · 场景 ${context.scenarioId} · 方案 ${context.proposalId || "尚未生成"}`;
  },
  context: {
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
  },
});

window.decisionPreview = {
  api,
  unmount: () => mounted.destroy(),
  updateContext: (context) => mounted.updateContext(context),
};
