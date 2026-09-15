// Five screens: Home, Trade, Positions, Wallet, Account.
//
// What the app is for: you connect Phantom or Trust Wallet, and the platform
// opens the position itself with a stop loss and a take profit attached. So
// the exits are the middle of the Trade screen, not an advanced option.
//
// Shaped by Phase 9, which decides several things that look like styling and
// are not:
//   §23 the operating mode is on every screen, so nobody has to wonder
//       whether the system can place a trade right now.
//   §54 the emergency controls are six separate actions, never one red button.
//   §67 position, stop, liquidation, risk state and Autopilot state stay
//       visible on a phone; mobile may simplify presentation, not safety.
//   §76 wallet balance, trading equity, available margin and capital at risk
//       are four different numbers and are never added together.
//   §78 withdrawal is user-only and sits apart from the trading automation.
//
// Everything on screen comes from /api/app. No wallet adapter exists yet, so
// the app shows the ordinary pre-connect state instead of invented balances.

let S = null;
let error = null;
let seenAt = null;
let side = "buy";
let tab = "home";
let amount = "";
let tpPct = 4;
let slPct = 2;

const TP_STEPS = [2, 4, 6, 10];
const SL_STEPS = [1, 2, 3, 5];

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};
const html = (tag, cls, markup) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  n.innerHTML = markup;
  return n;
};
const svg = (markup) => {
  const n = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  n.setAttribute("viewBox", "0 0 24 24");
  n.setAttribute("fill", "currentColor");
  n.innerHTML = markup;
  return n;
};

const usd = (n, digits = 2) =>
  n === null || n === undefined
    ? "—"
    : n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const money = (n, digits = 2) => (n === null || n === undefined ? "—" : `$${usd(n, digits)}`);
const signed = (n, digits = 2) => `${n >= 0 ? "+" : "−"}$${usd(Math.abs(n), digits)}`;
const short = (a) => (a ? `${a.slice(0, 4)}…${a.slice(-4)}` : "—");

// §23 still applies — the mode has to be on every screen — but it does not
// need a banner across the top to do it. It rides in the corner of the title
// row, where the per-screen tag used to sit; each screen's own tag was
// repeating something already visible a line or two below it.
function topline(title) {
  const bar = el("div", "topline");
  bar.append(el("h1", "title", title));
  const m = S.mode;
  const chip = el("button", `modechip ${m.name}`);
  chip.type = "button";
  chip.append(el("i"), el("span", null, m.label));
  chip.onclick = () => openSheet(modeSheet());
  bar.append(chip);
  return bar;
}

// Tapping the mode opens what it actually means and what would change it —
// §23 asks that nobody wonder whether the system can trade, and the honest
// version of that is a sentence, not a colour.
function modeSheet() {
  const box = document.createDocumentFragment();
  box.append(el("h2", "sheet-title", S.mode.label));
  box.append(el("p", "sheet-lead", S.mode.reason));
  const list = rows(
    row("Places orders on its own", S.mode.name === "autopilot" ? "Yes" : "No"),
    row("Needs your approval", S.mode.name === "copilot" ? "Every order" : "—"),
    row("Kill switch", S.health.kill_switch === "engaged" ? "Engaged" : "Released",
      { tone: S.health.kill_switch === "engaged" ? "ok" : "" }),
    row("Signing credential", S.health.credential ? "Configured" : "None"),
    row("Market data", S.health.market_data === "ok" ? "Live" : "Unavailable",
      { tone: S.health.market_data === "ok" ? "ok" : "bad" }),
  );
  box.append(list);
  box.append(el("p", "note", S.can_submit_orders
    ? "Autopilot is a separate grant with nine checks of its own."
    : "Every one of these has to be true before an order can be sent."));
  return box;
}

const cap = (text) => el("div", "cap", text);

function row(name, value, opts = {}) {
  const r = el("div", "row");
  const n = el("div", "n");
  n.append(document.createTextNode(name));
  if (opts.sub) n.append(el("small", null, opts.sub));
  r.append(n);
  if (value !== undefined && value !== null) {
    const v = el("div", `v ${opts.tone ?? ""}`.trim(), value);
    if (opts.vsub) v.append(el("small", null, opts.vsub));
    r.append(v);
  }
  return r;
}

function rows(...children) {
  const box = el("div", "rows");
  for (const c of children) box.append(c);
  return box;
}

function action(name, sub, opts = {}) {
  const b = el("button", `row act ${opts.danger ? "danger" : ""}`.trim());
  b.type = "button";
  b.disabled = opts.enabled !== true;
  const n = el("div", "n");
  n.append(document.createTextNode(name));
  if (sub) n.append(el("small", null, sub));
  b.append(n, html("span", "go", "&rsaquo;"));
  return b;
}

// --------------------------------------------------------------- connecting

const PHANTOM =
  '<path d="M20 11.4c0 4.2-3.5 7.6-7.9 7.6H4.6c-.6 0-1-.6-.7-1.1.5-1 .8-2.1.8-3.3v-3.2C4.7 7.2 8.2 4 12.4 4S20 7.2 20 11.4z"/>' +
  '<circle cx="10.2" cy="10.8" r="1.15" fill="#fff"/><circle cx="14.6" cy="10.8" r="1.15" fill="#fff"/>';
const TRUST = '<path d="M12 3l6.6 2.6v5.2c0 3.9-2.6 7.5-6.6 9.2-4-1.7-6.6-5.3-6.6-9.2V5.6z"/>';

function walletRow(name, sub, cls, glyph) {
  const b = el("button", "row act");
  b.type = "button";
  b.disabled = true;
  const mark = el("span", `mark ${cls}`);
  mark.append(svg(glyph));
  const n = el("div", "n");
  n.append(document.createTextNode(name), el("small", null, sub));
  b.append(mark, n, html("span", "go", "&rsaquo;"));
  return b;
}

const connectRows = () =>
  rows(
    walletRow("Phantom", "Solana · browser & mobile", "phantom", PHANTOM),
    walletRow("Trust Wallet", "WalletConnect", "trust", TRUST),
  );

// ------------------------------------------------------------------ screens

const SCREENS = {
  // §32: equity, margin, P&L, capital at risk — then the market, then open
  // risk, then whether the system is healthy. §33: no win rate, no streaks.
  home() {
    const frag = document.createDocumentFragment();
    const a = S.account;
    frag.append(topline("Home"));

    const hero = el("div", "hero");
    hero.append(cap("Trading equity"));
    hero.append(el("div", `big ${a.trading_equity === null ? "none" : ""}`.trim(),
      a.trading_equity === null ? "$—" : money(a.trading_equity)));
    hero.append(el("div", "sub", a.trading_equity === null
      ? a.reason
      : `Today ${signed(a.todays_pnl ?? 0)}`));
    frag.append(hero);

    // §76: four numbers, side by side, never summed into one.
    const grid = el("div", "grid");
    grid.append(cell("Available margin", money(a.available_margin)));
    grid.append(cell("Capital at risk", money(a.capital_at_risk)));
    grid.append(cell("Wallet balance", money(S.wallet.balance_usd)));
    grid.append(cell("Open positions", String((S.positions ?? []).length)));
    frag.append(grid);

    if (!S.wallet.connected) {
      const go = el("button", "primary", "Connect wallet");
      go.type = "button";
      go.onclick = () => { location.hash = "#/wallet"; };
      frag.append(go);
    }

    frag.append(cap("Market"));
    frag.append(rows(marketRow()));

    frag.append(cap("Open risk"));
    const open = S.positions ?? [];
    if (open.length) {
      for (const p of open) frag.append(position(p, { compact: true }));
    } else {
      frag.append(el("div", "empty", "No open positions."));
    }

    // §51 / §65: the health of what trading depends on is part of the screen,
    // not a page you have to go looking for.
    frag.append(cap("System health"));
    frag.append(rows(
      row("Market data", S.health.market_data === "ok" ? "Live" : "Unavailable",
        { tone: S.health.market_data === "ok" ? "ok" : "bad" }),
      row("Kill switch", S.health.kill_switch === "engaged" ? "Engaged" : "Released",
        { tone: S.health.kill_switch === "engaged" ? "ok" : "" }),
      row("Signing credential", S.health.credential ? "Configured" : "None"),
      row("Venue", S.health.venue === "unknown" ? "Not checked" : S.health.venue),
    ));
    return frag;
  },

  trade() {
    const frag = document.createDocumentFragment();
    const m = S.market;
    frag.append(topline("Trade"));

    const quote = el("div", "quote");
    if (m.available) {
      quote.append(el("div", "px", `$${usd(m.mid)}`));
      const pct = m.change_24h_pct;
      quote.append(el("div", `delta ${pct === null ? "" : pct >= 0 ? "up" : "down"}`.trim(),
        pct === null ? "24h —" : `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`));
    } else {
      quote.append(el("div", "px none", m.reason));
    }
    if (m.available && m.stale) {
      quote.append(el("span", "warn", `${Math.round(m.age_seconds)}s old`));
    }
    frag.append(quote);
    if (m.available) {
      frag.append(el("div", "book",
        `Bid ${usd(m.bid)}  ·  Spread ${usd(m.ask - m.bid)}  ·  Ask ${usd(m.ask)}`));
      frag.append(m.history
        ? chart(m.history, {
            window: "6h",
            levels: [
              { price: exitPrice(m, tpPct, true), color: "var(--up)", label: "TP" },
              { price: exitPrice(m, slPct, false), color: "var(--down)", label: "SL" },
            ],
          })
        : el("div", "nochart", "No price history yet — the recorder has not been running long enough."));
    }

    const seg = el("div", "seg");
    for (const name of ["buy", "sell"]) {
      const b = el("button", `${name} ${side === name ? "on" : ""}`.trim(),
        name === "buy" ? "Buy / Long" : "Sell / Short");
      b.type = "button";
      b.onclick = () => { side = name; render(); };
      seg.append(b);
    }
    frag.append(seg);

    frag.append(cap("Position size"));
    const field = el("div", "size");
    const box = document.createElement("input");
    box.type = "text";
    box.inputMode = "decimal";
    box.placeholder = "0";
    box.value = amount;
    box.oninput = () => { amount = box.value; render({ keepFocus: true }); };
    field.append(box, el("span", "unit", "USD"));
    frag.append(field);

    // Exit prices come off the live quote, so they are real levels. The money
    // line stays a percentage until a size is entered, because a dollar figure
    // without a size would be made up.
    frag.append(cap("Exits"));
    frag.append(exit(m, "tp"));
    frag.append(exit(m, "sl"));

    const entry = entryPrice(m);
    const notional = size();
    const limit = S.limits.max_order_notional ?? null;
    const risk = notional === null ? null : (notional * slPct) / 100;

    // §73: the limit is stated as the concept it is — capital at risk against
    // a ceiling — rather than as a number on a slider.
    frag.append(rows(
      row("Capital at risk", money(risk),
        { tone: risk === null ? "" : "strong", sub: "What the stop loss costs if it fills" }),
      row("Position limit", money(limit, 0), { sub: "Enforced by the engine, not this screen" }),
      row("Risk / reward", `1 : ${(tpPct / slPct).toFixed(1)}`),
      row("Entry", entry === null ? "Market" : `Market · $${usd(entry)}`),
      // §67: liquidation stays on screen. It is unknown until leverage exists,
      // and saying so is different from leaving the row out.
      row("Liquidation", "None at 1×", { sub: "No leverage on this build" }),
      // §79: the fee is split, so a builder fee can never hide inside it.
      row("Trading fee", notional === null ? "0.045%" : money((notional * 4.5) / 10000, 3)),
      row("Builder fee", "None"),
    ));

    const over = limit !== null && notional !== null && notional > limit;
    const cta = el("button", "primary",
      side === "buy" ? "Open long with SL / TP" : "Open short with SL / TP");
    cta.type = "button";
    // Only an affordance: the limit, the kill switch and the authorization are
    // all enforced server-side (Invariant 4). Greying the button out early
    // saves a round trip that would be refused anyway.
    cta.disabled = !S.wallet.connected || !S.can_submit_orders || notional === null || over;
    frag.append(cta);
    frag.append(el("p", "note center", hint(over, limit)));
    return frag;
  },

  positions() {
    const frag = document.createDocumentFragment();
    const open = S.positions ?? [];
    frag.append(topline("Positions"));

    if (open.length) {
      for (const p of open) frag.append(position(p));
    } else {
      frag.append(el("div", "empty",
        "No open positions. What you open on the Trade tab appears here with its stop loss, take profit and liquidation price."));
    }

    // §54: six separate controls. §56: risk-reducing actions stay quick to
    // reach; §55: closing everything asks first.
    frag.append(cap("Emergency controls"));
    frag.append(rows(
      action("Pause Autopilot", "Stops new exposure. Open positions stay managed."),
      action("Cancel entry orders", "Working orders only. Positions untouched."),
      action("Reduce exposure", "Cut position size, keep the position open."),
      action("Close position", "Market exit for one position."),
      closeAllAction(),
      action("Revoke trading access", "The platform can no longer trade for you.", { danger: true }),
    ));
    frag.append(el("p", "note",
      "These are deliberately separate. One button that might pause, might close and might revoke is how the wrong thing gets pressed in a hurry."));
    return frag;
  },

  // §3: Layer A is your wallet, Layer B is the permission you grant, Layer C
  // is the trading account. The screen keeps them apart because the money in
  // each behaves differently.
  wallet() {
    const frag = document.createDocumentFragment();
    const w = S.wallet;
    frag.append(topline("Wallet"));

    const hero = el("div", "hero");
    hero.append(cap("Wallet balance"));
    hero.append(el("div", `big ${w.connected ? "" : "none"}`.trim(),
      w.balance_usd === null ? "$—" : money(w.balance_usd)));
    hero.append(el("div", "sub", w.connected
      ? `${w.provider} · ${S.network}`
      : "Connect a wallet to see your balance"));
    frag.append(hero);
    frag.append(el("p", "note",
      "This is what is in your wallet. It is not your trading equity, and neither number is the other."));

    if (!w.connected) {
      frag.append(cap("Connect"));
      frag.append(connectRows());
      frag.append(el("p", "note",
        "Your keys stay in your wallet. You grant permission to trade — never to withdraw."));
    }

    frag.append(cap("Trading authorization"));
    frag.append(rows(
      row("Status", S.authorization.granted ? "Active" : "Not granted",
        { tone: S.authorization.granted ? "ok" : "" }),
      row("Scope", S.authorization.scope ?? "—", { sub: "What the platform may do on your behalf" }),
      row("Expires", S.authorization.expires ?? "—"),
    ));

    // §77: funding says where the money goes. §78: withdrawal is yours alone
    // and does not sit next to the automation.
    frag.append(cap("Trading account"));
    frag.append(rows(
      row("Equity", money(S.account.trading_equity)),
      row("Available margin", money(S.account.available_margin)),
      action("Fund trading account", "Source, network, asset and amount shown before you sign"),
    ));

    frag.append(cap("Withdrawals"));
    frag.append(rows(action("Withdraw to your wallet", "You only. Automation never withdraws.")));

    if (w.connected && w.balances.length) {
      frag.append(cap("Assets"));
      const list = el("div", "rows");
      for (const b of w.balances) {
        const r = el("div", "row");
        r.append(el("span", `mark ${b.symbol === "BTC" ? "btc" : "plain"}`, b.symbol[0]));
        const n = el("div", "n");
        n.append(document.createTextNode(b.symbol), el("small", null, b.name));
        const v = el("div", "v strong", money(b.usd));
        v.append(el("small", null, `${b.amount} ${b.symbol}`));
        r.append(n, v);
        list.append(r);
      }
      frag.append(list);
    }
    return frag;
  },

  account() {
    const frag = document.createDocumentFragment();
    const w = S.wallet;
    frag.append(topline("Account"));

    const who = el("div", "who");
    who.append(el("span", "mark plain", w.connected ? w.provider[0] : "?"));
    const n = el("div");
    n.append(el("b", null, w.connected ? w.provider : "Not connected"));
    n.append(el("span", null, w.connected ? short(w.address) : "no wallet linked"));
    who.append(n);
    frag.append(who);

    if (!w.connected) {
      frag.append(cap("Connect"));
      frag.append(connectRows());
    }

    // §24/§25: entering a more permissive mode is an activation with
    // preconditions, not a switch you can brush with a thumb.
    frag.append(cap("Mode"));
    frag.append(rows(
      row("Current", S.mode.label, { tone: "strong", sub: S.mode.reason }),
      action("Activate Autopilot", "Nine checks must pass, and you confirm the summary"),
      action("Switch to Copilot", "Every trade waits for your approval"),
    ));

    // §72/§73: named, validated profiles and limits with an economic meaning.
    frag.append(cap("Risk"));
    frag.append(rows(
      row("Profile", "Conservative", { sub: "A validated configuration, not a leverage dial" }),
      row("Max position size", money(S.limits.max_order_notional, 0)),
      row("Default stop loss", `${slPct}%`, { sub: "Capital at risk per trade" }),
      row("Default take profit", `${tpPct}%`),
      row("Assets", S.assets.length ? S.assets.join(", ") : "—"),
    ));
    frag.append(el("p", "note",
      "You can set these below the system's ceiling, never above it."));

    frag.append(cap("Security"));
    frag.append(rows(
      row("Keys", "Never leave your wallet"),
      row("Withdrawals", "Not permitted to automation"),
      row("Kill switch", S.trading_enabled ? "Released" : "Engaged",
        { tone: S.trading_enabled ? "" : "ok" }),
      action("Revoke trading access", "Ends the platform's permission immediately", { danger: true }),
    ));
    return frag;
  },
};

// ------------------------------------------------------------------- chart

// A line through what the recorder actually captured. The exits are drawn on
// the same axis when they fall inside it, and as an edge marker when they do
// not — seeing that a stop sits far below anything the last six hours did is
// the point of putting both on one picture.
function chart(series, opts = {}) {
  const W = 320;
  const H = opts.height ?? 132;
  const lo0 = Math.min(...series);
  const hi0 = Math.max(...series);
  const pad = (hi0 - lo0) * 0.18 || Math.max(hi0 * 0.0005, 1);
  const lo = lo0 - pad;
  const hi = hi0 + pad;
  const x = (i) => (i / (series.length - 1)) * W;
  const y = (v) => H - ((v - lo) / (hi - lo)) * H;
  const rising = series[series.length - 1] >= series[0];
  const stroke = rising ? "var(--up)" : "var(--down)";
  const line = series
    .map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`)
    .join(" ");
  const id = `g${Math.random().toString(36).slice(2, 8)}`;

  const marks = (opts.levels ?? [])
    .filter((l) => l.price !== null && l.price !== undefined)
    .map((l) => {
      const inside = l.price > lo && l.price < hi;
      const at = inside ? y(l.price) : l.price >= hi ? 7 : H - 7;
      const text = (at + (at < 16 ? 13 : -6)).toFixed(1);
      return `<line x1="0" y1="${at.toFixed(1)}" x2="${W}" y2="${at.toFixed(1)}"
          stroke="${l.color}" stroke-width="1" vector-effect="non-scaling-stroke"
          stroke-dasharray="${inside ? "4 4" : "2 5"}" opacity="${inside ? 0.85 : 0.4}"/>
        <text x="3" y="${text}" text-anchor="start" fill="${l.color}"
          font-size="9" opacity="0.95">${l.label}</text>`;
    })
    .join("");

  const svg = html("div", "chart", `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${stroke}" stop-opacity="0.22"/>
          <stop offset="100%" stop-color="${stroke}" stop-opacity="0"/>
        </linearGradient>
      </defs>
      <path d="${line} L${W} ${H} L0 ${H} Z" fill="url(#${id})"/>
      <path d="${line}" fill="none" stroke="${stroke}" stroke-width="1.6"
        stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>
      ${marks}
      <circle cx="${(W - 2).toFixed(1)}" cy="${y(series[series.length - 1]).toFixed(1)}"
        r="2.6" fill="${stroke}"/>
    </svg>`);

  const axis = el("div", "axis");
  axis.append(el("span", null, opts.window ?? "6h"), el("span", null, "now"));
  const wrap = el("div");
  wrap.append(svg, axis);
  return wrap;
}

function spark(series) {
  const W = 64;
  const H = 22;
  const lo = Math.min(...series);
  const hi = Math.max(...series);
  const span = hi - lo || 1;
  const d = series
    .map((v, i) =>
      `${i ? "L" : "M"}${((i / (series.length - 1)) * W).toFixed(1)} ` +
      `${(H - ((v - lo) / span) * H).toFixed(1)}`)
    .join(" ");
  const rising = series[series.length - 1] >= series[0];
  return html("span", "spark", `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <path d="${d}" fill="none" stroke="${rising ? "var(--up)" : "var(--down)"}"
      stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round"
      vector-effect="non-scaling-stroke"/></svg>`);
}

// -------------------------------------------------------------------- sheet

function closeSheet() {
  const open = document.querySelector(".scrim");
  if (open) open.remove();
}

function openSheet(content) {
  closeSheet();
  const scrim = el("div", "scrim");
  const panel = el("div", "sheet");
  panel.append(el("div", "grip"));
  panel.append(content);
  const done = el("button", "primary ghost", "Close");
  done.type = "button";
  done.onclick = closeSheet;
  panel.append(done);
  scrim.append(panel);
  scrim.onclick = (e) => { if (e.target === scrim) closeSheet(); };
  document.body.append(scrim);
}

window.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSheet(); });

// --------------------------------------------------------------- components

// §55: the confirmation names the number of positions, the exposure and
// whether working orders go with them — before anything is closed.
function closeAllAction() {
  const open = S.positions ?? [];
  const b = action("Close all positions", "Asks for confirmation first.", { danger: true });
  b.disabled = false;
  b.onclick = () => {
    const box = document.createDocumentFragment();
    box.append(el("h2", "sheet-title", "Close all positions?"));
    box.append(el("p", "sheet-lead",
      "Every open position is closed at market. This cannot be undone."));
    const exposure = open.reduce((t2, p) => t2 + p.size_usd, 0);
    const risk = open.reduce((t2, p) => t2 + (p.risk_usd ?? 0), 0);
    box.append(rows(
      row("Positions", String(open.length)),
      row("Exposure", money(exposure, 0)),
      row("At risk to the stops", money(risk)),
      row("Working orders", "Cancelled with them"),
      row("Execution", "Market", { sub: "The fill is not the price above" }),
    ));
    const go = el("button", "primary danger", `Close ${open.length} position${open.length === 1 ? "" : "s"}`);
    go.type = "button";
    go.disabled = true;
    box.append(go);
    box.append(el("p", "note center", S.can_submit_orders
      ? "Not wired yet: the Risk Engine has to own this action before it exists."
      : S.mode.reason));
    openSheet(box);
  };
  return b;
}

function cell(name, value) {
  const c = el("div", "cell");
  c.append(el("div", "k", name));
  c.append(el("div", "v", value));
  return c;
}

function marketRow() {
  const m = S.market;
  const r = el("div", "row");
  r.append(el("span", "mark btc", "B"));
  const n = el("div", "n");
  n.append(document.createTextNode("Bitcoin"), el("small", null, m.available ? m.symbol : "—"));
  r.append(n);
  if (m.available) {
    const pct = m.change_24h_pct;
    if (m.history) r.append(spark(m.history));
    const v = el("div", "v strong", `$${usd(m.mid)}`);
    v.append(el("small", pct === null ? null : pct >= 0 ? "up" : "down",
      pct === null ? "24h —" : `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`));
    r.append(v);
  } else {
    r.append(el("div", "v", m.reason));
  }
  return r;
}

function entryPrice(m) {
  if (!m.available) return null;
  return side === "buy" ? m.ask : m.bid;
}

function exitPrice(m, pct, profit) {
  const entry = entryPrice(m);
  if (entry === null) return null;
  const up = profit === (side === "buy");
  return entry * (1 + (up ? pct : -pct) / 100);
}

function size() {
  const n = Number.parseFloat(amount.replace(/,/g, ""));
  return Number.isFinite(n) && n > 0 ? n : null;
}

function exit(m, kind) {
  const profit = kind === "tp";
  const pct = profit ? tpPct : slPct;
  const steps = profit ? TP_STEPS : SL_STEPS;
  const price = exitPrice(m, pct, profit);

  const box = el("div", `exit ${kind}`);
  const head = el("div", "head");
  head.append(el("span", "k", profit ? "Take profit" : "Stop loss"));
  head.append(el("span", `p ${profit ? "up" : "down"}`, price === null ? "—" : `$${usd(price)}`));
  box.append(head);

  const bar = el("div", "steps");
  for (const step of steps) {
    const b = el("button", step === pct ? "on" : null, `${profit ? "+" : "−"}${step}%`);
    b.type = "button";
    b.onclick = () => {
      if (profit) tpPct = step; else slPct = step;
      render();
    };
    bar.append(b);
  }
  box.append(bar);

  const n = size();
  box.append(el("div", "pnl", n === null
    ? `${profit ? "+" : "−"}${pct}% of your position`
    : `${profit ? "+" : "−"}$${usd((n * pct) / 100)} on $${usd(n, 0)}`));
  return box;
}

function hint(over, limit) {
  if (over) return `Over the ${money(limit, 0)} position limit set on this account.`;
  if (!S.wallet.connected) return "Connect Phantom or Trust Wallet to place this order.";
  if (!S.can_submit_orders) return S.mode.reason;
  return "The stop loss and take profit are sent with the entry and held by the engine, not by this phone.";
}

// §67: a position is shown risk-first — what it can lose, where it stops, and
// where it liquidates, before what it might make.
function position(p, opts = {}) {
  const box = el("div", "pos");
  const head = el("div", "head");
  head.append(el("span", null, p.symbol));
  head.append(el("span", "side", `${p.side === "long" ? "Long" : "Short"} · ${money(p.size_usd, 0)}`));
  box.append(head);

  const up = p.pnl_usd >= 0;
  box.append(el("div", `big ${up ? "up" : "down"}`, signed(p.pnl_usd)));
  box.append(el("div", "meta",
    `${up ? "+" : "−"}${Math.abs(p.pnl_pct).toFixed(2)}%  ·  entry $${usd(p.entry)}  ·  now $${usd(p.mark)}`));

  const span = p.take_profit - p.stop_loss;
  const at = span === 0 ? 50 : ((p.mark - p.stop_loss) / span) * 100;
  const rail = el("div", "rail");
  const fill = document.createElement("b");
  fill.style.width = `${Math.min(100, Math.max(0, at))}%`;
  const dot = el("i");
  dot.style.left = `${Math.min(97, Math.max(3, at))}%`;
  rail.append(fill, dot);
  box.append(rail);

  const ends = el("div", "ends");
  ends.append(html("span", "sl down", `<small>STOP LOSS</small>$${usd(p.stop_loss)}`));
  ends.append(html("span", "tp up", `<small>TAKE PROFIT</small>$${usd(p.take_profit)}`));
  box.append(ends);

  if (!opts.compact) {
    box.append(rows(
      row("At risk to the stop", money(p.risk_usd)),
      row("Liquidation", p.liquidation === null || p.liquidation === undefined
        ? "None at 1×" : `$${usd(p.liquidation)}`),
      row("Opened", p.opened ?? "—"),
    ));
  }
  return box;
}

// ------------------------------------------------------------------ routing

function render(opts = {}) {
  const name = SCREENS[tab] ? tab : "home";
  for (const link of document.querySelectorAll(".tabbar a")) {
    link.classList.toggle("active", link.dataset.tab === name);
  }
  const target = $("screen");
  const scroll = window.scrollY;
  if (!S) {
    target.replaceChildren(error ? errorScreen() : skeleton());
    return;
  }
  target.replaceChildren(...(error ? [offlineStrip(), SCREENS[name]()] : [SCREENS[name]()]));
  if (opts.keepFocus) {
    window.scrollTo(0, scroll);
    const field = target.querySelector(".size input");
    if (field) {
      field.focus();
      field.setSelectionRange(field.value.length, field.value.length);
    }
  } else {
    window.scrollTo(0, 0);
  }
}

function route() {
  // A sheet belongs to the screen that opened it; changing tabs behind it
  // leaves a panel describing something you are no longer looking at.
  closeSheet();
  tab = (location.hash.replace("#/", "") || "home").trim();
  render();
}

// The last state that really arrived is kept and labelled with when it
// arrived. Inventing an "offline" state would replace real numbers with
// made-up ones at exactly the moment the user most needs to know which is
// which.
async function load() {
  try {
    const response = await fetch("/api/app");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    S = await response.json();
    seenAt = new Date();
    error = null;
  } catch {
    error = "Cannot reach the server";
  }
  render();
}

function skeleton() {
  const box = el("div", "skeleton");
  box.append(el("div", "sk title"));
  box.append(el("div", "sk hero"));
  box.append(el("div", "sk tiles"));
  for (let i = 0; i < 4; i += 1) box.append(el("div", "sk line"));
  return box;
}

function errorScreen() {
  const box = el("div", "failure");
  box.append(el("h2", null, "Can't reach the server"));
  box.append(el("p", null,
    "Nothing is shown rather than something out of date, because there is no earlier state to show yet."));
  const retry = el("button", "primary", "Try again");
  retry.type = "button";
  retry.onclick = () => { error = null; render(); load(); };
  box.append(retry);
  return box;
}

function offlineStrip() {
  const bar = el("div", "offline");
  const when = seenAt
    ? seenAt.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
    : "—";
  bar.append(el("span", null, `Offline · last received ${when}`));
  const retry = el("button", null, "Retry");
  retry.type = "button";
  retry.onclick = () => load();
  bar.append(retry);
  return bar;
}

window.addEventListener("hashchange", route);
route();
load();
setInterval(load, 15000);
