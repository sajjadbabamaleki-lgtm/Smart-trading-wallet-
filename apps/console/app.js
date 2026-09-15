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

function topline(title, tag) {
  const bar = el("div", "topline");
  bar.append(el("h1", "title", title));
  if (tag) bar.append(el("span", "tag", tag));
  return bar;
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
  const b = el("button",
    `row act ${opts.danger ? "danger" : ""} ${opts.key ? "key" : ""}`.replace(/\s+/g, " ").trim());
  b.type = "button";
  b.disabled = opts.enabled !== true;
  const n = el("div", "n");
  n.append(document.createTextNode(name));
  if (sub) n.append(el("small", null, sub));
  b.append(n, html("span", "go", "&rsaquo;"));
  return b;
}

// §23: the mode is not a setting buried in Account, it is a persistent line at
// the top of every screen.
function modeBanner() {
  const m = S.mode;
  const bar = el("div", `mode ${m.name}`);
  bar.append(el("span", "dot"));
  bar.append(el("b", null, m.label));
  bar.append(el("span", "why", m.reason));
  return bar;
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
    frag.append(topline("Home", S.network));

    const hero = el("div", "herocard");
    hero.append(el("div", "k", "Trading equity"));
    hero.append(el("div", `big ${a.trading_equity === null ? "none" : ""}`.trim(),
      a.trading_equity === null ? "$—" : money(a.trading_equity)));
    hero.append(el("div", "sub", a.trading_equity === null
      ? a.reason
      : `Today ${signed(a.todays_pnl ?? 0)}`));
    const acts = el("div", "acts");
    // §56: the risk-reducing action is in the hero, not three taps down.
    acts.append(heroAct("Fund", ICON.plus, "#/wallet", { key: true }));
    acts.append(heroAct("Trade", ICON.chart, "#/trade"));
    acts.append(heroAct("Positions", ICON.bag, "#/positions"));
    acts.append(heroAct("Pause", ICON.pause, "#/positions"));
    hero.append(acts);
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
    frag.append(topline("Trade", m.available ? m.symbol : "offline"));

    const quote = el("div", "quote");
    if (m.available) {
      quote.append(el("div", "px", `$${usd(m.mid)}`));
      const pct = m.change_24h_pct;
      quote.append(el("div", `delta ${pct === null ? "" : pct >= 0 ? "up" : "down"}`.trim(),
        pct === null ? "24h —" : `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`));
    } else {
      quote.append(el("div", "px none", m.reason));
    }
    const qcard = el("div", "quotecard");
    qcard.append(quote);
    if (m.available) {
      qcard.append(el("div", "book",
        `Bid ${usd(m.bid)}  ·  Spread ${usd(m.ask - m.bid)}  ·  Ask ${usd(m.ask)}`));
    }
    frag.append(qcard);

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
    const exits = el("div", "exits");
    exits.append(exit(m, "tp"), exit(m, "sl"));
    frag.append(exits);

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
    frag.append(topline("Positions", open.length ? `${open.length} open` : "none open"));

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
      action("Close all positions", "Asks for confirmation first.", { danger: true }),
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
    frag.append(topline("Wallet", w.connected ? short(w.address) : S.network));

    const hero = el("div", "hero");
    hero.append(el("div", "k", "Wallet balance"));
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
      action("Fund trading account", "Source, network, asset and amount shown before you sign",
        { key: true }),
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

// --------------------------------------------------------------- components

const ICON = {
  plus: '<path d="M11 5h2v14h-2z"/><path d="M5 11h14v2H5z"/>',
  chart: '<path d="M4 18V11h3v7zm6.5 0V6h3v12zM17 18v-5h3v5z"/>',
  bag: '<path d="M9 3h6a2 2 0 0 1 2 2v1h2.5A1.5 1.5 0 0 1 21 7.5v11a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5v-11A1.5 1.5 0 0 1 4.5 6H7V5a2 2 0 0 1 2-2zm0 3h6V5H9z"/>',
  pause: '<path d="M8 5h3v14H8zm5 0h3v14h-3z"/>',
};

function heroAct(name, glyph, href, opts = {}) {
  const b = el("button", opts.key ? "go" : null);
  b.type = "button";
  b.onclick = () => { location.hash = href; };
  const ring = el("span", "ring");
  ring.append(svg(glyph));
  b.append(ring, el("span", null, name));
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
  head.append(el("span", "mark btc", "B"));
  const title = el("div", "sym");
  title.append(document.createTextNode(p.symbol));
  title.append(el("small", null, `${p.side === "long" ? "Long" : "Short"} · ${money(p.size_usd, 0)}`));
  head.append(title);
  head.append(el("span", `pct ${p.pnl_usd >= 0 ? "" : "neg"}`.trim(),
    `${p.pnl_usd >= 0 ? "↑" : "↓"} ${Math.abs(p.pnl_pct).toFixed(2)}%`));
  box.append(head);

  const up = p.pnl_usd >= 0;
  box.append(el("div", `big ${up ? "up" : "down"}`, signed(p.pnl_usd)));
  box.append(el("div", "meta", `Entry $${usd(p.entry)}  ·  now $${usd(p.mark)}`));

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
    target.replaceChildren(el("div", "empty", "Loading…"));
    return;
  }
  target.replaceChildren(modeBanner(), SCREENS[name]());
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
  tab = (location.hash.replace("#/", "") || "home").trim();
  render();
}

async function load() {
  try {
    S = await fetch("/api/app").then((r) => r.json());
  } catch {
    // Without backend state the app cannot say what mode it is in or whether
    // trading is off, so it says that rather than showing the last value.
    S = {
      mode: { name: "research", label: "OFFLINE", reason: "Cannot reach the server" },
      network: "offline",
      trading_enabled: false,
      can_submit_orders: false,
      assets: [],
      limits: { max_order_notional: null },
      health: { market_data: "unavailable", kill_switch: "engaged", credential: false, venue: "unknown" },
      market: { available: false, reason: "Cannot reach the server" },
      wallet: { connected: false, balance_usd: null, balances: [] },
      authorization: { granted: false, scope: null, expires: null },
      account: { trading_equity: null, available_margin: null, capital_at_risk: null,
        todays_pnl: null, reason: "Cannot reach the server" },
      positions: [],
    };
  }
  render();
}

window.addEventListener("hashchange", route);
route();
load();
setInterval(load, 15000);
