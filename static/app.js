const DIR = { expense: "支出", income: "收入", refund: "退款", transfer: "划转", ignore: "不入账" };
const VIEWS = [
  ["home", "总览"],
  ["tx", "明细"],
  ["import", "导入"],
  ["members", "家人"],
  ["settings", "模型"],
];
const state = {
  view: "home",
  start: "",
  end: "",
  rangeKey: "latest",
  meta: null,
  members: [],
  settings: null,
  overview: null,
  tx: null,
  imports: [],
  bucket: "booked",
  q: "",
  poll: null,
  busy: false,
};

function h(tag, attrs, children) {
  const node = document.createElement(tag);
  Object.entries(attrs || {}).forEach(([key, value]) => {
    if (key === "class") node.className = value;
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (value != null && value !== false) node.setAttribute(key, value);
  });
  [].concat(children || []).forEach((child) => {
    if (child == null || child === false) return;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  });
  return node;
}

function yuan(cents) {
  const sign = cents < 0 ? "-" : "";
  const text = (Math.abs(cents) / 100).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return sign + text;
}

function when(iso) {
  return (iso || "").replace("T", " ").slice(0, 16);
}

function toast(message) {
  const node = document.getElementById("toast");
  node.hidden = false;
  node.textContent = message;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { node.hidden = true; }, 4200);
}

async function api(path, options) {
  const response = await fetch(path, options);
  const text = await response.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = { detail: text }; }
  if (!response.ok) {
    const detail = body && body.detail;
    throw new Error(typeof detail === "string" ? detail : "请求失败");
  }
  return body;
}

function qs(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) search.set(key, value);
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

function monthRange(ym) {
  const [year, month] = ym.split("-").map(Number);
  const last = new Date(year, month, 0).getDate();
  return { start: `${ym}-01`, end: `${ym}-${String(last).padStart(2, "0")}` };
}

function applyRange(key) {
  state.rangeKey = key;
  if (key === "all") {
    state.start = "";
    state.end = "";
  } else if (key === "latest" && state.meta && state.meta.latest_batch) {
    state.start = state.meta.latest_batch.period_start || "";
    state.end = state.meta.latest_batch.period_end || "";
  } else if (/^\d{4}-\d{2}$/.test(key)) {
    const range = monthRange(key);
    state.start = range.start;
    state.end = range.end;
  }
}

function renderNav() {
  const nav = document.getElementById("nav");
  nav.replaceChildren(...VIEWS.map(([id, label]) => h("button", {
    class: state.view === id ? "active" : "",
    onclick: () => { state.view = id; location.hash = `#/${id}`; render(); },
  }, label)));
  document.getElementById("heading").textContent = (VIEWS.find(([id]) => id === state.view) || VIEWS[0])[1];
  const household = (state.meta && state.meta.household_name) || "";
  const sub = document.getElementById("household");
  sub.textContent = household && household !== "家庭账本" ? household : "";
}

function renderRange() {
  const host = document.getElementById("range");
  if (state.view === "members" || state.view === "settings" || state.view === "import") {
    host.replaceChildren();
    return;
  }
  const chips = [["latest", "最近一份"], ["all", "全部"]];
  ((state.meta && state.meta.months) || []).forEach((month) => chips.push([month, month.replace("-", "年") + "月"]));
  host.replaceChildren(...chips.map(([key, label]) => h("button", {
    class: "chip" + (state.rangeKey === key ? " active" : ""),
    onclick: async () => { applyRange(key); await reloadData(); render(); },
  }, label)));
}

function prettyDate(iso) {
  return iso ? iso.replaceAll("-", ".") : "";
}

function categoryList(items) {
  const max = Math.max(...items.map((item) => item.cents), 1);
  if (!items.length) return h("p", { class: "muted" }, "还没有支出。");
  const rows = [];
  items.forEach((item) => {
    const fill = h("span", { class: "fill" });
    fill.style.width = `${item.cents / max * 100}%`;
    rows.push(
      h("span", { class: "cat-name" }, item.category),
      h("span", { class: "track" }, fill),
      h("span", { class: "amt" }, yuan(item.cents)),
    );
  });
  return h("div", { class: "cats" }, rows);
}

function summaryBlock(text) {
  const box = h("div", { class: "summary" });
  String(text || "").split(/\n+/).forEach((line) => {
    const trimmed = line.trim().replace(/^#{1,3}\s*/, "").replace(/^[-*]\s*/, "");
    if (!trimmed) return;
    const p = h("p");
    const parts = trimmed.split(/\*\*(.+?)\*\*/);
    parts.forEach((part, index) => {
      p.append(index % 2 ? h("strong", null, part) : document.createTextNode(part));
    });
    box.append(p);
  });
  return box;
}

async function renderHome() {
  const view = document.getElementById("view");
  view.replaceChildren(h("p", { class: "muted" }, "正在读取"));
  try {
    state.overview = await api("/api/overview" + qs({ start: state.start, end: state.end }));
  } catch (error) {
    view.replaceChildren(h("p", { class: "error" }, error.message));
    return;
  }
  const data = state.overview;
  if (!(state.meta && state.meta.span)) {
    view.replaceChildren(h("p", { class: "empty" }, "还没有账。到「导入」放入 CSV、Excel 或 PDF。"));
    return;
  }
  const write = h("button", { class: "ghost", onclick: writeSummary }, state.busy ? "正在写…" : "重写");
  write.disabled = state.busy;
  const simple = !data.refund_cents && !data.income_cents && !data.transfer_cents;
  const facts = [];
  if (data.start && data.end) facts.push(`${prettyDate(data.start)} – ${prettyDate(data.end)}`);
  facts.push(`${data.included_count} 笔入账`);
  if (data.excluded_count) facts.push(`${data.excluded_count} 笔未计入`);
  const extras = [];
  if (data.refund_cents) {
    extras.push(["支出", data.expense_cents]);
    extras.push(["退款", data.refund_cents]);
  }
  if (data.income_cents) extras.push(["收入", data.income_cents]);
  if (data.income_cents) extras.push(["结余", data.balance_cents]);
  if (data.transfer_cents) extras.push(["划转", data.transfer_cents]);
  const hero = h("section", { class: "hero" }, [
    h("div", null, [
      h("span", { class: "kicker" }, simple ? "支出" : "净支出"),
      h("p", { class: "money" }, yuan(data.net_expense_cents)),
      h("p", { class: "quiet" }, facts.join(" · ")),
      extras.length ? h("div", { class: "side-stats" }, extras.map(([label, cents]) => h("div", null, [
        h("span", { class: "kicker" }, label),
        h("strong", null, yuan(cents)),
      ]))) : null,
    ]),
  ]);
  const left = h("section", { class: "panel" }, [
    h("h2", null, "去向"),
    categoryList(data.categories || []),
  ]);
  const right = h("section", { class: "panel" }, [
    h("h2", null, "较大的几笔"),
    ...(data.top || []).map((item) => h("div", { class: "rowline" }, [
      h("time", null, when(item.occurred_at).slice(5, 10)),
      h("div", { class: "row-main" }, [
        h("span", { class: "title" }, item.title),
        h("span", { class: "tag" }, item.category),
      ]),
      h("span", { class: "amt" }, yuan(item.amount_cents)),
    ])),
    (data.top || []).length ? null : h("p", { class: "muted" }, "还没有支出。"),
  ]);
  const letter = h("section", { class: "letter" }, [
    h("div", { class: "letter-head" }, [h("h2", null, "说明"), write]),
    data.summary ? summaryBlock(data.summary.content) : h("p", { class: "muted" }, "这段范围还没有说明。"),
  ]);
  view.replaceChildren(hero, h("div", { class: "layout" }, [left, right]), letter);
}

async function writeSummary() {
  state.busy = true;
  renderHome();
  try {
    await api("/api/reports", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start: state.start, end: state.end }),
    });
    toast("说明写好了");
  } catch (error) {
    toast(error.message);
  } finally {
    state.busy = false;
    renderHome();
  }
}

async function renderTx() {
  const view = document.getElementById("view");
  const search = h("input", { type: "search", placeholder: "搜名称、对方、分类", value: state.q });
  search.addEventListener("change", async () => { state.q = search.value.trim(); await renderTx(); });
  const buckets = [["booked", "已入账"], ["expense", "支出"], ["refund", "退款"], ["income", "收入"], ["transfer", "划转"], ["excluded", "不入账"], ["all", "全部"]];
  const tools = h("div", { class: "tools" }, [
    search,
    ...buckets.map(([id, label]) => h("button", {
      class: "chip" + (state.bucket === id ? " active" : ""),
      onclick: async () => { state.bucket = id; await renderTx(); },
    }, label)),
    h("a", { class: "ghost", href: "/api/export.csv" + qs({ start: state.start, end: state.end }) }, "导出"),
  ]);
  view.replaceChildren(tools, h("p", { class: "muted" }, "正在读取"));
  try {
    state.tx = await api("/api/transactions" + qs({ start: state.start, end: state.end, bucket: state.bucket, q: state.q }));
  } catch (error) {
    view.replaceChildren(tools, h("p", { class: "error" }, error.message));
    return;
  }
  const rows = state.tx.items.map((item) => {
    const category = h("input", { type: "text", value: item.category, list: "categories" });
    category.addEventListener("change", () => patchTxn(item.id, { category: category.value }));
    const member = h("select", { onchange: (event) => patchTxn(item.id, { member_id: event.target.value || null }) }, [
      h("option", { value: "" }, "未指定"),
      ...state.members.map((person) => h("option", { value: person.id, selected: person.id === item.member_id }, person.name)),
    ]);
    return h("div", { class: "txn" + (item.included ? "" : " muted") }, [
      h("span", null, when(item.occurred_at).slice(5)),
      h("div", null, [
        h("div", { class: "title" }, item.title),
        h("div", { class: "muted" }, [item.counterparty, item.pay_method, item.note].filter(Boolean).join(" · ")),
      ]),
      category,
      member,
      h("div", { class: "amt " + item.direction }, [
        yuan(item.amount_cents),
        " ",
        h("span", { class: "tag" }, DIR[item.direction] || item.direction),
      ]),
    ]);
  });
  const list = h("datalist", { id: "categories" }, (state.meta.categories || []).map((name) => h("option", { value: name })));
  const head = h("div", { class: "txn head" }, ["日期", "账目", "分类", "家人", "金额"]);
  view.replaceChildren(tools, list, ...(rows.length ? [head, ...rows] : [h("p", { class: "empty" }, "这个范围里没有符合条件的账。")]));
  view.querySelectorAll("option[selected]").forEach((option) => { option.selected = true; });
}

async function patchTxn(id, body) {
  try {
    await api(`/api/transactions/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (error) {
    toast(error.message);
  }
}

function renderImportList() {
  const host = document.getElementById("import-list");
  const heading = document.getElementById("import-heading");
  if (!host) return;
  if (heading) heading.hidden = !state.imports.length;
  host.replaceChildren(...state.imports.map((item) => {
    const actions = [];
    if (item.status !== "running") {
      actions.push(h("button", { class: "ghost", onclick: () => retryImport(item.id) }, "让模型重读"));
      actions.push(h("button", { class: "ghost", onclick: () => removeImport(item.id) }, "删除这批"));
    }
    const bar = h("div", { class: "bar" }, h("span"));
    bar.firstChild.style.width = `${item.progress || (item.status === "done" ? 100 : 0)}%`;
    return h("article", { class: "import-item" }, [
      h("strong", null, item.filename),
      " ",
      h("span", { class: "tag" }, item.status === "running" ? "阅读中" : item.status === "error" ? "失败" : "已入账"),
      h("p", { class: item.status === "error" ? "error" : "muted" }, item.error || item.message || "等待模型"),
      item.status === "running" ? bar : null,
      h("div", { class: "tools" }, actions),
    ]);
  }));
}

async function renderImport() {
  const view = document.getElementById("view");
  const input = h("input", { type: "file", accept: ".csv,.xlsx,.xls,.pdf,text/csv", multiple: "multiple" });
  input.addEventListener("change", () => { if (input.files.length) uploadFiles(input.files); });
  const drop = h("div", { class: "drop", onclick: () => input.click() }, [
    h("strong", null, "把账单放到这里"),
    h("p", { class: "muted" }, "CSV、Excel 或 PDF"),
    h("button", { class: "primary", type: "button" }, "选择文件"),
  ]);
  ["dragover", "dragenter"].forEach((name) => drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.add("hot");
  }));
  drop.addEventListener("dragleave", () => drop.classList.remove("hot"));
  drop.addEventListener("drop", (event) => {
    event.preventDefault();
    drop.classList.remove("hot");
    if (event.dataTransfer.files.length) uploadFiles(event.dataTransfer.files);
  });
  view.replaceChildren(drop, input, h("h2", { id: "import-heading" }, "已经导入"), h("div", { id: "import-list" }));
  await refreshImports();
  renderImportList();
}

async function uploadFiles(files) {
  for (const file of files) {
    const form = new FormData();
    form.append("file", file);
    try {
      const result = await api("/api/imports", { method: "POST", body: form });
      toast(result.duplicate_file ? "这份文件已经记过了" : "已交给模型阅读");
    } catch (error) {
      toast(error.message);
    }
  }
  await refreshImports();
  if (state.view === "import") renderImportList();
  ensurePoll();
}

async function retryImport(id) {
  try {
    await api(`/api/imports/${id}/reanalyze`, { method: "POST" });
    toast("模型会重新读这份文件");
    await refreshImports();
    renderImportList();
    ensurePoll();
  } catch (error) {
    toast(error.message);
  }
}

async function removeImport(id) {
  if (!confirm("删除这批账？已经记入的交易会一起去掉。")) return;
  try {
    await api(`/api/imports/${id}`, { method: "DELETE" });
    await refreshImports();
    await loadMeta();
    renderImportList();
  } catch (error) {
    toast(error.message);
  }
}

async function renderMembers() {
  const view = document.getElementById("view");
  const name = h("input", { type: "text", placeholder: "名字，例如妈妈" });
  const note = h("input", { type: "text", placeholder: "备注，可不填" });
  const form = h("form", { class: "tools", onsubmit: async (event) => {
    event.preventDefault();
    try {
      await api("/api/members", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.value, note: note.value }),
      });
      name.value = "";
      note.value = "";
      await loadMembers();
      renderMembers();
    } catch (error) {
      toast(error.message);
    }
  } }, [name, note, h("button", { class: "primary" }, "添加")]);
  const list = state.members.map((person) => h("div", { class: "member" }, [
    h("div", null, [h("strong", null, person.name), person.note ? h("div", { class: "muted" }, person.note) : null]),
    h("button", { class: "ghost", onclick: async () => {
      await api(`/api/members/${person.id}`, { method: "DELETE" });
      await loadMembers();
      renderMembers();
    } }, "移除"),
  ]));
  view.replaceChildren(
    h("div", { class: "sheet" }, [
      form,
      ...(list.length ? list : [h("p", { class: "empty" }, "还没有家人。")]),
    ]),
  );
}

async function renderSettings() {
  const view = document.getElementById("view");
  const current = state.settings || {};
  const household = h("input", { type: "text", value: current.household_name || "" });
  const base = h("input", { type: "text", value: current.base_url || "" });
  const model = h("input", { type: "text", value: current.model || "" });
  const key = h("input", { type: "password", placeholder: current.api_key_set ? `已保存（${current.api_key_hint}），留空则不修改` : "密钥" });
  const result = h("p", { class: "muted" });
  async function save() {
    try {
      state.settings = await api("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          household_name: household.value,
          base_url: base.value,
          model: model.value,
          api_key: key.value,
        }),
      });
      key.value = "";
      await loadMeta();
      renderNav();
      toast("已保存");
      renderSettings();
    } catch (error) {
      toast(error.message);
    }
  }
  async function test() {
    result.textContent = "正在连接…";
    try {
      const body = await api("/api/settings/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base_url: base.value, model: model.value, api_key: key.value }),
      });
      result.textContent = "已连通。模型回复：" + (body.reply || "");
    } catch (error) {
      result.textContent = error.message;
      result.className = "error";
    }
  }
  let folder = null;
  if (window.pywebview && window.pywebview.api) {
    folder = h("button", { class: "ghost", onclick: () => window.pywebview.api.perform("open_data", {}) }, "打开数据文件夹");
  }
  view.replaceChildren(
    h("div", { class: "sheet" }, [
      h("label", { class: "field" }, ["家里的名称", household]),
      h("label", { class: "field" }, ["接口地址", base]),
      h("label", { class: "field" }, ["模型", model]),
      h("label", { class: "field" }, ["密钥", key]),
      h("div", { class: "tools" }, [
        h("button", { class: "primary", onclick: save }, "保存"),
        h("button", { class: "ghost", onclick: test }, "测试连接"),
        folder,
      ]),
      result,
      state.health ? h("p", { class: "muted" }, state.health.data_dir) : null,
    ]),
  );
}

async function render() {
  const hash = (location.hash || "#/home").replace("#/", "") || "home";
  state.view = VIEWS.some(([id]) => id === hash) ? hash : "home";
  renderNav();
  renderRange();
  if (state.view === "home") await renderHome();
  else if (state.view === "tx") await renderTx();
  else if (state.view === "import") await renderImport();
  else if (state.view === "members") await renderMembers();
  else await renderSettings();
}

async function loadMeta() {
  state.meta = await api("/api/meta");
}

async function loadMembers() {
  state.members = await api("/api/members");
}

async function refreshImports() {
  state.imports = await api("/api/imports");
}

function ensurePoll() {
  if (state.poll || !state.imports.some((item) => item.status === "running")) return;
  state.poll = setInterval(async () => {
    const before = new Map(state.imports.map((item) => [item.id, item.status]));
    await refreshImports();
    state.imports.forEach((item) => {
      if (before.get(item.id) === "running" && item.status === "done") toast(item.message || "已经入账");
      if (before.get(item.id) === "running" && item.status === "error") toast(item.error || "导入失败");
    });
    if (state.view === "import") renderImportList();
    if (!state.imports.some((item) => item.status === "running")) {
      clearInterval(state.poll);
      state.poll = null;
      await loadMeta();
      if (state.rangeKey === "latest") applyRange("latest");
      if (state.view === "home" || state.view === "tx") render();
    }
  }, 800);
}

async function reloadData() {
  if (state.view === "home" || state.view === "tx") await render();
}

document.addEventListener("dragover", (event) => event.preventDefault());
document.addEventListener("drop", (event) => {
  if (!event.dataTransfer || !event.dataTransfer.files || !event.dataTransfer.files.length) return;
  if (event.target.closest && event.target.closest(".drop")) return;
  event.preventDefault();
  location.hash = "#/import";
  uploadFiles(event.dataTransfer.files);
});
window.addEventListener("hashchange", render);

(async function boot() {
  try {
    state.health = await api("/api/health");
    await Promise.all([loadMeta(), loadMembers(), api("/api/settings").then((value) => { state.settings = value; }), refreshImports()]);
    applyRange(state.meta.latest_batch ? "latest" : "all");
    await render();
    ensurePoll();
  } catch (error) {
    document.getElementById("view").replaceChildren(h("p", { class: "error" }, error.message));
  }
}());
