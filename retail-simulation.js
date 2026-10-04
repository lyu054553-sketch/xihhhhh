(function () {
  "use strict";

  const STORAGE_KEY = "huobuy aqian.retail.simulations.v1".replace(" ", "");
  const instances = new Map();
  const icon = (name) => `<span class="material-symbols-rounded" aria-hidden="true">${name}</span>`;
  const fallbackEscape = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[c]));
  const number = (value, digits = 0) => Number.isFinite(Number(value)) ? Number(value).toLocaleString("zh-CN", { maximumFractionDigits: digits }) : "—";

  function create(root, context) {
    let ctx = context;
    let options = { stores: [], categories: [], is_demo: null, as_of_date: null };
    let optionsReady = false;
    let optionsError = "";
    let optionsPromise = null;
    let optionsSignature = "";
    let draft = freshDraft();
    let messages = [];
    let result = null;
    let stage = "idle";
    let error = "";
    let missing = [];
    let editorOpen = false;
    let input = "";
    let generation = 0;
    let requestController = null;
    let resizeObserver = null;
    let history = readHistory();
    let historyId = null;
    let historyOpen = false;
    let saveNotice = "";
    let currentIsHistory = false;
    const escape = (value) => (ctx.escapeHtml || fallbackEscape)(value);
    const money = (value) => typeof value === "number" && Number.isFinite(value) ? (ctx.money ? ctx.money(value) : `¥${number(value)}`) : "—";
    const $ = (selector) => root.querySelector(selector);

    function freshDraft() {
      return { horizon_days: null, reduction_pct: null, store_id: "all", category: null, request_text: "" };
    }

    function readHistory() {
      try {
        const items = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
        return Array.isArray(items) ? items.filter((item) => item && typeof item.id === "string" && item.draft && item.result && item.result.status === "completed" && item.result.metrics && Array.isArray(item.messages)).slice(0, 12) : [];
      } catch (_) { return []; }
    }

    function saveHistory() {
      if (!result || result.status !== "completed") return;
      historyId = historyId || `sim-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const entry = { id: historyId, updated_at: new Date().toISOString(), title: draft.request_text || `未来 ${draft.horizon_days} 天采购减少 ${draft.reduction_pct}%`, draft: { ...draft }, messages: messages.slice(-30), result };
      history = [entry, ...history.filter((item) => item.id !== historyId)].slice(0, 12);
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(history)); saveNotice = ""; }
      catch (_) { saveNotice = "当前浏览器无法保存历史，会话在本次打开期间仍可查看。"; }
    }

    function scopeLabel() {
      if (draft.store_id === "all") return options.stores.length ? `全部 ${options.stores.length} 家门店` : "全部门店";
      return options.stores.find((store) => String(store.id) === String(draft.store_id))?.name || "请选择门店";
    }

    function validateDraft() {
      const problems = [];
      if (!Number.isInteger(draft.horizon_days) || draft.horizon_days < 1 || draft.horizon_days > 90) problems.push("模拟周期（1–90 天）");
      if (!Number.isFinite(draft.reduction_pct) || draft.reduction_pct < 0 || draft.reduction_pct > 100) problems.push("采购减少比例（0–100%）");
      if (draft.store_id !== "all" && !options.stores.some((store) => String(store.id) === String(draft.store_id))) problems.push("有效门店");
      if (draft.category && !options.categories.includes(draft.category)) problems.push("有效商品品类");
      return problems;
    }

    function invalidate() {
      generation += 1;
      if (requestController) requestController.abort();
      requestController = null;
      result = null;
      currentIsHistory = false;
      error = "";
      missing = [];
      if (messages.length) stage = "draft";
    }

    function chineseNumber(value) {
      if (/^\d+(?:\.\d+)?$/.test(value)) return Number(value);
      const values = { 零: 0, 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 };
      if (value === "百" || value === "一百") return 100;
      if (value.includes("十")) {
        const [a, b] = value.split("十");
        return (a ? values[a] : 1) * 10 + (b ? values[b] : 0);
      }
      return values[value];
    }

    function parseRequest(text) {
      const patch = {};
      const warnings = [];
      const numeral = "[0-9一二两三四五六七八九十百]+";
      const hasPurchase = /采购|补货|进货/.test(text);
      const hasReduction = /减少|减掉|降低|缩减|削减|少采购|少进货|少补货|采购少|减\s*\d|下调/.test(text);
      const unsupported = /增加采购|增加进货|多采购|多进货|提高采购|降价|促销|调拨|回款|释放.*[万亿]|减少.*[万亿]元/.test(text);
      if (unsupported) return { patch, warnings: ["当前支持按采购减少比例试算采购支出、库存占用和缺货风险。请补充类似“未来 14 天采购减少 20%”的条件；调拨、促销或回款目标需在对应业务模块处理。"], supported: false };

      const percent = text.match(/([0-9]+(?:\.[0-9]+)?)\s*[%％]/) || text.match(new RegExp(`百分之(${numeral})`));
      const chineseDiscount = text.match(new RegExp(`(?:减少|少采购|少进货|少补货|下调)\s*(${numeral})成`));
      if (percent && (hasPurchase || hasReduction || draft.reduction_pct !== null)) patch.reduction_pct = chineseNumber(percent[1]);
      else if (chineseDiscount) patch.reduction_pct = chineseNumber(chineseDiscount[1]) * 10;
      else if (/保持原计划|不减采购|不减少采购|不调整采购/.test(text)) patch.reduction_pct = 0;

      const days = text.match(new RegExp(`(${numeral})\s*天`));
      const weeks = text.match(new RegExp(`(${numeral})\s*(?:个)?(?:周|星期)`));
      const months = text.match(new RegExp(`(${numeral})\s*(?:个)?月`));
      if (days) patch.horizon_days = chineseNumber(days[1]);
      else if (weeks) patch.horizon_days = chineseNumber(weeks[1]) * 7;
      else if (months) patch.horizon_days = chineseNumber(months[1]) * 30;
      else if (/下周|一周|本周/.test(text)) patch.horizon_days = 7;
      else if (/下个月|下月|本月/.test(text)) patch.horizon_days = 30;

      if (/全部门店|所有门店|全店|全部\s*\d+\s*家/.test(text)) patch.store_id = "all";
      else {
        const matched = [...options.stores].sort((a, b) => b.name.length - a.name.length).find((store) => text.includes(store.name));
        if (matched) patch.store_id = String(matched.id);
        else if (/(?:只看|只算|范围.*?)[\u4e00-\u9fa5]{2,10}店/.test(text)) warnings.push("没有识别到该门店，请在场景卡中选择门店。");
      }
      if (/全部品类|所有品类|全部商品|所有商品|不限品类/.test(text)) patch.category = null;
      else {
        const match = [...options.categories].sort((a, b) => b.length - a.length).find((category) => text.includes(category));
        if (match) patch.category = match;
        else if (/(?:只看|只算|仅看|只模拟).*(?:类|品类|商品)/.test(text)) warnings.push("没有识别到该品类，请在场景卡中选择商品品类。");
      }
      const supported = Object.keys(patch).length > 0 || (hasPurchase && hasReduction);
      if (!supported) warnings.push("可以试算采购调整的影响。请告诉我模拟多少天、采购减少多少，例如“未来两周少采购 20%，会不会缺货？”");
      return { patch, warnings, supported };
    }

    function submitMessage(text) {
      text = String(text || "").trim();
      if (!text || stage === "running") return;
      input = "";
      messages.push({ role: "user", text });
      invalidate();
      const parsed = parseRequest(text);
      if (parsed.supported) {
        draft = { ...draft, ...parsed.patch, request_text: text };
        const needs = validateDraft();
        const message = needs.length ? `还需补充${needs.join("、")}。你可以继续告诉我，或直接修改下方场景卡。` : "我会对比原计划和调整后的方案。先确认这次模拟的范围与条件：";
        messages.push({ role: "agent", text: [...parsed.warnings, message].join("\n") });
        if (parsed.warnings.length) editorOpen = true;
        stage = "draft";
      } else {
        messages.push({ role: "agent", text: parsed.warnings.join("\n") });
        // A request outside this calculator must never be run as an older scenario.
        draft.request_text = "";
        stage = "clarify";
      }
      render();
      focusComposer();
    }

    function scenarioCard() {
      if (!messages.length || stage === "clarify") return "";
      const busy = stage === "running";
      const needs = validateDraft();
      const badge = busy ? "正在计算" : result ? (currentIsHistory ? "历史方案" : "已完成") : needs.length ? "待补充" : "待你确认";
      const editable = editorOpen && !busy;
      const rows = [
        ["门店范围", scopeLabel(), "store_id"],
        ["模拟周期", draft.horizon_days === null ? "请补充周期" : `未来 ${draft.horizon_days} 天`, "horizon_days"],
        ["调整条件", draft.reduction_pct === null ? "请补充减少比例" : `采购数量减少 ${number(draft.reduction_pct, 2)}%`, "reduction_pct"],
        ["商品品类", draft.category || "全部品类", "category"],
      ];
      return `<section class="retail-sim-scenario" aria-label="本次模拟条件">
        <div class="retail-sim-scenario-heading"><h2>本次模拟</h2><span class="retail-sim-badge ${result ? "retail-sim-badge-complete" : ""}">${badge}</span>${editable ? '<button type="button" class="retail-sim-text-button" data-retail-sim-action="editor-done">完成修改</button>' : ""}</div>
        ${editable ? `<div class="retail-sim-editor">
          <label>门店范围<select data-retail-sim-field="store_id"><option value="all">${escape(options.stores.length ? `全部 ${options.stores.length} 家门店` : "全部门店")}</option>${options.stores.map((store) => `<option value="${escape(store.id)}" ${String(store.id) === String(draft.store_id) ? "selected" : ""}>${escape(store.name)}</option>`).join("")}</select></label>
          <label>模拟周期 <span>1–90 天</span><input type="number" inputmode="numeric" min="1" max="90" step="1" value="${draft.horizon_days ?? ""}" placeholder="例如 14" data-retail-sim-field="horizon_days"></label>
          <label>采购减少比例 <span>0–100%</span><div class="retail-sim-percent-field"><input type="number" inputmode="decimal" min="0" max="100" step="0.1" value="${draft.reduction_pct ?? ""}" placeholder="例如 20" data-retail-sim-field="reduction_pct"><span>%</span></div></label>
          <label>商品品类<select data-retail-sim-field="category"><option value="all">全部品类</option>${options.categories.map((category) => `<option value="${escape(category)}" ${category === draft.category ? "selected" : ""}>${escape(category)}</option>`).join("")}</select></label>
        </div>` : `<div class="retail-sim-scenario-rows">${rows.map(([label, value, field]) => `<div class="retail-sim-scenario-row"><span>${label}</span><strong>${escape(value)}</strong><button type="button" class="retail-sim-text-button" data-retail-sim-action="edit" data-field="${field}" ${busy ? "disabled" : ""}>修改<span class="retail-sim-sr-only">${label}</span></button></div>`).join("")}</div>`}
        <p class="retail-sim-card-note">将比较：采购支出、期末库存占用、缺货风险</p>
        ${needs.length ? `<p class="retail-sim-validation" role="status">请补充${escape(needs.join("、"))}</p>` : ""}
        <button type="button" class="retail-sim-primary retail-sim-confirm" data-retail-sim-action="run" ${busy || needs.length || !optionsReady ? "disabled" : ""}>${busy ? `${icon("progress_activity")}正在计算方案` : result ? `重新模拟 ${icon("refresh")}` : `确认并开始模拟 ${icon("arrow_forward")}`}</button>
      </section>`;
    }

    function messageMarkup(message) {
      return `<article class="retail-sim-message retail-sim-message-${message.role === "user" ? "user" : "agent"}"><span class="retail-sim-avatar">${message.role === "user" ? icon("person") : '<img src="assets/brand-mark.png" alt="货不压钱">'}</span><div class="retail-sim-bubble">${escape(message.text).replace(/\n/g, "<br>")}</div></article>`;
    }

    function failureMarkup() {
      if (stage === "error") return `<div class="retail-sim-alert" role="alert">${icon("error")}<div><strong>这次没能完成计算</strong><p>${escape(error)}</p><button type="button" class="retail-sim-text-button" data-retail-sim-action="run">重新计算 ${icon("refresh")}</button></div></div>`;
      if (stage === "unavailable") return `<div class="retail-sim-alert" role="status">${icon("info")}<div><strong>还缺少计算所需的数据</strong><p>${escape(error || "补充以下数据后，就能比较两个方案。")}</p>${missing.length ? `<ul>${missing.map((item) => `<li>${escape(typeof item === "string" ? item : item.label || item.field || JSON.stringify(item))}</li>`).join("")}</ul>` : ""}<a href="#data" class="retail-sim-text-button">查看数据连接 ${icon("arrow_forward")}</a></div></div>`;
      return "";
    }

    function render() {
      const composerFocused = document.activeElement?.dataset?.retailSimInput === "message";
      const cursor = composerFocused ? document.activeElement.selectionStart : null;
      resizeObserver?.disconnect();
      root.classList.add("retail-sim-view");
      const hasResult = !!result?.metrics;
      const source = options.is_demo === true ? "演示数据" : options.is_demo === false ? "导入数据" : "正在读取数据";
      root.innerHTML = `<div class="retail-sim-page ${hasResult ? "retail-sim-has-result" : ""}">
        <header class="retail-sim-page-header"><div><h1>现金流模拟</h1><span class="retail-sim-source">${source}${options.as_of_date ? ` · ${escape(options.as_of_date)}` : ""}</span></div><nav aria-label="模拟会话操作"><button type="button" class="retail-sim-text-button" data-retail-sim-action="history">${icon("history")}历史会话${history.length ? `<span class="retail-sim-history-count">${history.length}</span>` : ""}</button>${messages.length ? `<button type="button" class="retail-sim-new" data-retail-sim-action="new">${icon("add")}新会话</button>` : ""}</nav></header>
        ${optionsError ? `<div class="retail-sim-data-error" role="alert">${icon("cloud_off")}<span>数据选项加载失败：${escape(optionsError)}</span><button type="button" class="retail-sim-text-button" data-retail-sim-action="reload-options">重试</button></div>` : ""}
        <div class="retail-sim-layout"><div class="retail-sim-conversation">
          ${!hasResult ? `<div class="retail-sim-intro"><span class="retail-sim-intro-icon">${icon("auto_awesome")}</span><h2>先聊聊，你想让哪笔钱松一松？</h2><p>说出你的经营想法，一起算算对库存与采购支出的影响</p></div>` : `<div class="retail-sim-conversation-title"><span>${icon("forum")}本次对话</span><small>${currentIsHistory ? "历史记录" : "可继续调整方案"}</small></div>`}
          <div class="retail-sim-thread" role="log" aria-label="模拟会话" aria-live="polite">${messages.map(messageMarkup).join("")}</div>
          ${!messages.length ? `<div class="retail-sim-starters"><p>可以这样问我</p><button type="button" data-retail-sim-prompt="未来两周少采购 20%，会不会缺货？"><span>${icon("shopping_bag")}未来两周少采购 20%，会不会缺货？</span>${icon("arrow_upward")}</button><button type="button" data-retail-sim-prompt="未来 30 天采购减少 10%，库存能降多少？"><span>${icon("inventory_2")}未来 30 天采购减少 10%，库存能降多少？</span>${icon("arrow_upward")}</button></div>` : ""}
          ${scenarioCard()}
          ${stage === "running" ? `<div class="retail-sim-progress" role="status"><span>${icon("progress_activity")}正在比较采购支出、库存占用与缺货风险…</span><button type="button" class="retail-sim-text-button" data-retail-sim-action="cancel">取消</button></div>` : ""}
          ${failureMarkup()}
          <div class="retail-sim-composer-wrap"><form class="retail-sim-composer" data-retail-sim-form="message"><label class="retail-sim-sr-only" for="retail-sim-input">描述采购模拟条件</label><textarea id="retail-sim-input" data-retail-sim-input="message" rows="1" maxlength="1200" placeholder="${messages.length ? "继续补充，例如：只看饮料类商品…" : "例如：未来两周少采购 20%，会不会缺货？"}" ${stage === "running" ? "disabled" : ""}>${escape(input)}</textarea><button type="submit" aria-label="发送模拟条件" ${stage === "running" || !optionsReady ? "disabled" : ""}>${icon("arrow_upward")}</button></form><p class="retail-sim-composer-note">${hasResult ? "继续描述新条件，确认后重新计算" : "确认后开始测算，结果将在生成后展开"}</p></div>
          ${saveNotice ? `<p class="retail-sim-save-notice">${escape(saveNotice)}</p>` : ""}
        </div>${hasResult ? resultMarkup() : ""}</div>
        <dialog class="retail-sim-history-dialog" aria-labelledby="retail-sim-history-title"><div class="retail-sim-history-header"><div><h2 id="retail-sim-history-title">历史会话</h2><p>本机保存最近 12 次完成的模拟</p></div><button type="button" class="retail-sim-icon-button" data-retail-sim-action="close-history" aria-label="关闭历史会话">${icon("close")}</button></div><div class="retail-sim-history-list">${history.length ? history.map((item) => `<button type="button" class="retail-sim-history-item" data-retail-sim-history="${escape(item.id)}"><span>${icon("chat_bubble")}<strong>${escape(item.title)}</strong></span><small>${escape(new Date(item.updated_at).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }))} · ${item.result.is_demo ? "演示数据" : "导入数据"}</small>${icon("chevron_right")}</button>`).join("") : `<div class="retail-sim-history-empty">${icon("history")}<strong>还没有完成的模拟</strong><p>确认场景并完成第一次计算后，会保存在这里。</p></div>`}</div></dialog>
      </div>`;
      const dialog = $(".retail-sim-history-dialog");
      dialog.addEventListener("close", () => { historyOpen = false; });
      dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
      if (historyOpen) dialog.showModal();
      if (hasResult) setupChart();
      if (composerFocused) {
        const textarea = $("[data-retail-sim-input]");
        textarea?.focus({ preventScroll: true });
        if (cursor !== null) textarea?.setSelectionRange(cursor, cursor);
      }
    }

    function metricMarkup(key, label, glyph, monetary) {
      const metric = result.metrics[key];
      if (!metric) return "";
      const baseline = monetary ? money(metric.baseline) : number(metric.baseline);
      const scenario = monetary ? money(metric.scenario) : number(metric.scenario);
      const delta = Number(metric.delta);
      const deltaText = delta === 0 ? "与原计划持平" : `${delta < 0 ? "减少" : "增加"} ${monetary ? money(Math.abs(delta)) : `${number(Math.abs(delta))} 项`}`;
      return `<article class="retail-sim-metric"><div>${icon(glyph)}<span>${label}</span></div><p><span>${baseline}</span>${icon("arrow_forward")}<strong>${scenario}</strong></p><small class="${delta > 0 ? "retail-sim-increase" : ""}">${escape(deltaText)}</small></article>`;
    }

    function resultMarkup() {
      const risks = Array.isArray(result.risks) ? result.risks : [];
      const newRisks = risks.filter((risk) => risk.is_new_risk).length;
      const assumptions = result.metadata?.assumptions || [];
      const resultSource = result.metadata?.is_demo ?? result.is_demo;
      return `<aside class="retail-sim-results" aria-label="模拟结果"><header class="retail-sim-result-header"><div><p>${currentIsHistory ? "历史方案 · " : ""}${resultSource ? "基于演示数据" : "基于导入数据"}</p><h2>基线与方案对比</h2></div><span>${icon("info")}结果为估算值</span></header>
        <div class="retail-sim-metrics">${metricMarkup("purchase_outflow", "预计采购支出", "shopping_bag", true)}${metricMarkup("ending_inventory_cost", "期末库存资金占用", "database", true)}${metricMarkup("stockout_risk_count", "缺货风险项", "warning", false)}</div>
        <section class="retail-sim-chart-card"><div class="retail-sim-section-heading"><h3>采购现金流出对比</h3><span>单位：元 · 按周汇总</span></div><div class="retail-sim-chart-legend"><span><i></i>基线（当前计划）</span><span><i></i>模拟方案（减少 ${number(result.scenario?.reduction_pct ?? draft.reduction_pct, 2)}%）</span></div><div class="retail-sim-chart-wrap"><canvas class="retail-sim-chart" role="img" aria-label="按周对比原计划与调整方案的采购支出，下方可展开完整数据"></canvas></div><details class="retail-sim-chart-data"><summary>查看每周数据</summary><div class="retail-sim-table-wrap"><table><thead><tr><th>时间</th><th>基线采购支出</th><th>方案采购支出</th></tr></thead><tbody>${(result.weekly || []).map((row) => `<tr><td>${escape(row.label)}</td><td>${money(row.baseline)}</td><td>${money(row.scenario)}</td></tr>`).join("")}</tbody></table></div></details></section>
        <section class="retail-sim-risks ${risks.length ? "retail-sim-risks-warning" : "retail-sim-risks-clear"}"><header>${icon(risks.length ? "warning" : "check_circle")}<div><h3>${risks.length ? `有 <em>${risks.length} 项</em>需要关注缺货风险` : "当前方案未识别到缺货风险"}</h3><p>${risks.length ? `按“门店 × 商品”统计${newRisks ? `，较原计划新增 ${newRisks} 项` : ""}；低于安全库存或发生缺货均需关注。` : "按当前销量和补货计划估算，实际销售变化仍会影响库存。"}</p></div></header>${risks.length ? `<div class="retail-sim-table-wrap"><table><thead><tr><th>商品 / 门店</th><th>基线可售天数</th><th>方案可售天数</th><th>安全阈值</th><th>风险</th></tr></thead><tbody>${risks.map((risk) => `<tr><td><strong>${escape(risk.product)}</strong><small>${escape(risk.store_name)}${risk.is_new_risk ? ' <span class="retail-sim-new-risk">新增</span>' : ""}</small></td><td>${number(risk.baseline_days, 1)} 天</td><td class="retail-sim-risk-number">${number(risk.scenario_days, 1)} 天</td><td>${number(risk.safety_days, 1)} 天</td><td><span class="retail-sim-risk-tag ${risk.risk_level === "high" ? "retail-sim-risk-high" : ""}">${risk.risk_level === "high" ? "预计缺货" : "低于安全库存"}</span></td></tr>`).join("")}</tbody></table></div>` : ""}</section>
        <details class="retail-sim-assumptions"><summary>${icon("fact_check")}计算依据与假设${icon("expand_more")}</summary><div><p>采购支出按当前可调整采购计划测算；库存占用按成本计。减少采购支出不等于已到账现金。</p>${assumptions.length ? `<ul>${assumptions.map((item) => `<li>${escape(typeof item === "string" ? item : JSON.stringify(item))}</li>`).join("")}</ul>` : ""}<p>范围：${escape(result.scenario?.store_name || scopeLabel())} · ${escape(result.scenario?.category || "全部品类")} · ${number(result.scenario?.horizon_days ?? draft.horizon_days)} 天</p></div></details>
      </aside>`;
    }

    function setupChart() {
      const canvas = $(".retail-sim-chart");
      if (!canvas) return;
      const draw = () => {
        const rows = result?.weekly || [];
        const width = canvas.parentElement.clientWidth;
        if (!width) return;
        const height = 230;
        const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = width * pixelRatio;
        canvas.height = height * pixelRatio;
        canvas.style.height = `${height}px`;
        const painter = canvas.getContext("2d");
        if (!painter) return;
        painter.scale(pixelRatio, pixelRatio);
        const inset = { left: width < 450 ? 46 : 57, right: 18, top: 18, bottom: 35 };
        const innerW = width - inset.left - inset.right;
        const innerH = height - inset.top - inset.bottom;
        const maxValue = Math.max(1, ...rows.flatMap((row) => [Number(row.baseline) || 0, Number(row.scenario) || 0]));
        const magnitude = 10 ** Math.floor(Math.log10(maxValue));
        const yMax = Math.ceil(maxValue / magnitude / 2) * magnitude * 2;
        painter.font = '11px "PingFang SC", system-ui, sans-serif';
        painter.textAlign = "right";
        const palette = getComputedStyle(document.body);
        const accent = palette.getPropertyValue('--retail-accent').trim() || '#176b50';
        painter.fillStyle = palette.getPropertyValue('--retail-muted').trim() || '#7b8585';
        painter.lineWidth = 1;
        for (let i = 0; i <= 4; i += 1) {
          const y = inset.top + innerH * i / 4;
          painter.strokeStyle = "#edf0ee";
          painter.beginPath(); painter.moveTo(inset.left, y); painter.lineTo(width - inset.right, y); painter.stroke();
          const value = yMax * (4 - i) / 4;
          painter.fillText(value >= 10000 ? `${number(value / 10000, 1)}万` : number(value), inset.left - 10, y + 4);
        }
        const getX = (i) => inset.left + (rows.length === 1 ? innerW / 2 : innerW * i / Math.max(1, rows.length - 1));
        painter.textAlign = "center";
        rows.forEach((row, i) => {
          if (rows.length > 7 && i % 2 !== 0 && i !== rows.length - 1) return;
          painter.fillText(row.label || `第${i + 1}周`, getX(i), height - 10);
        });
        [{ key: "baseline", color: accent, alpha: 1, dash: [] }, { key: "scenario", color: accent, alpha: .52, dash: [5, 5] }].forEach((line) => {
          painter.globalAlpha = line.alpha;
          painter.strokeStyle = line.color;
          painter.lineWidth = 2.2;
          painter.setLineDash(line.dash);
          painter.beginPath();
          rows.forEach((row, i) => {
            const y = inset.top + innerH * (1 - Number(row[line.key] || 0) / yMax);
            if (i === 0) painter.moveTo(getX(i), y); else painter.lineTo(getX(i), y);
          });
          painter.stroke(); painter.setLineDash([]); painter.fillStyle = line.color;
          rows.forEach((row, i) => { painter.beginPath(); painter.arc(getX(i), inset.top + innerH * (1 - Number(row[line.key] || 0) / yMax), 3.5, 0, Math.PI * 2); painter.fill(); });
          painter.globalAlpha = 1;
        });
      };
      draw();
      if (window.ResizeObserver) { resizeObserver = new ResizeObserver(draw); resizeObserver.observe(canvas.parentElement); }
    }

    async function run() {
      if (stage === "running" || !optionsReady || validateDraft().length || !draft.request_text) return;
      const token = ++generation;
      stage = "running";
      error = "";
      missing = [];
      result = null;
      editorOpen = false;
      currentIsHistory = false;
      requestController = new AbortController();
      let timedOut = false;
      const timeout = setTimeout(() => { timedOut = true; requestController?.abort(); }, 30000);
      render();
      try {
        const response = await ctx.api("/retail/simulate", { method: "POST", body: JSON.stringify({ ...draft }), signal: requestController.signal });
        if (token !== generation) return;
        if (response.status === "unavailable" || !response.metrics) {
          stage = "unavailable";
          missing = response.metadata?.missing || [];
          error = response.message || "当前数据不足以可靠计算，补充后可重新模拟。";
        } else if (response.status !== "completed") {
          throw new Error(response.message || "模拟服务未返回完整结果，请重试。");
        } else {
          result = response;
          stage = "completed";
          const delta = response.metrics.purchase_outflow?.delta;
          const riskDelta = response.metrics.stockout_risk_count?.delta;
          const spending = delta === 0 ? "采购支出与原计划持平" : `预计采购支出${delta < 0 ? "减少" : "增加"} ${money(Math.abs(delta))}`;
          const riskText = Number(riskDelta) > 0 ? `，同时新增 ${number(riskDelta)} 项缺货风险` : "";
          messages.push({ role: "agent", text: `${spending}${riskText}。完整对比已展开，你可以继续调整条件再试算。` });
          saveHistory();
        }
      } catch (err) {
        if (token !== generation) return;
        stage = "error";
        error = timedOut ? "计算超过 30 秒，请稍后重试。" : String(err.message || "网络连接失败，请重试。");
      } finally {
        clearTimeout(timeout);
        if (token === generation) { requestController = null; render(); }
      }
    }

    function focusComposer() {
      $("[data-retail-sim-input]")?.focus({ preventScroll: true });
    }

    function reset() {
      invalidate(); draft = freshDraft(); messages = []; input = ""; stage = "idle"; editorOpen = false; historyId = null; historyOpen = false;
      render(); focusComposer();
    }

    function openHistory(id) {
      const entry = history.find((item) => item.id === id);
      if (!entry) return;
      invalidate();
      draft = { ...entry.draft };
      messages = entry.messages.map((message) => ({ role: message.role === "user" ? "user" : "agent", text: String(message.text || "") }));
      result = entry.result;
      stage = "completed";
      historyId = entry.id;
      historyOpen = false;
      currentIsHistory = true;
      input = "";
      editorOpen = false;
      render();
    }

    async function refresh(nextContext) {
      if (nextContext) ctx = nextContext;
      if (optionsPromise) return optionsPromise;
      optionsPromise = (async () => {
        try {
          const data = await ctx.api("/retail/simulation-options");
          const signature = JSON.stringify(data);
          if (optionsSignature && signature !== optionsSignature && messages.length) {
            invalidate();
            messages.push({ role: "agent", text: "数据来源已更新，请重新确认本次范围与条件后计算。" });
          }
          optionsSignature = signature;
          options = { ...data, stores: Array.isArray(data.stores) ? data.stores : [], categories: Array.isArray(data.categories) ? data.categories : [] };
          optionsReady = true;
          optionsError = "";
        } catch (err) { optionsError = String(err.message || "无法连接数据服务"); }
        finally { optionsPromise = null; render(); }
      })();
      return optionsPromise;
    }

    root.addEventListener("submit", (event) => {
      if (event.target.matches('[data-retail-sim-form="message"]')) { event.preventDefault(); submitMessage(input); }
    });
    root.addEventListener("keydown", (event) => {
      if (event.target.matches("[data-retail-sim-input]") && event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); submitMessage(input); }
    });
    root.addEventListener("input", (event) => {
      if (event.target.matches("[data-retail-sim-input]")) {
        input = event.target.value;
        if (result && input.trim()) { invalidate(); render(); }
      }
    });
    root.addEventListener("change", (event) => {
      const field = event.target.dataset.retailSimField;
      if (!field) return;
      const value = event.target.value;
      invalidate();
      draft[field] = field === "category" ? (value === "all" ? null : value) : ["horizon_days", "reduction_pct"].includes(field) ? (value === "" ? null : Number(value)) : value;
      if (!draft.request_text) draft.request_text = "手动调整采购模拟条件";
      render();
      $(`[data-retail-sim-field="${field}"]`)?.focus({ preventScroll: true });
    });
    root.addEventListener("click", (event) => {
      const prompt = event.target.closest("[data-retail-sim-prompt]");
      if (prompt) { submitMessage(prompt.dataset.retailSimPrompt); return; }
      const historical = event.target.closest("[data-retail-sim-history]");
      if (historical) { openHistory(historical.dataset.retailSimHistory); return; }
      const button = event.target.closest("[data-retail-sim-action]");
      if (!button || button.disabled) return;
      switch (button.dataset.retailSimAction) {
        case "run": run(); break;
        case "new": reset(); break;
        case "cancel": invalidate(); render(); break;
        case "edit": {
          const field = button.dataset.field;
          editorOpen = true; render(); $(`[data-retail-sim-field="${field}"]`)?.focus(); break;
        }
        case "editor-done": editorOpen = false; render(); break;
        case "history": historyOpen = true; $(".retail-sim-history-dialog").showModal(); break;
        case "close-history": $(".retail-sim-history-dialog").close(); break;
        case "reload-options": refresh(); break;
      }
    });
    render();
    refresh();
    return { refresh };
  }

  window.RetailSimulation = {
    mount(root, context) {
      if (!root) return;
      if (!instances.has(root)) instances.set(root, create(root, context));
      return instances.get(root);
    },
    refresh(root, context) {
      if (root && instances.has(root)) return instances.get(root).refresh(context);
      return Promise.all([...instances.values()].map((instance) => instance.refresh(context)));
    },
  };
})();
