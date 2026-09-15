// Five screens: Home, Wallet, Trade, Swap, Account.
//
// What the app is for: you connect Phantom or Trust Wallet, and the platform
// opens the position for you with a stop loss and a take profit attached to
// it. So the exits are not an advanced option — they are the middle of the
// Trade screen, and the order is not sent without them.
//
// Everything on screen comes from /api/app. No wallet adapter exists yet, so
// the app is in the state every wallet app is in before you connect; balances
// are not invented while it is in that state.

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

const signed = (n, digits = 2) => `${n >= 0 ? "+" : "−"}$${usd(Math.abs(n), digits)}`;
const short = (a) => (a ? `${a.slice(0, 4)}…${a.slice(-4)}` : "—");

function topline(title, tag) {
  const bar = el("div", "topline");
  bar.append(el("h1", "title", title));
  if (tag) bar.append(el("span", "tag", tag));
  return bar;
}

function cap(text) {
  return el("div", "cap", text);
}

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

// --------------------------------------------------------------- connecting

const PHANTOM =
  '<path d="M20 11.4c0 4.2-3.5 7.6-7.9 7.6H4.6c-.6 0-1-.6-.7-1.1.5-1 .8-2.1.8-3.3v-3.2C4.7 7.2 8.2 4 12.4 4S20 7.2 20 11.4z"/>' +
  '<circle cx="10.2" cy="10.8" r="1.15" fill="#fff"/><circle cx="14.6" cy="10.8" r="1.15" fill="#fff"/>';
const TRUST = '<path d="M12 3l6.6 2.6v5.2c0 3.9-2.6 7.5-6.6 9.2-4-1.7-6.6-5.3-6.6-9.2V5.6z"/>';

function walletRow(name, sub, cls, glyph) {
  const b = el("button", "row tap");
  b.type = "button";
  b.disabled = true;
  const mark = el("span", `mark ${cls}`);
  mark.append(svg(glyph));
  const n = el("div", "n");
  n.append(document.createTextNode(name), el("small", null, sub));
  b.append(mark, n, html("span", "go", "&rsaquo;"));
  return b;
}

function connectRows() {
  return rows(
    walletRow("Phantom", "Solana · browser & mobile", "phantom", PHANTOM),
    walletRow("Trust Wallet", "WalletConnect", "trust", TRUST),
  );
}

// ------------------------------------------------------------------ screens

const SCREENS = {
  home() {
    const frag = document.createDocumentFragment();
    const w = S.wallet;
    const m = S.market;
    frag.append(topline("Home", S.network));

    const hero = el("div", "hero");
    hero.append(el("div", "cap", "Total balance"));
    if (w.connected) {
      hero.append(el("div", "big", `$${usd(w.total_usd)}`));
      const open = (S.positions ?? []).reduce((t, p) => t + p.pnl_usd, 0);
      const line = el("div", "sub");
      line.append(document.createTextNode("Open P&L "));
      line.append(el("span", open >= 0 ? "up" : "down", signed(open)));
      hero.append(line);
    } else {
      hero.append(el("div", "big none", "$—"));
      hero.append(el("div", "sub", "No wallet connected"));
    }
    frag.append(hero);

    if (!w.connected) {
      const go = el("button", "primary", "Connect wallet");
      go.type = "button";
      go.onclick = () => { location.hash = "#/wallet"; };
      frag.append(go);
    } else {
      const pair = el("div", "pair");
      for (const [name, href] of [["Trade", "#/trade"], ["Swap", "#/swap"]]) {
        const b = el("button", "quiet", name);
        b.type = "button";
        b.onclick = () => { location.hash = href; };
        pair.append(b);
      }
      frag.append(pair);
    }

    frag.append(cap("Market"));
    const btc = el("div", "row");
    btc.append(el("span", "mark btc", "B"));
    const n = el("div", "n");
    n.append(document.createTextNode("Bitcoin"), el("small", null, m.available ? m.symbol : "—"));
    btc.append(n);
    if (m.available) {
      const v = el("div", "v strong", `$${usd(m.mid)}`);
      const pct = m.change_24h_pct;
      v.append(el("small", pct === null ? null : pct >= 0 ? "up" : "down",
        pct === null ? "24h —" : `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`));
      btc.append(v);
    } else {
      btc.append(el("div", "v", m.reason));
    }
    frag.append(rows(btc));

    frag.append(cap("Autopilot"));
    frag.append(rows(
      row("Trade for me", S.autopilot ? "On" : "Off",
        { tone: S.autopilot ? "strong" : "", sub: "Opens and closes positions on its own" }),
      row("Exits on every trade", `${slPct}% / ${tpPct}%`, { sub: "Stop loss / take profit" }),
      row("Max position size", S.max_order_notional ? `$${usd(S.max_order_notional, 0)}` : "—"),
    ));

    frag.append(cap("Activity"));
    frag.append(el("div", "empty", (S.positions ?? []).length
      ? `${S.positions.length} position open. Its stop loss and take profit are on the Wallet tab.`
      : "Nothing yet. Trades placed here, and by Autopilot, appear in this list."));
    return frag;
  },

  wallet() {
    const frag = document.createDocumentFragment();
    const w = S.wallet;
    frag.append(topline("Wallet", w.connected ? short(w.address) : S.network));

    const hero = el("div", "hero");
    hero.append(el("div", "cap", "Total balance"));
    if (w.connected) {
      hero.append(el("div", "big", `$${usd(w.total_usd)}`));
      hero.append(el("div", "sub", `${w.provider} · ${S.network}`));
    } else {
      hero.append(el("div", "big none", "$—"));
      hero.append(el("div", "sub", "Connect a wallet to see your balance"));
    }
    frag.append(hero);

    if (!w.connected) {
      frag.append(cap("Connect"));
      frag.append(connectRows());
      frag.append(el("p", "note",
        "The platform trades from your wallet: it opens the position and places the stop loss and take profit with it. Your keys stay in your wallet — you grant permission to trade, never to withdraw."));
    } else {
      const pair = el("div", "pair");
      for (const name of ["Deposit", "Withdraw", "History"]) {
        const b = el("button", "quiet", name);
        b.type = "button";
        b.disabled = true;
        pair.append(b);
      }
      frag.append(pair);
    }

    frag.append(cap("Open positions"));
    const open = S.positions ?? [];
    if (open.length) {
      for (const p of open) frag.append(position(p));
    } else {
      frag.append(el("div", "empty",
        "No open positions. What you open on the Trade tab shows up here with its stop loss and take profit."));
    }

    if (w.connected && w.balances.length) {
      frag.append(cap("Assets"));
      const list = el("div", "rows");
      for (const b of w.balances) {
        const r = el("div", "row");
        r.append(el("span", `mark ${b.symbol === "BTC" ? "btc" : "plain"}`, b.symbol[0]));
        const n = el("div", "n");
        n.append(document.createTextNode(b.symbol), el("small", null, b.name));
        const v = el("div", "v strong", `$${usd(b.usd)}`);
        v.append(el("small", null, `${b.amount} ${b.symbol}`));
        r.append(n, v);
        list.append(r);
      }
      frag.append(list);
    }
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
    frag.append(quote);
    if (m.available) {
      frag.append(el("div", "book",
        `Bid ${usd(m.bid)}  ·  Spread ${usd(m.ask - m.bid)}  ·  Ask ${usd(m.ask)}`));
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

    // The exits. Prices come off the live quote, so they are real levels; the
    // P&L line stays a percentage until a size is entered, because a dollar
    // figure without a size would be made up.
    frag.append(cap("Exits"));
    frag.append(exit(m, "tp"));
    frag.append(exit(m, "sl"));

    const entry = entryPrice(m);
    const notional = size();
    frag.append(rows(
      row("Risk / reward", `1 : ${(tpPct / slPct).toFixed(1)}`, { tone: "strong" }),
      row("Entry", entry === null ? "Market" : `Market · $${usd(entry)}`),
      row("Est. fee", notional === null ? "0.045%" : `$${usd((notional * 4.5) / 10000, 3)}`),
    ));

    const limit = S.max_order_notional ?? null;
    const over = limit !== null && notional !== null && notional > limit;
    const cta = el("button", "primary",
      side === "buy" ? "Open long with SL / TP" : "Open short with SL / TP");
    cta.type = "button";
    // Only an affordance: the limit, the kill switch and the authorization are
    // all enforced server-side (Invariant 4). Greying the button out early
    // just saves a round trip that would be refused anyway.
    cta.disabled = !S.wallet.connected || !S.can_submit_orders || notional === null || over;
    frag.append(cta);
    frag.append(el("p", "note center", hint(over, limit)));
    return frag;
  },

  swap() {
    const frag = document.createDocumentFragment();
    const m = S.market;
    frag.append(topline("Swap", S.network));

    frag.append(leg("From", "USDC", "U", "plain"));
    frag.append(leg("To", "BTC", "B", "btc"));

    frag.append(rows(
      row("Rate", m.available ? `1 BTC ≈ $${usd(m.mid)}` : "—"),
      row("Max slippage", "0.50%"),
      row("Network", S.network),
    ));

    const cta = el("button", "primary",
      S.wallet.connected ? "Swap" : "Connect wallet to swap");
    cta.type = "button";
    cta.disabled = true;
    frag.append(cta);
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

    frag.append(cap("Autopilot"));
    const auto = el("div", "rows");
    const trade = el("div", "row");
    const label = el("div", "n");
    label.append(document.createTextNode("Trade for me"),
      el("small", null, "Opens and closes positions on its own"));
    const sw = el("div", `switch ${S.autopilot ? "on" : ""}`.trim());
    sw.append(el("i"));
    trade.append(label, sw);
    auto.append(trade);
    auto.append(row("Default stop loss", `${slPct}%`));
    auto.append(row("Default take profit", `${tpPct}%`));
    auto.append(row("Max position size",
      S.max_order_notional ? `$${usd(S.max_order_notional, 0)}` : "—"));
    auto.append(row("Assets", S.assets.length ? S.assets.join(", ") : "—"));
    frag.append(auto);

    frag.append(cap("Trading"));
    frag.append(rows(
      row("Network", S.network),
      row("Venue", "Hyperliquid"),
      row("Orders", S.trading_enabled ? "Enabled" : "Disabled",
        { tone: S.trading_enabled ? "strong" : "" }),
    ));

    frag.append(cap("Security"));
    frag.append(rows(
      row("Keys", "Never leave your wallet"),
      row("Withdrawals", "Not permitted"),
      row("Kill switch", S.trading_enabled ? "Released" : "Engaged"),
    ));
    return frag;
  },
};

// -------------------------------------------------------------- trade parts

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

  const box = el("div", "exit");
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
  if (over) return `Over the $${usd(limit, 0)} position limit set on this account.`;
  if (!S.wallet.connected) return "Connect Phantom or Trust Wallet to place this order.";
  if (!S.can_submit_orders) return "Trading is disabled on this build. No order can be submitted.";
  return "The stop loss and take profit are sent with the entry and held by the engine, not by this phone.";
}

function position(p) {
  const box = el("div", "pos");
  const head = el("div", "head");
  head.append(el("span", null, p.symbol));
  head.append(el("span", "side", `${p.side === "long" ? "Long" : "Short"} · $${usd(p.size_usd, 0)}`));
  box.append(head);

  const up = p.pnl_usd >= 0;
  box.append(el("div", `big ${up ? "up" : "down"}`, signed(p.pnl_usd)));
  box.append(el("div", "meta",
    `${up ? "+" : "−"}${Math.abs(p.pnl_pct).toFixed(2)}%  ·  entry $${usd(p.entry)}  ·  now $${usd(p.mark)}`));

  const span = p.take_profit - p.stop_loss;
  const at = span === 0 ? 50 : ((p.mark - p.stop_loss) / span) * 100;
  const rail = el("div", "rail");
  const dot = el("i");
  dot.style.left = `${Math.min(97, Math.max(3, at))}%`;
  rail.append(dot);
  box.append(rail);

  const ends = el("div", "ends");
  ends.append(html("span", "sl down", `<small>STOP LOSS</small>$${usd(p.stop_loss)}`));
  ends.append(html("span", "tp up", `<small>TAKE PROFIT</small>$${usd(p.take_profit)}`));
  box.append(ends);
  return box;
}

function leg(k, symbol, letter, cls) {
  const box = el("div", "leg");
  box.append(el("div", "k", k));
  const line = el("div", "row2");
  const input = document.createElement("input");
  input.type = "text";
  input.inputMode = "decimal";
  input.placeholder = "0";
  input.disabled = true;
  const picker = el("button", "picker");
  picker.type = "button";
  picker.disabled = true;
  picker.append(el("span", `mark ${cls}`, letter), el("span", null, symbol));
  line.append(input, picker);
  box.append(line);
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
  target.replaceChildren(S ? SCREENS[name]() : el("div", "empty", "Loading…"));
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
    // Without backend state the app cannot say what network it is on or
    // whether trading is off, so it shows neither rather than the last value.
    S = {
      network: "offline",
      trading_enabled: false,
      can_submit_orders: false,
      assets: [],
      market: { available: false, reason: "Cannot reach the server" },
      wallet: { connected: false, balances: [] },
    };
  }
  render();
}

window.addEventListener("hashchange", route);
route();
load();
setInterval(load, 15000);
