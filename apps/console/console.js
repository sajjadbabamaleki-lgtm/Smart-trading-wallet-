// The console renders what the backend reports, and infers nothing.
//
// Invariant 4: the frontend is not an authorization boundary and never infers
// critical state locally. "Trading is probably off because the environment
// looks like development" is exactly that inference, so every claim here came
// over the wire.
//
// Screens that have no data show an empty state naming the milestone that will
// fill them. That is the difference between an app that has not been built yet
// and an app pretending it has: this one never renders a zero for something
// that does not exist.

let STATE = null;
let DATA = null;

const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};

const fmt = (n) => (n === null || n === undefined ? "—" : n.toLocaleString("en-US"));
const when = (iso) => (iso ? new Date(iso).toLocaleString() : "—");

function head(title, note) {
  const wrap = el("div", "screen-head");
  wrap.append(el("h1", null, title));
  if (note) wrap.append(el("p", null, note));
  return wrap;
}

function stat(key, value, tone = "", small = false) {
  const box = el("div", "stat");
  box.append(el("div", "k", key));
  box.append(el("div", `v ${tone} ${small ? "sm" : ""}`.trim(), value));
  return box;
}

function empty(glyph, title, body, milestone) {
  const box = el("div", "empty");
  box.append(el("div", "glyph", glyph));
  box.append(el("h3", null, title));
  box.append(el("p", null, body));
  if (milestone) box.append(el("span", "ms", milestone));
  return box;
}

function rowItem(title, detail, pillText, pillTone) {
  const item = el("div", "row-item");
  const left = el("div");
  left.append(el("div", "t", title));
  if (detail) left.append(el("div", "d", detail));
  item.append(left, el("span", `pill ${pillTone}`.trim(), pillText));
  return item;
}

function table(columns, rows) {
  const t = el("table");
  const thead = el("thead");
  const hr = el("tr");
  for (const col of columns) {
    const th = el("th", col.num ? "num" : null, col.label);
    hr.append(th);
  }
  thead.append(hr);
  const tbody = el("tbody");
  for (const row of rows) {
    const tr = el("tr");
    for (const [index, cell] of row.entries()) {
      tr.append(el("td", columns[index].num ? "num" : null, cell));
    }
    tbody.append(tr);
  }
  t.append(thead, tbody);
  return t;
}

// ------------------------------------------------------------------ screens

const SCREENS = {
  dashboard() {
    const frag = document.createDocumentFragment();
    frag.append(head("Dashboard", "Live system state. BTC perpetuals on Hyperliquid."));

    const s = STATE.safety;
    const stats = el("div", "stats");
    stats.append(
      stat("Equity", "—", "", true),
      stat("Open positions", "0"),
      stat("Realised P&L", "—", "", true),
      stat("Orders today", "0"),
    );
    frag.append(stats);
    frag.append(
      empty(
        "◧",
        "No trading activity",
        "No order has ever been submitted and no position has ever been opened by this system. These tiles stay blank rather than showing a zero that would imply a live account.",
        "EXECUTION · M8",
      ),
    );

    frag.append(el("h2", "section", "Market data"));
    const dataStats = el("div", "stats");
    if (DATA && DATA.reachable) {
      dataStats.append(
        stat("Market events", fmt(DATA.total_market_events), "ok"),
        stat("Trader events", fmt(DATA.total_trader_events)),
        stat("Streams", String(DATA.streams.length)),
        stat("Venue", s.market_data_environment, "", true),
      );
    } else {
      dataStats.append(
        stat("Market events", "unreachable", "warn", true),
        stat("Store", "ClickHouse down", "warn", true),
      );
    }
    frag.append(dataStats);

    frag.append(el("h2", "section", "Safety"));
    const safety = el("div", "stats");
    safety.append(
      stat("Execution env", s.execution_environment, "", true),
      stat("Venue endpoint", s.venue_endpoint ?? "none", s.venue_endpoint ? "stop" : "ok", true),
      stat("Order submission", s.may_submit_orders ? "POSSIBLE" : "impossible",
        s.may_submit_orders ? "stop" : "ok", true),
      stat("Max order", s.max_order_notional, "", true),
    );
    frag.append(safety);
    return frag;
  },

  positions() {
    const frag = document.createDocumentFragment();
    frag.append(head("Positions", "Open exposure, margin and unrealised P&L."));
    frag.append(
      empty(
        "◧",
        "No positions",
        "The Execution Engine has not been built, so this system has never held a position. An empty table here would imply an account that could hold one.",
        "EXECUTION · M8",
      ),
    );
    return frag;
  },

  activity() {
    const frag = document.createDocumentFragment();
    frag.append(head("Activity", "Chronological ledger of decisions, orders and fills."));
    frag.append(
      empty(
        "≡",
        "No activity",
        "Nothing has been decided, ordered or filled. The ledger begins when the Risk Engine issues its first execution intent.",
        "RISK · M7",
      ),
    );
    return frag;
  },

  data() {
    const frag = document.createDocumentFragment();
    frag.append(head("Market data", "What the recorder has captured and stored."));

    if (!DATA) {
      frag.append(empty("◈", "Loading", "Reading from ClickHouse."));
      return frag;
    }
    if (!DATA.reachable) {
      frag.append(
        empty("◈", "Store unreachable", `ClickHouse did not answer: ${DATA.error}`),
      );
      return frag;
    }

    const stats = el("div", "stats");
    stats.append(
      stat("Market events", fmt(DATA.total_market_events), "ok"),
      stat("Trader events", fmt(DATA.total_trader_events)),
      stat("Streams", String(DATA.streams.length)),
    );
    frag.append(stats);

    frag.append(el("h2", "section", "By stream"));
    if (DATA.streams.length === 0) {
      frag.append(
        empty("◈", "No rows yet", "The recorder has not written anything to this store."),
      );
    } else {
      frag.append(
        table(
          [
            { label: "Stream" },
            { label: "Rows", num: true },
            { label: "First" },
            { label: "Last" },
          ],
          DATA.streams.map((s) => [s.event_type, fmt(s.count), when(s.first), when(s.last)]),
        ),
      );
    }
    return frag;
  },

  research() {
    const frag = document.createDocumentFragment();
    frag.append(head("Research", "Datasets, cost model and backtests."));

    const stats = el("div", "stats");
    stats.append(
      stat("Round trip cost", "10.0 bps", "warn"),
      stat("Taker fee", "4.5 bps"),
      stat("Data arrival floor", "322 ms", "warn"),
      stat("Strategies", "0"),
    );
    frag.append(stats);

    frag.append(el("h2", "section", "Built"));
    const rows = el("div", "rows");
    for (const item of STATE.capabilities) {
      const built = item.availability === "IMPLEMENTED";
      rows.append(
        rowItem(
          item.name,
          item.detail,
          built ? "BUILT" : item.milestone || "NOT BUILT",
          built ? "ok" : "warn",
        ),
      );
    }
    frag.append(rows);
    return frag;
  },

  risk() {
    const frag = document.createDocumentFragment();
    frag.append(
      head("Risk", "Hard limits sit outside the reach of this interface and of any model."),
    );

    const s = STATE.safety;
    const stats = el("div", "stats");
    stats.append(
      stat("Kill switch", s.trading_enabled ? "RELEASED" : "ENGAGED",
        s.trading_enabled ? "stop" : "ok", true),
      stat("Max order notional", s.max_order_notional),
      stat("Asset allowlist", s.asset_allowlist.join(", "), "", true),
      stat("Real capital", s.reaches_real_capital ? "REACHABLE" : "unreachable",
        s.reaches_real_capital ? "stop" : "ok", true),
    );
    frag.append(stats);

    frag.append(el("h2", "section", "Emergency controls"));
    const controls = el("div", "controls");
    for (const control of STATE.emergency_controls) {
      const button = el("button", "control");
      button.type = "button";
      button.disabled = !control.enabled;
      button.append(el("strong", null, control.name), el("small", null, control.detail));
      controls.append(button);
    }
    frag.append(controls);

    frag.append(el("h2", "section", "Risk Engine"));
    frag.append(
      empty(
        "⬡",
        "Risk Engine not built",
        "The capital-control boundary. Until it exists nothing may be authorized to trade, because nothing would bound it.",
        "M7",
      ),
    );
    return frag;
  },

  account() {
    const frag = document.createDocumentFragment();
    frag.append(
      head(
        "Account",
        "Three separate things: the wallet that owns and authorizes, the authorization itself, and the venue account where collateral lives.",
      ),
    );
    const rows = el("div", "rows");
    for (const layer of STATE.account_layers) {
      const built = layer.availability === "IMPLEMENTED";
      rows.append(
        rowItem(layer.name, layer.detail, built ? "CONNECTED" : layer.milestone, built ? "ok" : "warn"),
      );
    }
    frag.append(rows);
    return frag;
  },
};

// ------------------------------------------------------------------- chrome

function renderChrome() {
  const s = STATE.safety;

  const badge = document.getElementById("env-badge");
  const safe = !s.reaches_real_capital && !s.may_submit_orders;
  badge.className = `env ${safe ? "" : "danger"}`.trim();
  badge.textContent = safe ? `${s.execution_environment} · NO CAPITAL` : "CAPITAL REACHABLE";

  const kill = document.getElementById("killswitch");
  kill.className = `killswitch ${s.trading_enabled ? "live" : ""}`.trim();
  document.getElementById("killswitch-state").textContent =
    s.trading_enabled ? "released" : "engaged";

  const modes = document.getElementById("modes");
  modes.replaceChildren(
    ...STATE.modes.map((mode) => {
      const button = el("button", null, mode.name);
      button.type = "button";
      button.className = [mode.active ? "active" : "", mode.available ? "available" : ""]
        .filter(Boolean)
        .join(" ");
      button.title = mode.detail;
      button.disabled = !mode.available;
      return button;
    }),
  );

  document.getElementById("generated-at").textContent =
    `Updated ${new Date(STATE.generated_at).toLocaleTimeString()}`;
}

function route() {
  const name = (location.hash.replace("#/", "") || "dashboard").trim();
  const screen = SCREENS[name] ? name : "dashboard";
  for (const link of document.querySelectorAll("nav a")) {
    link.classList.toggle("active", link.dataset.route === screen);
  }
  const target = document.getElementById("screen");
  target.replaceChildren(STATE ? SCREENS[screen]() : el("div", "empty", "Loading…"));
  document.querySelector(".scroll").scrollTop = 0;
}

async function load() {
  try {
    const [state, data] = await Promise.all([
      fetch("/api/state").then((r) => r.json()),
      fetch("/api/data").then((r) => r.json()).catch(() => null),
    ]);
    STATE = state;
    DATA = data;
    renderChrome();
    route();
  } catch (error) {
    // A console that cannot reach the backend must say so. Leaving the last
    // render up would keep a safety badge asserting something it can no
    // longer verify.
    const badge = document.getElementById("env-badge");
    badge.className = "env danger";
    badge.textContent = "STATE UNAVAILABLE";
    document
      .getElementById("screen")
      .replaceChildren(empty("⚠", "Backend unreachable", String(error.message)));
  }
}

window.addEventListener("hashchange", route);
load();
setInterval(load, 15000);
