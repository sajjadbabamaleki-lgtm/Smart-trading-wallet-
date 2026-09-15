// Renders whatever /api/state reports, and nothing else.
//
// There is no local state and no inference here on purpose: Invariant 4 says
// the frontend never infers critical state locally, and "trading is probably
// off because the environment looks like development" is exactly that kind of
// inference. Every claim on the page came from the backend.

const show = (id, text) => { document.getElementById(id).textContent = text; };

function tag(text, kind = "") {
  const el = document.createElement("span");
  el.className = `tag ${kind}`.trim();
  el.textContent = text;
  return el;
}

function card(name, tagText, tagKind, detail, available) {
  const li = document.createElement("li");
  li.className = available ? "available" : "unavailable";
  const row = document.createElement("div");
  row.className = "row";
  const label = document.createElement("span");
  label.className = "name";
  label.textContent = name;
  row.append(label, tag(tagText, tagKind));
  const note = document.createElement("p");
  note.className = "detail";
  note.textContent = detail;
  li.append(row, note);
  return li;
}

function renderSafety(safety) {
  const target = document.getElementById("safety");
  target.replaceChildren();
  const rows = [
    ["Execution environment", safety.execution_environment],
    ["Reaches real capital", safety.reaches_real_capital ? "YES" : "no"],
    ["Venue endpoint", safety.venue_endpoint ?? "none"],
    ["Trading enabled", safety.trading_enabled ? "YES" : "no"],
    ["Order submission", safety.may_submit_orders ? "POSSIBLE" : "impossible"],
    ["Signing credential", safety.credential_configured ? "configured" : "none"],
    ["Market data", safety.market_data_environment],
    ["Market data read-only", safety.market_data_is_read_only ? "yes" : "NO"],
    ["Asset allowlist", safety.asset_allowlist.join(", ")],
    ["Max order notional", safety.max_order_notional],
  ];
  for (const [term, value] of rows) {
    const wrap = document.createElement("div");
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = value;
    wrap.append(dt, dd);
    target.append(wrap);
  }
}

function renderBanner(safety) {
  const banner = document.getElementById("capital-banner");
  // Both conditions, because either one alone would let the banner say
  // something reassuring while the other was true.
  const safe = !safety.reaches_real_capital && !safety.may_submit_orders;
  banner.className = `banner ${safe ? "safe" : "danger"}`;
  banner.textContent = safe
    ? "No real capital reachable · order submission impossible"
    : "CAPITAL REACHABLE — check configuration immediately";
}

function render(state) {
  show("build-stage", state.build_stage);
  show("generated-at", new Date(state.generated_at).toLocaleString());
  renderBanner(state.safety);
  renderSafety(state.safety);

  const modes = document.getElementById("modes");
  modes.replaceChildren(...state.modes.map((mode) =>
    card(
      mode.name,
      mode.active ? "active" : mode.available ? "available" : "unavailable",
      mode.active ? "ok" : "",
      mode.detail,
      mode.available,
    ),
  ));

  const layers = document.getElementById("account-layers");
  layers.replaceChildren(...state.account_layers.map((layer) =>
    card(
      layer.name,
      layer.availability === "IMPLEMENTED" ? "connected" : "not built",
      layer.availability === "IMPLEMENTED" ? "ok" : "",
      `${layer.detail}${layer.milestone ? ` (${layer.milestone})` : ""}`,
      layer.availability === "IMPLEMENTED",
    ),
  ));

  const controls = document.getElementById("emergency");
  controls.replaceChildren(...state.emergency_controls.map((control) => {
    const li = document.createElement("li");
    const row = document.createElement("div");
    row.className = "row";
    const label = document.createElement("span");
    label.className = "name";
    label.textContent = control.name;
    row.append(label, tag(control.enabled ? "armed" : "inert"));
    const note = document.createElement("p");
    note.className = "detail";
    note.textContent = control.detail;
    li.append(row, note);
    return li;
  }));

  const capabilities = document.getElementById("capabilities");
  capabilities.replaceChildren(...state.capabilities.map((item) =>
    card(
      item.name,
      item.availability === "IMPLEMENTED" ? "built" : "not built",
      item.availability === "IMPLEMENTED" ? "ok" : "warn",
      `${item.detail}${item.milestone ? ` (${item.milestone})` : ""}`,
      item.availability === "IMPLEMENTED",
    ),
  ));
}

async function load() {
  try {
    const response = await fetch("/api/state");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch (error) {
    // A console that cannot reach the backend must say so rather than show a
    // stale page: the previous render's safety banner would still be sitting
    // there claiming capital is unreachable, which it can no longer verify.
    const banner = document.getElementById("capital-banner");
    banner.className = "banner danger";
    banner.textContent = `STATE UNAVAILABLE — ${error.message}`;
  }
}

load();
setInterval(load, 15000);
