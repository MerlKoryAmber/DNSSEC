(() => {
  const root = document.getElementById("root");
  const toasts = document.getElementById("toasts");
  let user = null;
  let zonesCache = [];
  let zonesSort = { key: "name", dir: 1 };
  let recordsCache = [];
  let recordsSort = { key: "name", dir: 1 };
  let forwardersList = [];
  let uiPrefs = { timezone: "Europe/Moscow", options: [] };

  function parseRoute() {
    const h = (location.hash || "#/dashboard").replace(/^#/, "");
    const parts = h.split("/").filter(Boolean);
    if (parts[0] === "login") return { name: "login" };
    if (parts[0] === "dashboard" || parts[0] === "home") return { name: "dashboard", type: parts[1] || "LastHour" };
    if (parts[0] === "zones" && parts[1]) return { name: "records", zone: decodeURIComponent(parts[1]) };
    if (parts[0] === "zones") return { name: "zones" };
    if (parts[0] === "forwarders" || parts[0] === "upstream") return { name: "forwarders" };
    if (parts[0] === "protocols" || parts[0] === "client-protocol") return { name: "protocols" };
    if (parts[0] === "settings") return { name: "settings", tab: parts[1] || "general" };
    if (parts[0] === "blocking" || parts[0] === "blocked") {
      if (parts[1] === "log") return { name: "querylog" };
      if (parts[1] === "settings") return { name: "settings", tab: "blocking" };
      return { name: "blocking", tab: parts[1] || "lists" };
    }
    if (parts[0] === "query-log" || parts[0] === "querylog" || parts[0] === "logs") {
      return { name: "querylog" };
    }
    return { name: "dashboard", type: "LastHour" };
  }

  function toast(msg, kind = "ok") {
    const el = document.createElement("div");
    el.className = "toast " + kind;
    el.textContent = msg;
    toasts.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }

  function openChangePasswordModal() {
    return new Promise((resolve) => {
      const back = document.createElement("div");
      back.className = "modal-back";
      back.innerHTML = `
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="pwdTitle">
          <h3 id="pwdTitle">Change password</h3>
          <p>DNS server account (${escapeHtml(displayName())}). Session stays signed in.</p>
          <div class="form-error" id="pwdErr"></div>
          <div class="field">
            <label for="pwdCur">Current password</label>
            <input id="pwdCur" type="password" autocomplete="current-password" required />
          </div>
          <div class="field">
            <label for="pwdNew">New password</label>
            <input id="pwdNew" type="password" autocomplete="new-password" required />
          </div>
          <div class="field">
            <label for="pwdNew2">Confirm new password</label>
            <input id="pwdNew2" type="password" autocomplete="new-password" required />
          </div>
          <div class="modal-actions">
            <button type="button" class="btn btn-secondary" data-a="cancel">Cancel</button>
            <button type="button" class="btn" data-a="ok">Save</button>
          </div>
        </div>`;
      document.body.appendChild(back);
      const err = back.querySelector("#pwdErr");
      const cur = back.querySelector("#pwdCur");
      const neu = back.querySelector("#pwdNew");
      const neu2 = back.querySelector("#pwdNew2");
      cur.focus();

      async function submit() {
        err.textContent = "";
        const a = cur.value;
        const b = neu.value;
        const c = neu2.value;
        if (!a || !b) {
          err.textContent = "Fill current and new password";
          return;
        }
        if (b !== c) {
          err.textContent = "New passwords do not match";
          return;
        }
        if (a === b) {
          err.textContent = "New password must differ from current";
          return;
        }
        const okBtn = back.querySelector('[data-a="ok"]');
        okBtn.disabled = true;
        try {
          await DnsApi.changePassword(a, b);
          back.remove();
          toast("Password updated");
          resolve(true);
        } catch (ex) {
          err.textContent = ex.message || "Change failed";
          okBtn.disabled = false;
        }
      }

      back.addEventListener("click", (e) => {
        const a = e.target.getAttribute("data-a");
        if (a === "ok") {
          submit();
          return;
        }
        if (a === "cancel" || e.target === back) {
          back.remove();
          resolve(false);
        }
      });
      back.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          back.remove();
          resolve(false);
        }
        if (e.key === "Enter" && e.target.tagName === "INPUT") {
          e.preventDefault();
          submit();
        }
      });
    });
  }

  function confirmModal({ title, text, dangerLabel = "Delete" }) {
    return new Promise((resolve) => {
      const back = document.createElement("div");
      back.className = "modal-back";
      back.innerHTML = `
        <div class="modal" role="dialog" aria-modal="true">
          <h3>${escapeHtml(title)}</h3>
          <p>${escapeHtml(text)}</p>
          <div class="modal-actions">
            <button type="button" class="btn btn-secondary" data-a="cancel">Cancel</button>
            <button type="button" class="btn btn-danger" data-a="ok">${escapeHtml(dangerLabel)}</button>
          </div>
        </div>`;
      document.body.appendChild(back);
      back.addEventListener("click", (e) => {
        const a = e.target.getAttribute("data-a");
        if (!a && e.target !== back) return;
        if (a === "ok") resolve(true);
        else if (a === "cancel" || e.target === back) resolve(false);
        back.remove();
      });
    });
  }

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }

  function displayName() {
    return (user && (user.displayName || user.username)) || "admin";
  }

  async function ensureAuth() {
    try {
      user = await DnsApi.me();
      try {
        const prefs = await DnsApi.uiPrefs();
        uiPrefs = {
          timezone: prefs.timezone || "Europe/Moscow",
          options: Array.isArray(prefs.options) ? prefs.options : [],
          timezoneLabel: prefs.timezoneLabel || "",
        };
      } catch {
        /* keep default UTC+3 */
      }
      return true;
    } catch {
      user = null;
      return false;
    }
  }

  function kindFromProtocol(proto) {
    const p = String(proto || "Udp").toLowerCase();
    if (p === "https") return "doh";
    if (p === "tls") return "dot";
    return "classic";
  }

  function protocolFromKind(kind) {
    if (kind === "doh") return "Https";
    if (kind === "dot") return "Tls";
    return "Udp";
  }

  function detectFwdKind(addr) {
    const a = String(addr || "").trim().toLowerCase();
    if (a.startsWith("https://") || a.startsWith("http://")) return "doh";
    if (a.startsWith("tls://") || /:853$/.test(a)) return "dot";
    return "classic";
  }

  /** UI form: DoT host without :853/tls://; DoH as https URL. */
  function normalizeFwd(addr, kind) {
    let a = String(addr || "").trim();
    let k = kind || "classic";
    if (k === "doh") {
      if (!/^https?:\/\//i.test(a)) a = "https://" + a;
      try {
        const u = new URL(a);
        if (!u.pathname || u.pathname === "/") {
          a = `${u.protocol}//${u.host}/dns-query`;
        }
      } catch { /* keep as-is; server will validate */ }
    } else if (k === "dot") {
      a = a.replace(/^tls:\/\//i, "").replace(/:853$/i, "");
    } else {
      a = a.replace(/^tls:\/\//i, "");
    }
    return { addr: a, kind: k };
  }

  /** Address string for Technitium settings/set (protocol is separate). */
  function encodeFwdForStore(addr, kind) {
    const n = normalizeFwd(addr, kind);
    if (n.kind === "doh") return n.addr;
    if (n.kind === "dot") return n.addr.replace(/:853$/i, "");
    return n.addr;
  }

  function decodeFwdFromStore(addr, fallbackKind) {
    const raw = String(addr || "").trim();
    const detected = detectFwdKind(raw);
    const kind = detected !== "classic" ? detected : (fallbackKind || "classic");
    return normalizeFwd(raw, kind);
  }

  function renderLogin() {
    root.innerHTML = `
      <div class="login-page">
        <form class="login-card" id="loginForm">
          <div class="brand-mark brand-mark-lg" aria-hidden="true">
            <img src="/img/brand-mascot.png" alt="" />
          </div>
          <h1>DNS Panel</h1>
          <p class="sub">Zones and DNS records</p>
          <div class="form-error" id="loginErr"></div>
          <div class="field">
            <label for="user">Username</label>
            <input id="user" name="user" autocomplete="username" required value="admin" />
          </div>
          <div class="field">
            <label for="pass">Password</label>
            <input id="pass" name="password" type="password" autocomplete="current-password" required />
            <div class="hint">DNS server account (default: admin)</div>
          </div>
          <button class="btn" type="submit" style="width:100%">Sign in</button>
        </form>
      </div>`;
    document.getElementById("loginForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const err = document.getElementById("loginErr");
      err.textContent = "";
      try {
        await DnsApi.login(
          document.getElementById("user").value.trim(),
          document.getElementById("pass").value
        );
        location.hash = "#/dashboard";
        await boot();
      } catch (ex) {
        err.textContent = ex.message || "Sign-in failed";
      }
    });
  }

  function shell(title, toolbarHtml, workHtml, active) {
    root.innerHTML = `
      <div class="app-shell">
        <div class="sidebar-backdrop" id="sidebarBack"></div>
        <aside class="sidebar" id="sidebar">
          <div class="sidebar-brand">
            <div class="brand-mark" aria-hidden="true">
              <img src="/img/brand-mascot.png" alt="" />
            </div>
            <div class="brand-copy">
              <div class="brand-title">DNS Panel</div>
              <div class="brand-sub">DNS management</div>
            </div>
          </div>
          <nav class="sidebar-nav">
            <button type="button" class="nav-item ${active === "dashboard" ? "active" : ""}" data-go="#/dashboard">Dashboard</button>
            <button type="button" class="nav-item ${active === "zones" || active === "records" ? "active" : ""}" data-go="#/zones">Zones</button>
            <button type="button" class="nav-item ${active === "forwarders" ? "active" : ""}" data-go="#/forwarders">Forwarders</button>
            <button type="button" class="nav-item ${active === "protocols" ? "active" : ""}" data-go="#/client-protocol">Client protocol</button>
            <button type="button" class="nav-item ${active === "blocking" ? "active" : ""}" data-go="#/blocking">Blocking</button>
            <button type="button" class="nav-item ${active === "querylog" ? "active" : ""}" data-go="#/query-log">Query log</button>
          </nav>
          <nav class="sidebar-nav-bottom">
            <button type="button" class="nav-item ${active === "settings" ? "active" : ""}" data-go="#/settings">Settings</button>
          </nav>
          <div class="sidebar-foot">Internal</div>
        </aside>
        <div class="main">
          <header class="topbar">
            <div style="display:flex;align-items:center;gap:10px;min-width:0">
              <button type="button" class="hamburger" id="menuBtn" aria-label="Menu">☰</button>
              <h2>${escapeHtml(title)}</h2>
            </div>
            <div class="topbar-user">
              <div class="user-menu" id="userMenu">
                <button type="button" class="user-menu-btn" id="userMenuBtn" aria-haspopup="true" aria-expanded="false">
                  <span class="user-menu-name">${escapeHtml(displayName())}</span>
                  <span class="user-role">admin</span>
                  <span class="user-menu-caret" aria-hidden="true">▾</span>
                </button>
                <div class="user-menu-pop" id="userMenuPop" hidden>
                  <button type="button" class="user-menu-item" id="btnChangePass">Change password</button>
                  <button type="button" class="user-menu-item" id="logoutBtn">Sign out</button>
                </div>
              </div>
            </div>
          </header>
          <div class="toolbar">${toolbarHtml || ""}</div>
          <div class="work">${workHtml}</div>
        </div>
      </div>`;

    root.querySelectorAll("[data-go]").forEach((el) => {
      el.addEventListener("click", () => { location.hash = el.getAttribute("data-go"); });
    });
    const menuBtn = document.getElementById("userMenuBtn");
    const menuPop = document.getElementById("userMenuPop");
    const closeUserMenu = () => {
      menuPop.hidden = true;
      menuBtn.setAttribute("aria-expanded", "false");
    };
    const onDocClick = () => {
      closeUserMenu();
      document.removeEventListener("click", onDocClick);
    };
    menuBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (menuPop.hidden) {
        menuPop.hidden = false;
        menuBtn.setAttribute("aria-expanded", "true");
        setTimeout(() => document.addEventListener("click", onDocClick), 0);
      } else {
        document.removeEventListener("click", onDocClick);
        closeUserMenu();
      }
    });
    menuPop.addEventListener("click", (e) => e.stopPropagation());
    document.getElementById("btnChangePass").addEventListener("click", async () => {
      document.removeEventListener("click", onDocClick);
      closeUserMenu();
      await openChangePasswordModal();
    });
    document.getElementById("logoutBtn").addEventListener("click", async () => {
      document.removeEventListener("click", onDocClick);
      closeUserMenu();
      try { await DnsApi.logout(); } catch { /* ignore */ }
      location.hash = "#/login";
      renderLogin();
    });
    const sidebar = document.getElementById("sidebar");
    const back = document.getElementById("sidebarBack");
    document.getElementById("menuBtn").addEventListener("click", () => {
      sidebar.classList.toggle("open");
      back.classList.toggle("open");
    });
    back.addEventListener("click", () => {
      sidebar.classList.remove("open");
      back.classList.remove("open");
    });
  }

  function sortMark(key, sortState) {
    if (sortState.key !== key) return "";
    return `<span class="sort-mark">${sortState.dir > 0 ? "▲" : "▼"}</span>`;
  }

  function bindSortHeaders(box, sortState, onChange) {
    box.querySelectorAll("th.sortable").forEach((th) => {
      th.addEventListener("click", () => {
        const key = th.getAttribute("data-sort");
        if (sortState.key === key) sortState.dir *= -1;
        else { sortState.key = key; sortState.dir = 1; }
        onChange();
      });
    });
  }

  function normalizeZone(z) {
    return {
      name: z.name || z.zoneName || "",
      type: z.type || "",
      disabled: !!z.disabled,
      records: z.totalRecords ?? z.recordsCount ?? z.recordCount ?? z.records?.length ?? "—",
      serial: z.soaSerial ?? z.serial ?? "—",
    };
  }

  function fmtNum(n) {
    const v = Number(n);
    if (!Number.isFinite(v)) return "—";
    return v.toLocaleString("ru-RU");
  }

  function dateTzOptions() {
    const tz = uiPrefs && uiPrefs.timezone;
    if (!tz || tz === "local") return {};
    return { timeZone: tz };
  }

  function asDate(raw) {
    if (raw instanceof Date) return raw;
    if (raw == null || raw === "") return null;
    const d = new Date(raw);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  /** Display timestamps in Settings timezone (default UTC+3 / Europe/Moscow). */
  function fmtDateTime(raw) {
    const d = asDate(raw);
    if (!d) return "—";
    return d.toLocaleString("ru-RU", {
      ...dateTzOptions(),
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  }

  function fmtChartLabel(raw, labelFormat) {
    const d = asDate(raw);
    if (!d) return String(raw || "");
    const pad = (x) => String(x).padStart(2, "0");
    const parts = new Intl.DateTimeFormat("en-GB", {
      ...dateTzOptions(),
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).formatToParts(d);
    const get = (t) => (parts.find((p) => p.type === t) || {}).value || "00";
    const fmt = labelFormat || "HH:mm";
    if (fmt.includes("dd") || fmt.includes("MM") || fmt.includes("yyyy")) {
      return `${get("day")}.${get("month")} ${get("hour")}:${get("minute")}`;
    }
    return `${get("hour")}:${get("minute")}`;
  }

  function sparklineSvg(values, width, height) {
    const nums = (values || []).map((x) => Number(x) || 0);
    if (!nums.length) {
      return `<svg class="dash-spark" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true"></svg>`;
    }
    const max = Math.max(...nums, 1);
    const min = Math.min(...nums, 0);
    const span = Math.max(max - min, 1);
    const step = nums.length > 1 ? (width - 2) / (nums.length - 1) : 0;
    const pts = nums.map((v, i) => {
      const x = 1 + i * step;
      const y = height - 1 - ((v - min) / span) * (height - 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    return `<svg class="dash-spark" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="Queries over time">
      <polyline fill="none" stroke="currentColor" stroke-width="1.5" points="${pts}" />
    </svg>`;
  }

  function barRows(labels, data, accentClass, fallbackLabels) {
    let pairs = (labels || []).map((lab, i) => ({
      label: lab,
      value: Number((data || [])[i]) || 0,
    }));
    if (!pairs.length && Array.isArray(fallbackLabels) && fallbackLabels.length) {
      pairs = fallbackLabels.map((lab) => ({ label: lab, value: 0 }));
    }
    const max = Math.max(...pairs.map((p) => p.value), 1);
    if (!pairs.length) {
      return `<div class="dash-empty">No queries in this period</div>`;
    }
    return `<div class="dash-bars">${pairs.map((p) => {
      const pct = Math.round((p.value / max) * 100);
      return `<div class="dash-bar-row">
        <div class="dash-bar-label">${escapeHtml(String(p.label))}</div>
        <div class="dash-bar-track"><span class="dash-bar-fill ${accentClass || ""}" style="width:${pct}%"></span></div>
        <div class="dash-bar-val">${fmtNum(p.value)}</div>
      </div>`;
    }).join("")}</div>`;
  }

  function topTable(rows, nameKey) {
    const list = Array.isArray(rows) ? rows : [];
    if (!list.length) {
      return `<div class="dash-empty">No entries in this period</div>`;
    }
    return `<div class="table-scroll dash-top-scroll"><table>
      <thead><tr><th>${escapeHtml(nameKey)}</th><th class="num">Hits</th></tr></thead>
      <tbody>${list.map((r) => {
        const name = r.name || "—";
        const sub = r.domain ? `<div class="cell-note">${escapeHtml(r.domain)}</div>` : "";
        const rl = r.rateLimited ? ` <span class="badge badge-warn">rate</span>` : "";
        return `<tr>
          <td><div class="cell-url">${escapeHtml(name)}</div>${sub}${rl}</td>
          <td class="num">${fmtNum(r.hits)}</td>
        </tr>`;
      }).join("")}</tbody>
    </table></div>`;
  }

  function renderTops(clients, domains, blocked) {
    const blocks = [
      { title: "Top clients", rows: clients, key: "Client" },
      { title: "Top domains", rows: domains, key: "Domain" },
      { title: "Top blocked", rows: blocked, key: "Domain" },
    ].filter((b) => Array.isArray(b.rows) && b.rows.length > 0);
    if (!blocks.length) {
      return `<div class="dash-card dash-card-wide">
        <p class="section-title">Top lists</p>
        <div class="dash-empty">No clients / domains / blocked hits in this period</div>
      </div>`;
    }
    const cols = blocks.length;
    return `<div class="dash-tops dash-card-wide" style="grid-template-columns:repeat(${cols},minmax(0,1fr))">
      ${blocks.map((b) => `<div class="dash-card">
        <p class="section-title">${escapeHtml(b.title)}</p>
        ${topTable(b.rows, b.key)}
      </div>`).join("")}
    </div>`;
  }

  function fmtBytes(n) {
    const v = Number(n);
    if (!Number.isFinite(v) || v < 0) return "—";
    if (v < 1024) return `${Math.round(v)} B`;
    const u = ["KB", "MB", "GB", "TB"];
    let x = v / 1024;
    let i = 0;
    while (x >= 1024 && i < u.length - 1) { x /= 1024; i += 1; }
    return `${x >= 10 ? x.toFixed(0) : x.toFixed(1)} ${u[i]}`;
  }

  function resourceCard(res) {
    const r = res || {};
    const cpu = r.cpuPercent != null ? `${fmtNum(r.cpuPercent)}%` : "—";
    const memPct = r.memPercent != null ? `${fmtNum(r.memPercent)}%` : "—";
    const memLine = (r.memUsedBytes != null && r.memTotalBytes != null)
      ? `${fmtBytes(r.memUsedBytes)} / ${fmtBytes(r.memTotalBytes)}`
      : "—";
    const load = [r.load1, r.load5, r.load15]
      .map((x) => (x == null ? "—" : Number(x).toFixed(2)))
      .join(" · ");
    const cpuBar = r.cpuPercent != null ? Math.max(0, Math.min(100, Number(r.cpuPercent))) : 0;
    const memBar = r.memPercent != null ? Math.max(0, Math.min(100, Number(r.memPercent))) : 0;
    return `
      <div class="dash-res">
        <div class="dash-bar-row">
          <div class="dash-bar-label">CPU</div>
          <div class="dash-bar-track"><span class="dash-bar-fill" style="width:${cpuBar}%"></span></div>
          <div class="dash-bar-val">${escapeHtml(cpu)}</div>
        </div>
        <div class="dash-bar-row">
          <div class="dash-bar-label">RAM</div>
          <div class="dash-bar-track"><span class="dash-bar-fill" style="width:${memBar}%"></span></div>
          <div class="dash-bar-val">${escapeHtml(memPct)}</div>
        </div>
        <div class="dash-mini-stats">
          <div><span>RAM detail</span><strong>${escapeHtml(memLine)}</strong></div>
          <div><span>Load 1 · 5 · 15</span><strong>${escapeHtml(load)}</strong></div>
        </div>
      </div>`;
  }

  function servicesCard(list) {
    const rows = Array.isArray(list) ? list : [];
    if (!rows.length) return `<div class="empty">No data</div>`;
    return `<div class="dash-services">${rows.map((s) => {
      const ok = !!s.ok;
      return `<div class="dash-svc ${ok ? "is-up" : "is-down"}">
        <span class="dash-svc-dot" aria-hidden="true"></span>
        <span class="dash-svc-name">${escapeHtml(s.name || s.id || "—")}</span>
        <span class="dash-svc-state">${ok ? "up" : "down"}</span>
      </div>`;
    }).join("")}</div>`;
  }

  async function viewDashboard(initialType) {
    const allowed = ["LastHour", "LastDay", "LastWeek", "LastMonth", "LastYear"];
    let period = allowed.includes(initialType) ? initialType : "LastHour";

    shell("Dashboard", `
      <label class="dash-period-label" for="dashPeriod">Period</label>
      <select id="dashPeriod" class="dash-period">
        <option value="LastHour">Last hour</option>
        <option value="LastDay">Last day</option>
        <option value="LastWeek">Last week</option>
        <option value="LastMonth">Last month</option>
        <option value="LastYear">Last year</option>
      </select>
      <div class="toolbar-spacer"></div>
      <button type="button" class="btn btn-secondary" id="btnDashRefresh">Refresh</button>
    `, `<div class="form-panel dash-panel" id="dashBox"><div class="empty">Loading…</div></div>`, "dashboard");

    const sel = document.getElementById("dashPeriod");
    sel.value = period;

    async function load() {
      const box = document.getElementById("dashBox");
      box.innerHTML = `<div class="empty">Loading…</div>`;
      try {
        const data = await DnsApi.dashboard(period);
        const st = data.stats || {};
        const hy = data.hybrid || {};
        const chart = data.mainChart || {};
        const totalSeries = (chart.series && (chart.series.Total || chart.series.total)) || [];
        const labels = (chart.labels || []).map((l) => fmtChartLabel(l, chart.labelFormat));
        const uptime = data.metrics && data.metrics.uptimeSeconds != null
          ? (() => {
              const s = Number(data.metrics.uptimeSeconds) || 0;
              const d = Math.floor(s / 86400);
              const h = Math.floor((s % 86400) / 3600);
              const m = Math.floor((s % 3600) / 60);
              return d > 0 ? `${d}d ${h}h` : `${h}h ${m}m`;
            })()
          : null;

        box.innerHTML = `
          <div class="dash-status">
            <span class="dash-pill ${hy.enableBlocking ? "is-on" : "is-off"}">Blocking ${hy.enableBlocking ? "on" : "off"}</span>
            <span class="dash-pill">Forwarders ${fmtNum(hy.forwarderCount)}</span>
            <span class="dash-pill ${hy.enableDnsOverTls ? "is-on" : ""}">DoT ${hy.enableDnsOverTls ? "on" : "off"}${hy.dnsOverTlsPort ? " :" + hy.dnsOverTlsPort : ""}</span>
            <span class="dash-pill ${hy.enableDnsOverHttps ? "is-on" : ""}">DoH ${hy.enableDnsOverHttps ? "on" : "off"}${hy.dnsOverHttpsPort ? " :" + hy.dnsOverHttpsPort : ""}</span>
            ${uptime != null ? `<span class="dash-pill muted">Uptime ${escapeHtml(uptime)}</span>` : ""}
          </div>

          <div class="dash-kpis">
            <div class="dash-kpi"><div class="dash-kpi-label">Queries</div><div class="dash-kpi-val">${fmtNum(st.totalQueries)}</div></div>
            <div class="dash-kpi"><div class="dash-kpi-label">Cached</div><div class="dash-kpi-val">${fmtNum(st.totalCached)}</div></div>
            <div class="dash-kpi"><div class="dash-kpi-label">Blocked</div><div class="dash-kpi-val">${fmtNum(st.totalBlocked)}</div></div>
            <div class="dash-kpi"><div class="dash-kpi-label">Clients</div><div class="dash-kpi-val">${fmtNum(st.totalClients)}</div></div>
            <div class="dash-kpi"><div class="dash-kpi-label">Zones</div><div class="dash-kpi-val">${fmtNum(st.zones)}</div></div>
            <div class="dash-kpi"><div class="dash-kpi-label">Cache entries</div><div class="dash-kpi-val">${fmtNum(st.cachedEntries)}</div></div>
          </div>

          <div class="dash-grid">
            <div class="dash-card dash-card-wide">
              <p class="section-title">Queries over time</p>
              <div class="dash-spark-wrap">${sparklineSvg(totalSeries, 640, 120)}</div>
              <div class="dash-spark-meta">
                <span>${labels.length ? escapeHtml(labels[0]) : "—"}</span>
                <span>${labels.length ? escapeHtml(labels[labels.length - 1]) : "—"}</span>
              </div>
            </div>

            <div class="dash-card">
              <p class="section-title">Result codes</p>
              ${barRows(
                ["No Error", "NXDOMAIN", "Server Failure", "Refused", "Dropped"],
                [st.totalNoError, st.totalNxDomain, st.totalServerFailure, st.totalRefused, st.totalDropped],
                "accent"
              )}
            </div>
            <div class="dash-card">
              <p class="section-title">Lists</p>
              <div class="dash-mini-stats">
                <div><span>Block list zones</span><strong>${fmtNum(st.blockListZones)}</strong></div>
                <div><span>Blocked zones (manual)</span><strong>${fmtNum(st.blockedZones)}</strong></div>
                <div><span>Allowed zones</span><strong>${fmtNum(st.allowedZones)}</strong></div>
                <div><span>Allow list zones</span><strong>${fmtNum(st.allowListZones)}</strong></div>
              </div>
            </div>
            <div class="dash-card">
              <p class="section-title">CPU / RAM</p>
              ${resourceCard(data.resources)}
            </div>

            <div class="dash-card dash-card-wide">
              <p class="section-title">Services</p>
              ${servicesCard(data.services)}
            </div>

            ${renderTops(data.topClients, data.topDomains, data.topBlockedDomains)}
          </div>
        `;
      } catch (ex) {
        box.innerHTML = `<div class="empty"><strong>Failed to load</strong><br>${escapeHtml(ex.message || "error")}</div>`;
      }
    }

    sel.addEventListener("change", () => {
      period = sel.value;
      location.hash = "#/dashboard/" + period;
    });
    document.getElementById("btnDashRefresh").addEventListener("click", load);
    await load();
  }

  async function viewZones() {
    shell("Zones", `
      <input type="search" class="filter-input" id="zoneFilter" placeholder="Filter by name…" />
      <div class="toolbar-spacer"></div>
      <button type="button" class="btn btn-secondary" id="btnRefresh">Refresh</button>
      <button type="button" class="btn" id="btnAddZone">Create zone</button>
    `, `<div class="table-wrap"><div class="table-scroll" id="zonesBox"><div class="empty">Loading…</div></div></div>`, "zones");

    function renderTable() {
      const box = document.getElementById("zonesBox");
      const q = (document.getElementById("zoneFilter")?.value || "").trim().toLowerCase();
      let rows = zonesCache.slice();
      if (q) rows = rows.filter((z) => z.name.toLowerCase().includes(q) || z.type.toLowerCase().includes(q));
      rows.sort((a, b) => {
        const ka = String(a[zonesSort.key] ?? "").toLowerCase();
        const kb = String(b[zonesSort.key] ?? "").toLowerCase();
        if (ka < kb) return -1 * zonesSort.dir;
        if (ka > kb) return 1 * zonesSort.dir;
        return 0;
      });
      if (!rows.length) {
        box.innerHTML = `<div class="empty"><strong>No data</strong><span>${
          zonesCache.length ? "Nothing matches the filter." : "No zones yet. Create a Primary, Stub, or Conditional Forwarder."
        }</span></div>`;
        return;
      }
      box.innerHTML = `<table class="data">
        <thead><tr>
          <th class="sortable" data-sort="name">Name${sortMark("name", zonesSort)}</th>
          <th class="sortable" data-sort="type">Type${sortMark("type", zonesSort)}</th>
          <th class="sortable" data-sort="records">Records${sortMark("records", zonesSort)}</th>
          <th class="sortable" data-sort="serial">SOA serial${sortMark("serial", zonesSort)}</th>
          <th></th>
        </tr></thead>
        <tbody>${rows.map((z) => `
          <tr>
            <td><a href="#/zones/${encodeURIComponent(z.name)}">${escapeHtml(z.name)}</a></td>
            <td><span class="badge">${escapeHtml(z.type)}</span>${z.disabled ? ' <span class="badge badge-muted">off</span>' : ""}</td>
            <td>${escapeHtml(z.records)}</td>
            <td>${escapeHtml(z.serial)}</td>
            <td class="actions"><button type="button" class="btn btn-danger btn-sm" data-del="${escapeHtml(z.name)}">Delete</button></td>
          </tr>`).join("")}</tbody></table>`;
      bindSortHeaders(box, zonesSort, renderTable);
      box.querySelectorAll("[data-del]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const zn = btn.getAttribute("data-del");
          const ok = await confirmModal({
            title: "Delete zone?",
            text: `Zone “${zn}” will be permanently deleted.`,
          });
          if (!ok) return;
          try {
            await DnsApi.deleteZone(zn);
            toast("Zone deleted");
            load();
          } catch (ex) { toast(ex.message, "error"); }
        });
      });
    }

    async function load() {
      const box = document.getElementById("zonesBox");
      box.innerHTML = `<div class="empty">Loading…</div>`;
      try {
        const data = await DnsApi.zones("?page=1&per_page=200");
        zonesCache = (data.zones || data.response?.zones || []).map(normalizeZone);
        renderTable();
      } catch (ex) {
        box.innerHTML = `<div class="empty"><strong>Error</strong><span>${escapeHtml(ex.message)}</span></div>`;
      }
    }

    document.getElementById("zoneFilter").addEventListener("input", renderTable);
    document.getElementById("btnRefresh").addEventListener("click", load);
    document.getElementById("btnAddZone").addEventListener("click", () => openCreateZone(load));
    await load();
  }

  function openCreateZone(onDone) {
    const back = document.createElement("div");
    back.className = "modal-back";
    back.innerHTML = `
      <div class="modal">
        <h3>Create zone</h3>
        <div class="field"><label>Zone name</label><input id="zName" placeholder="example.local" /></div>
        <div class="field"><label>Type</label>
          <select id="zType">
            <option value="Primary">Primary</option>
            <option value="Secondary">Secondary</option>
            <option value="Stub">Stub</option>
            <option value="Forwarder">Conditional Forwarder</option>
          </select>
        </div>
        <div class="field" id="zNsWrap" style="display:none">
          <label>Primary NS</label>
          <input id="zNs" placeholder="ns1.example.com" />
          <div class="hint">Comma-separated — for Secondary and Stub</div>
        </div>
        <div class="field" id="zFwdWrap" style="display:none">
          <label>Forwarder</label>
          <input id="zFwd" placeholder="1.1.1.1" />
          <label style="margin-top:8px">Protocol</label>
          <select id="zProto">
            <option value="Udp">UDP — classic DNS</option>
            <option value="Tcp">TCP</option>
            <option value="Tls">TLS — DoT</option>
            <option value="Https">HTTPS — DoH</option>
          </select>
        </div>
        <div class="form-error" id="zErr"></div>
        <div class="modal-actions">
          <button type="button" class="btn btn-secondary" data-a="cancel">Cancel</button>
          <button type="button" class="btn" data-a="ok">Create</button>
        </div>
      </div>`;
    document.body.appendChild(back);
    const typeEl = back.querySelector("#zType");
    const sync = () => {
      const t = typeEl.value;
      back.querySelector("#zNsWrap").style.display = (t === "Secondary" || t === "Stub") ? "" : "none";
      back.querySelector("#zFwdWrap").style.display = t === "Forwarder" ? "" : "none";
    };
    typeEl.addEventListener("change", sync);
    sync();
    back.addEventListener("click", async (e) => {
      const a = e.target.getAttribute("data-a");
      if (a === "cancel" || e.target === back) { back.remove(); return; }
      if (a !== "ok") return;
      const body = { zone: back.querySelector("#zName").value.trim(), type: typeEl.value };
      if (!body.zone) { back.querySelector("#zErr").textContent = "Enter a zone name"; return; }
      if (body.type === "Secondary" || body.type === "Stub") {
        body.primaryNameServerAddresses = back.querySelector("#zNs").value.trim() || undefined;
      }
      if (body.type === "Forwarder") {
        body.forwarder = back.querySelector("#zFwd").value.trim();
        body.protocol = back.querySelector("#zProto").value;
        body.initializeForwarder = true;
      }
      try {
        await DnsApi.createZone(body);
        toast("Zone created");
        back.remove();
        onDone();
      } catch (ex) {
        back.querySelector("#zErr").textContent = ex.message;
      }
    });
  }

  function formatRecordValue(r) {
    const rd = r.rData || r.data || r;
    if (typeof rd === "string") return rd;
    if (rd.ipAddress) return rd.ipAddress;
    if (rd.cname) return rd.cname;
    if (rd.nameServer) return rd.nameServer;
    if (rd.exchange) return `${rd.preference ?? ""} ${rd.exchange}`.trim();
    if (rd.text) return rd.text;
    if (rd.target) return `${rd.priority ?? ""} ${rd.weight ?? ""} ${rd.port ?? ""} ${rd.target}`.trim();
    if (rd.forwarder) return `${rd.protocol || ""} ${rd.forwarder}`.trim();
    try { return JSON.stringify(rd); } catch { return String(rd); }
  }

  function extractDeleteValue(r) {
    const rd = r.rData || r.data || {};
    return rd.ipAddress || rd.cname || rd.nameServer || rd.exchange || rd.text || rd.target || rd.forwarder || r.value || "";
  }

  async function viewRecords(zone) {
    shell(`Records · ${zone}`, `
      <button type="button" class="btn btn-secondary" data-go="#/zones">← Zones</button>
      <input type="search" class="filter-input" id="recFilter" placeholder="Filter…" />
      <div class="toolbar-spacer"></div>
      <button type="button" class="btn btn-secondary" id="btnRefresh">Refresh</button>
      <button type="button" class="btn" id="btnAddRec">Add record</button>
    `, `<div class="table-wrap"><div class="table-scroll" id="recBox"><div class="empty">Loading…</div></div></div>`, "records");
    root.querySelector("[data-go]").addEventListener("click", () => { location.hash = "#/zones"; });

    function renderTable() {
      const box = document.getElementById("recBox");
      const q = (document.getElementById("recFilter")?.value || "").trim().toLowerCase();
      let rows = recordsCache.slice();
      if (q) {
        rows = rows.filter((r) =>
          r.name.toLowerCase().includes(q) ||
          r.type.toLowerCase().includes(q) ||
          r.value.toLowerCase().includes(q)
        );
      }
      rows.sort((a, b) => {
        const ka = String(a[recordsSort.key] ?? "").toLowerCase();
        const kb = String(b[recordsSort.key] ?? "").toLowerCase();
        if (ka < kb) return -1 * recordsSort.dir;
        if (ka > kb) return 1 * recordsSort.dir;
        return 0;
      });
      if (!rows.length) {
        box.innerHTML = `<div class="empty"><strong>No data</strong><span>${
          recordsCache.length ? "Nothing matches the filter." : "No records in this zone."
        }</span></div>`;
        return;
      }
      box.innerHTML = `<table class="data">
        <thead><tr>
          <th class="sortable" data-sort="name">Name${sortMark("name", recordsSort)}</th>
          <th class="sortable" data-sort="type">Type${sortMark("type", recordsSort)}</th>
          <th class="sortable" data-sort="ttl">TTL${sortMark("ttl", recordsSort)}</th>
          <th class="sortable" data-sort="value">Data${sortMark("value", recordsSort)}</th>
          <th></th>
        </tr></thead>
        <tbody>${rows.map((r) => {
          const payload = encodeURIComponent(JSON.stringify({
            domain: r.name, type: r.type, value: r.deleteValue,
          }));
          return `<tr>
            <td>${escapeHtml(r.name)}</td>
            <td><span class="badge">${escapeHtml(r.type)}</span></td>
            <td>${escapeHtml(r.ttl)}</td>
            <td>${escapeHtml(r.value)}</td>
            <td class="actions"><button type="button" class="btn btn-danger btn-sm" data-del="${payload}">Delete</button></td>
          </tr>`;
        }).join("")}</tbody></table>`;
      bindSortHeaders(box, recordsSort, renderTable);
      box.querySelectorAll("[data-del]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const body = JSON.parse(decodeURIComponent(btn.getAttribute("data-del")));
          const ok = await confirmModal({
            title: "Delete record?",
            text: `${body.type} ${body.domain}`,
          });
          if (!ok) return;
          try {
            await DnsApi.deleteRecord(zone, body);
            toast("Record deleted");
            load();
          } catch (ex) { toast(ex.message, "error"); }
        });
      });
    }

    async function load() {
      const box = document.getElementById("recBox");
      box.innerHTML = `<div class="empty">Loading…</div>`;
      try {
        const data = await DnsApi.records(zone);
        const records = data.response?.records || data.records || [];
        recordsCache = records.map((r) => ({
          name: r.name || r.domain || "",
          type: r.type || "",
          ttl: r.ttl ?? "",
          value: formatRecordValue(r),
          deleteValue: extractDeleteValue(r),
        }));
        renderTable();
      } catch (ex) {
        box.innerHTML = `<div class="empty"><strong>Error</strong><span>${escapeHtml(ex.message)}</span></div>`;
      }
    }

    document.getElementById("recFilter").addEventListener("input", renderTable);
    document.getElementById("btnRefresh").addEventListener("click", load);
    document.getElementById("btnAddRec").addEventListener("click", () => openAddRecord(zone, load));
    await load();
  }

  function openAddRecord(zone, onDone) {
    const back = document.createElement("div");
    back.className = "modal-back";
    back.innerHTML = `
      <div class="modal">
        <h3>Add record</h3>
        <div class="field"><label>Name</label><input id="rDomain" value="${escapeHtml(zone)}" /></div>
        <div class="field"><label>Type</label>
          <select id="rType">
            <option>A</option><option>AAAA</option><option>CNAME</option>
            <option>MX</option><option>TXT</option><option>NS</option>
            <option>SRV</option><option>PTR</option>
          </select>
        </div>
        <div class="field"><label>Value</label><input id="rValue" placeholder="192.168.0.10" />
          <div class="hint">MX: “10 mail.example.local”. SRV: “prio weight port target”</div>
        </div>
        <div class="field"><label>TTL</label><input id="rTtl" type="number" value="3600" /></div>
        <div class="form-error" id="rErr"></div>
        <div class="modal-actions">
          <button type="button" class="btn btn-secondary" data-a="cancel">Cancel</button>
          <button type="button" class="btn" data-a="ok">Add</button>
        </div>
      </div>`;
    document.body.appendChild(back);
    back.addEventListener("click", async (e) => {
      const a = e.target.getAttribute("data-a");
      if (a === "cancel" || e.target === back) { back.remove(); return; }
      if (a !== "ok") return;
      const type = back.querySelector("#rType").value;
      const domain = back.querySelector("#rDomain").value.trim();
      const value = back.querySelector("#rValue").value.trim();
      const ttl = Number(back.querySelector("#rTtl").value) || 3600;
      const body = { domain, type, ttl };
      if (type === "A" || type === "AAAA") body.value = value;
      else if (type === "CNAME") body.cname = value;
      else if (type === "NS") body.nameServer = value;
      else if (type === "TXT") body.text = value;
      else if (type === "PTR") body.ptrName = value;
      else if (type === "MX") {
        const parts = value.split(/\s+/);
        body.preference = Number(parts[0]) || 10;
        body.exchange = parts.slice(1).join(" ") || parts[0];
      } else if (type === "SRV") {
        const parts = value.split(/\s+/);
        body.priority = Number(parts[0]) || 0;
        body.weight = Number(parts[1]) || 0;
        body.port = Number(parts[2]) || 0;
        body.target = parts[3] || "";
      } else body.value = value;
      try {
        await DnsApi.addRecord(zone, body);
        toast("Record added");
        back.remove();
        onDone();
      } catch (ex) {
        back.querySelector("#rErr").textContent = ex.message;
      }
    });
  }

  async function viewForwarders() {
    shell("Forwarders", `
      <div class="toolbar-spacer"></div>
      <button type="button" class="btn btn-secondary" id="btnAddFwd">Add forwarder</button>
      <button type="button" class="btn" id="btnSave">Save</button>
    `, `
      <div class="form-panel">
        <div class="form-card">
          <p class="section-title">Upstream forwarders</p>
          <p class="card-hint">Failover order = row order. First reachable wins; next only if previous fails.</p>
          <div class="proto-list" id="fwdList"></div>
        </div>
      </div>
    `, "forwarders");

    function moveFwd(from, to) {
      if (from === to || from < 0 || to < 0) return;
      if (from >= forwardersList.length || to >= forwardersList.length) return;
      syncFwdFromDom(false);
      const [item] = forwardersList.splice(from, 1);
      forwardersList.splice(to, 0, item);
      renderFwdList();
    }

    function renderFwdList() {
      const box = document.getElementById("fwdList");
      const rows = forwardersList.map((item, i) => `
        <div class="proto-row fwd-row" data-i="${i}">
          <button type="button" class="fwd-grip" draggable="true" data-grip="${i}" title="Drag to reorder" aria-label="Drag to reorder">⋮⋮</button>
          <div class="proto-main fwd-main">
            <label>Address</label>
            <input type="text" class="fwd-addr" value="${escapeHtml(item.addr)}" placeholder="1.1.1.1 or https://…/dns-query" />
          </div>
          <div class="proto-port fwd-kind">
            <label>Type</label>
            <select class="fwd-type">
              <option value="classic" ${item.kind === "classic" ? "selected" : ""}>Classic DNS</option>
              <option value="dot" ${item.kind === "dot" ? "selected" : ""}>DoT</option>
              <option value="doh" ${item.kind === "doh" ? "selected" : ""}>DoH</option>
            </select>
          </div>
          <div class="fwd-actions">
            <button type="button" class="btn btn-secondary btn-sm" data-up="${i}" ${i === 0 ? "disabled" : ""} title="Move up">↑</button>
            <button type="button" class="btn btn-secondary btn-sm" data-down="${i}" ${i >= forwardersList.length - 1 ? "disabled" : ""} title="Move down">↓</button>
            <button type="button" class="btn btn-danger btn-sm" data-rm="${i}">Remove</button>
          </div>
          <div class="fwd-status" data-st="${i}"></div>
        </div>`).join("");

      box.innerHTML = `
        ${rows || `<div class="empty proto-empty"><strong>No forwarders</strong><span>Recursive mode until you add upstreams.</span></div>`}
        <div class="proto-row">
          <div class="proto-main">
            <div class="hint">Failover: list order (1 → 2 → 3). Drag ⋮⋮ or use ↑↓. Next only if previous fails.</div>
          </div>
          <div class="proto-port proto-port-empty" aria-hidden="true"></div>
        </div>`;

      box.querySelectorAll("[data-rm]").forEach((btn) => {
        btn.addEventListener("click", () => {
          syncFwdFromDom(false);
          forwardersList.splice(Number(btn.getAttribute("data-rm")), 1);
          renderFwdList();
        });
      });
      box.querySelectorAll("[data-up]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const i = Number(btn.getAttribute("data-up"));
          moveFwd(i, i - 1);
        });
      });
      box.querySelectorAll("[data-down]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const i = Number(btn.getAttribute("data-down"));
          moveFwd(i, i + 1);
        });
      });
      box.querySelectorAll(".fwd-type").forEach((sel) => {
        sel.addEventListener("change", () => {
          const row = sel.closest(".fwd-row");
          const i = Number(row.getAttribute("data-i"));
          if (forwardersList[i]) forwardersList[i].kind = sel.value;
        });
      });

      let dragFrom = null;
      box.querySelectorAll(".fwd-grip").forEach((grip) => {
        grip.addEventListener("dragstart", (ev) => {
          dragFrom = Number(grip.getAttribute("data-grip"));
          ev.dataTransfer.effectAllowed = "move";
          ev.dataTransfer.setData("text/plain", String(dragFrom));
          const row = grip.closest(".fwd-row");
          if (row) row.classList.add("is-dragging");
          // ghost from whole row
          if (row && ev.dataTransfer.setDragImage) {
            ev.dataTransfer.setDragImage(row, 24, 16);
          }
        });
        grip.addEventListener("dragend", () => {
          dragFrom = null;
          box.querySelectorAll(".fwd-row").forEach((r) => {
            r.classList.remove("is-dragging", "is-drag-over");
          });
        });
      });
      box.querySelectorAll(".fwd-row").forEach((row) => {
        row.addEventListener("dragover", (ev) => {
          ev.preventDefault();
          ev.dataTransfer.dropEffect = "move";
          box.querySelectorAll(".fwd-row").forEach((r) => r.classList.remove("is-drag-over"));
          row.classList.add("is-drag-over");
        });
        row.addEventListener("dragleave", () => {
          row.classList.remove("is-drag-over");
        });
        row.addEventListener("drop", (ev) => {
          ev.preventDefault();
          const from = dragFrom != null ? dragFrom : Number(ev.dataTransfer.getData("text/plain"));
          const to = Number(row.getAttribute("data-i"));
          row.classList.remove("is-drag-over");
          moveFwd(from, to);
        });
      });
    }

    function syncFwdFromDom(dropEmpty) {
      const rows = [...document.querySelectorAll(".fwd-row")];
      const mapped = rows.map((row) => ({
        addr: row.querySelector(".fwd-addr").value.trim(),
        kind: row.querySelector(".fwd-type").value,
      }));
      forwardersList = dropEmpty ? mapped.filter((x) => x.addr) : mapped;
    }

    function setRowStatus(i, ok, message) {
      const row = document.querySelector(`.fwd-row[data-i="${i}"]`);
      const st = document.querySelector(`[data-st="${i}"]`);
      const input = row?.querySelector(".fwd-addr");
      if (input) input.classList.toggle("is-invalid", ok === false);
      if (!st) return;
      st.textContent = message || "";
      st.classList.toggle("is-ok", ok === true);
      st.classList.toggle("is-err", ok === false);
    }

    try {
      const data = await DnsApi.forwarders();
      forwardersList = (data.items || []).map((x) => ({
        addr: String(x.addr || ""),
        kind: x.kind === "dot" || x.kind === "doh" ? x.kind : "classic",
      }));
      renderFwdList();
    } catch (ex) {
      toast(ex.message, "error");
      renderFwdList();
    }

    document.getElementById("btnAddFwd").addEventListener("click", () => {
      syncFwdFromDom(false);
      forwardersList.push({ addr: "", kind: "classic" });
      renderFwdList();
    });

    document.getElementById("btnSave").addEventListener("click", async () => {
      syncFwdFromDom(false);
      const btn = document.getElementById("btnSave");

      forwardersList = forwardersList.map((x) => normalizeFwd(x.addr, x.kind));
      renderFwdList();

      const items = forwardersList.map((x, i) => ({ ...x, i }));
      items.forEach((x) => setRowStatus(x.i, null, ""));

      const empty = items.filter((x) => !x.addr);
      if (empty.length) {
        empty.forEach((x) => setRowStatus(x.i, false, "Address is required"));
        toast("Fill all forwarder addresses", "error");
        return;
      }

      btn.disabled = true;
      btn.textContent = "Testing…";
      try {
        if (items.length) {
          const test = await DnsApi.testForwarders(items.map(({ addr, kind }) => ({ addr, kind })));
          (test.results || []).forEach((r, idx) => {
            const row = document.querySelector(`.fwd-row[data-i="${idx}"] .fwd-addr`);
            if (row && r.addr) row.value = r.addr;
            if (forwardersList[idx] && r.addr) {
              forwardersList[idx] = normalizeFwd(r.addr, r.kind || forwardersList[idx].kind);
            }
            setRowStatus(idx, !!r.ok, r.message || (r.ok ? "OK" : "Failed"));
          });
          if (!test.ok) {
            toast("Fix invalid or unreachable forwarders", "error");
            return;
          }
        }
        await DnsApi.saveForwarders(forwardersList.map((x) => ({ addr: x.addr, kind: x.kind })));
        toast("Forwarders saved (Blocky · sequential)");
      } catch (ex) {
        toast(ex.message, "error");
      } finally {
        btn.disabled = false;
        btn.textContent = "Save";
      }
    });
  }

  async function viewProtocols() {
    shell("Client protocol", `
      <div class="toolbar-spacer"></div>
      <button type="button" class="btn" id="btnSave">Save</button>
    `, `
      <div class="form-panel">
        <div class="form-card">
          <p class="section-title">Client protocol</p>
          <div class="proto-list">
            <div class="proto-row">
              <div class="proto-main">
                <label class="inline"><input type="checkbox" id="plainDns" checked disabled /> Classic DNS (UDP/TCP)</label>
                <div class="hint">Always available to clients.</div>
              </div>
              <div class="proto-port">
                <label for="dnsPort">Port</label>
                <input id="dnsPort" type="number" inputmode="numeric" value="53" />
              </div>
            </div>
            <div class="proto-row">
              <div class="proto-main">
                <label class="inline"><input type="checkbox" id="dot" /> DNS-over-TLS</label>
                <div class="hint">Uses the same TLS certificate as direct DoH</div>
              </div>
              <div class="proto-port">
                <label for="dotPort">Port</label>
                <input id="dotPort" type="number" inputmode="numeric" value="853" />
              </div>
            </div>
            <div class="proto-row">
              <div class="proto-main">
                <label class="inline"><input type="checkbox" id="dohHttp" /> DNS-over-HTTP (behind reverse proxy)</label>
                <div class="hint">Via panel proxy: http(s)://HOST:&lt;UI-port&gt;/dns-query</div>
              </div>
              <div class="proto-port">
                <label for="httpPort">Port</label>
                <input id="httpPort" type="number" inputmode="numeric" value="8053" />
              </div>
            </div>
            <div class="proto-row proto-row-cert">
              <div class="proto-main">
                <label class="inline"><input type="checkbox" id="doh" /> DNS-over-HTTPS (direct)</label>
                <div class="hint">TLS certificate required for DoT / direct DoH / DoQ — .pfx or PEM key + chain</div>
              </div>
              <div class="proto-port">
                <label for="httpsPort">Port</label>
                <input id="httpsPort" type="number" inputmode="numeric" value="443" />
              </div>
              <div class="cert-box">
                <div class="cert-status" id="certStatus">Certificate: not set</div>
                <div class="cert-block">
                  <div class="cert-block-title">PKCS#12 (.pfx)</div>
                  <div class="cert-controls">
                    <label class="file-btn btn btn-secondary btn-sm">
                      Choose .pfx
                      <input type="file" id="certFile" accept=".pfx,.p12,application/x-pkcs12" hidden />
                    </label>
                    <span class="file-name" id="certFileName">no file selected</span>
                    <input type="password" id="certPass" class="cert-pass" placeholder=".pfx password (if any)" autocomplete="new-password" />
                    <button type="button" class="btn btn-sm" id="btnUploadCert">Upload .pfx</button>
                  </div>
                </div>
                <div class="cert-block">
                  <div class="cert-block-title">PEM key + certificate (chain)</div>
                  <div class="cert-controls">
                    <label class="file-btn btn btn-secondary btn-sm">
                      Choose key
                      <input type="file" id="pemKeyFile" accept=".key,.pem,.txt,application/x-pem-file" hidden />
                    </label>
                    <span class="file-name" id="pemKeyName">no key</span>
                    <label class="file-btn btn btn-secondary btn-sm">
                      Choose chain
                      <input type="file" id="pemChainFile" accept=".crt,.cer,.pem,.txt,application/x-pem-file,application/x-x509-ca-cert" hidden />
                    </label>
                    <span class="file-name" id="pemChainName">no chain</span>
                    <input type="password" id="pemKeyPass" class="cert-pass" placeholder="key password (if encrypted)" autocomplete="new-password" />
                    <button type="button" class="btn btn-sm" id="btnUploadPem">Upload PEM</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    `, "protocols");

    function parseDnsPort(endpoints) {
      if (!endpoints) return 53;
      const list = Array.isArray(endpoints) ? endpoints : String(endpoints).split(",");
      for (const ep of list) {
        const m = String(ep).trim().match(/:(\d+)\s*$/);
        if (m) return Number(m[1]) || 53;
      }
      return 53;
    }

    try {
      const data = await DnsApi.settings();
      const s = data.response || data;
      document.getElementById("dohHttp").checked = !!s.enableDnsOverHttp;
      document.getElementById("dot").checked = !!s.enableDnsOverTls;
      document.getElementById("doh").checked = !!s.enableDnsOverHttps;
      if (s.dnsOverTlsPort) document.getElementById("dotPort").value = s.dnsOverTlsPort;
      if (s.dnsOverHttpPort) document.getElementById("httpPort").value = s.dnsOverHttpPort;
      if (s.dnsOverHttpsPort) document.getElementById("httpsPort").value = s.dnsOverHttpsPort;
      document.getElementById("dnsPort").value = parseDnsPort(s.dnsServerLocalEndPoints);
      const certEl = document.getElementById("certStatus");
      if (s.dnsTlsCertificatePath) {
        certEl.textContent = "Certificate: set";
        certEl.classList.add("is-set");
      } else {
        certEl.textContent = "Certificate: not set";
        certEl.classList.remove("is-set");
      }
    } catch (ex) {
      toast(ex.message, "error");
    }

    const fileInput = document.getElementById("certFile");
    const fileName = document.getElementById("certFileName");
    fileInput.addEventListener("change", () => {
      const f = fileInput.files && fileInput.files[0];
      fileName.textContent = f ? f.name : "no file selected";
    });
    document.getElementById("btnUploadCert").addEventListener("click", async () => {
      const f = fileInput.files && fileInput.files[0];
      if (!f) { toast("Choose a .pfx file", "error"); return; }
      try {
        await DnsApi.uploadDnsTlsCert(f, document.getElementById("certPass").value);
        toast("Certificate uploaded (.pfx)");
        document.getElementById("certStatus").textContent = "Certificate: set";
        document.getElementById("certStatus").classList.add("is-set");
        fileInput.value = "";
        fileName.textContent = "no file selected";
        document.getElementById("certPass").value = "";
      } catch (ex) { toast(ex.message, "error"); }
    });

    const pemKey = document.getElementById("pemKeyFile");
    const pemChain = document.getElementById("pemChainFile");
    const pemKeyName = document.getElementById("pemKeyName");
    const pemChainName = document.getElementById("pemChainName");
    pemKey.addEventListener("change", () => {
      const f = pemKey.files && pemKey.files[0];
      pemKeyName.textContent = f ? f.name : "no key";
    });
    pemChain.addEventListener("change", () => {
      const f = pemChain.files && pemChain.files[0];
      pemChainName.textContent = f ? f.name : "no chain";
    });
    document.getElementById("btnUploadPem").addEventListener("click", async () => {
      const k = pemKey.files && pemKey.files[0];
      const c = pemChain.files && pemChain.files[0];
      if (!k) { toast("Choose private key (.key / .pem)", "error"); return; }
      if (!c) { toast("Choose certificate / chain (.crt / .pem)", "error"); return; }
      try {
        await DnsApi.uploadDnsTlsPem(k, c, document.getElementById("pemKeyPass").value);
        toast("Certificate uploaded (PEM → PKCS#12)");
        document.getElementById("certStatus").textContent = "Certificate: set";
        document.getElementById("certStatus").classList.add("is-set");
        pemKey.value = "";
        pemChain.value = "";
        pemKeyName.textContent = "no key";
        pemChainName.textContent = "no chain";
        document.getElementById("pemKeyPass").value = "";
      } catch (ex) { toast(ex.message, "error"); }
    });

    document.getElementById("btnSave").addEventListener("click", async () => {
      const dnsPort = Number(document.getElementById("dnsPort").value) || 53;
      const wantDot = document.getElementById("dot").checked;
      const wantDoh = document.getElementById("doh").checked;
      const certSet = document.getElementById("certStatus").classList.contains("is-set");
      if ((wantDot || wantDoh) && !certSet) {
        toast("DoT / direct DoH need a TLS certificate — upload .pfx or PEM first", "error");
        return;
      }
      try {
        await DnsApi.saveSettings({
          dnsServerLocalEndPoints: `0.0.0.0:${dnsPort},[::]:${dnsPort}`,
          enableDnsOverHttp: document.getElementById("dohHttp").checked,
          enableDnsOverTls: wantDot,
          enableDnsOverHttps: wantDoh,
          dnsOverTlsPort: Number(document.getElementById("dotPort").value) || 853,
          dnsOverHttpPort: Number(document.getElementById("httpPort").value) || 8053,
          dnsOverHttpsPort: Number(document.getElementById("httpsPort").value) || 443,
        });
        toast("Client protocol saved");
      } catch (ex) { toast(ex.message, "error"); }
    });
  }

  async function viewQueryLog() {
    let page = 1;
    let totalPages = 1;
    let totalEntries = 0;
    let logAllowed = false;
    // только после Apply — не при наборе текста
    const applied = {
      qname: "",
      clientIp: "",
      responseType: "Blocked",
      protocol: "",
      suspiciousOnly: false,
    };

    shell("Query log", `
      <input type="search" class="filter-input" id="logQname" placeholder="Domain contains…" />
      <input type="search" class="filter-input filter-input-sm" id="logClient" placeholder="Client IP…" />
      <select id="logType" class="toolbar-select" title="Response type">
        <option value="Blocked">Blocked</option>
        <option value="UpstreamBlocked">Upstream blocked</option>
        <option value="CacheBlocked">Cache blocked</option>
        <option value="Cached" data-allowed-only="1">Cached</option>
        <option value="Recursive" data-allowed-only="1">Recursive</option>
        <option value="Authoritative" data-allowed-only="1">Authoritative</option>
        <option value="" data-allowed-only="1">Any type</option>
      </select>
      <select id="logProto" class="toolbar-select" title="Protocol">
        <option value="">Any protocol</option>
        <option value="Udp">UDP</option>
        <option value="Tcp">TCP</option>
        <option value="Tls">DoT</option>
        <option value="Https">DoH</option>
      </select>
      <label class="inline toolbar-check" title="Entropy / long labels / rare qtype / client burst">
        <input type="checkbox" id="logSusOnly" /> Suspicious
      </label>
      <button type="button" class="btn" id="btnLogApply">Apply</button>
      <button type="button" class="btn btn-secondary" id="btnLogClear">Clear</button>
      <div class="toolbar-spacer"></div>
      <label class="inline toolbar-check" title="Off = store only blocked/dropped in DB">
        <input type="checkbox" id="logAllowedToggle" /> Log allowed
      </label>
      <button type="button" class="btn btn-secondary" id="btnLogPrev">←</button>
      <span class="dash-pill muted" id="logPageMeta">—</span>
      <button type="button" class="btn btn-secondary" id="btnLogNext">→</button>
      <button type="button" class="btn btn-secondary" id="btnLogRefresh">Refresh</button>
    `, `<div class="table-wrap"><div class="table-scroll" id="logBox"><div class="empty">Loading…</div></div></div>`, "querylog");

    const box = document.getElementById("logBox");
    const typeSel = document.getElementById("logType");
    const protoSel = document.getElementById("logProto");
    const allowedToggle = document.getElementById("logAllowedToggle");
    const susOnly = document.getElementById("logSusOnly");
    typeSel.value = applied.responseType;
    susOnly.checked = !!applied.suspiciousOnly;

    function syncAllowedTypeOptions() {
      typeSel.querySelectorAll("option[data-allowed-only]").forEach((opt) => {
        opt.disabled = !logAllowed;
        opt.hidden = !logAllowed;
      });
      if (!logAllowed) {
        const v = typeSel.value;
        if (!v || !/Blocked/i.test(v)) {
          typeSel.value = "Blocked";
          applied.responseType = "Blocked";
        }
      }
      allowedToggle.checked = !!logAllowed;
    }

    function readDraft() {
      return {
        qname: (document.getElementById("logQname").value || "").trim(),
        clientIp: (document.getElementById("logClient").value || "").trim(),
        responseType: typeSel.value,
        protocol: protoSel.value,
        suspiciousOnly: !!susOnly.checked,
      };
    }

    function writeDraft(f) {
      document.getElementById("logQname").value = f.qname || "";
      document.getElementById("logClient").value = f.clientIp || "";
      typeSel.value = f.responseType;
      protoSel.value = f.protocol || "";
      susOnly.checked = !!f.suspiciousOnly;
    }

    function badgeClass(rt) {
      const t = String(rt || "");
      if (/Blocked/i.test(t)) return "badge badge-warn";
      if (/Cached|Recursive|Authoritative/i.test(t)) return "badge";
      return "badge badge-muted";
    }

    function suspicionBadge(sus) {
      if (!sus || !sus.level || sus.level === "ok") {
        return `<span class="badge badge-muted" title="score ${sus && sus.score != null ? sus.score : 0}">ok</span>`;
      }
      const reasons = (sus.reasons || []).join(", ");
      const title = `score ${sus.score}` + (reasons ? ` · ${reasons}` : "")
        + (sus.entropy != null ? ` · H=${sus.entropy}` : "");
      const cls = sus.level === "high" ? "badge badge-danger" : "badge badge-warn";
      return `<span class="${cls}" title="${escapeHtml(title)}">${escapeHtml(sus.level)}</span>`;
    }

    function renderEntries(entries) {
      document.getElementById("logPageMeta").textContent =
        totalEntries ? `p.${page}/${totalPages} · ${fmtNum(totalEntries)}` : "empty";
      if (!entries.length) {
        box.innerHTML = `<div class="empty"><strong>No queries</strong><span>${
          totalEntries === 0
            ? (logAllowed
              ? "Nothing matched. Widen filters or Apply after Clear."
              : "Only blocked queries are stored. Turn on «Log allowed» to record the rest.")
            : (applied.suspiciousOnly
              ? "No suspicious rows on this fetch. Try «Log allowed» + Any type, or next page."
              : "Nothing on this page.")
        }</span></div>`;
        return;
      }
      box.innerHTML = `
        <table class="data">
          <thead>
            <tr>
              <th>Time</th>
              <th>Client</th>
              <th>Domain</th>
              <th>Type</th>
              <th>Proto</th>
              <th>Response</th>
              <th>Risk</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            ${entries.map((e) => {
              const ts = e.timestamp ? fmtDateTime(e.timestamp) : "—";
              const qn = e.qname || "—";
              const rt = e.responseType || e.rcode || "—";
              const isBlocked = /Blocked/i.test(String(e.responseType || ""));
              const sus = e.suspicion || null;
              return `<tr>
                <td class="nowrap">${escapeHtml(ts)}</td>
                <td>${escapeHtml(e.clientIpAddress || "—")}</td>
                <td><div class="cell-url">${escapeHtml(qn)}</div></td>
                <td>${escapeHtml(e.qtype || "—")}</td>
                <td>${escapeHtml(e.protocol || "—")}</td>
                <td><span class="${badgeClass(rt)}">${escapeHtml(rt)}</span></td>
                <td>${suspicionBadge(sus)}</td>
                <td class="actions">
                  ${isBlocked ? `<button type="button" class="btn btn-secondary btn-sm" data-allow="${escapeHtml(qn)}">Allow</button>` : ""}
                </td>
              </tr>`;
            }).join("")}
          </tbody>
        </table>`;
      box.querySelectorAll("[data-allow]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const domain = (btn.getAttribute("data-allow") || "").replace(/\.$/, "");
          if (!domain || domain === "—") return;
          const ok = await confirmModal({
            title: "Allow domain",
            text: `Add ${domain} to Allowed (bypass block lists)?`,
            dangerLabel: "Allow",
          });
          if (!ok) return;
          try {
            await DnsApi.addAllowed(domain);
            toast("Allowed: " + domain);
          } catch (ex) { toast(ex.message, "error"); }
        });
      });
    }

    async function loadLog() {
      box.innerHTML = `<div class="empty">Loading…</div>`;
      try {
        const data = await DnsApi.blockingLog({
          page,
          perPage: 50,
          qname: applied.qname,
          clientIp: applied.clientIp,
          responseType: applied.responseType,
          protocol: applied.protocol,
          suspiciousOnly: applied.suspiciousOnly ? "true" : "",
          ensure: true,
        });
        page = Number(data.pageNumber) || page;
        totalPages = Number(data.totalPages) || 1;
        totalEntries = Number(data.totalEntries) || 0;
        if (typeof data.logAllowedQueries === "boolean") {
          logAllowed = data.logAllowedQueries;
          syncAllowedTypeOptions();
        }
        if (data.logger && data.logger.installedNow) {
          toast("Query Logs (Sqlite) installed");
        }
        renderEntries(data.entries || []);
      } catch (ex) {
        const missing = ex.status === 409 || /Query Logs|missing-app|не установлен/i.test(ex.message || "");
        if (missing) {
          box.innerHTML = `
            <div class="empty log-install">
              <strong>Query Logs (Sqlite) нужен</strong>
              <span>Загрузи zip вручную или положи в /opt/dns/vendor/.</span>
              <span class="hint">Файл: QueryLogsSqliteApp-v9.1.2.zip</span>
              <div class="log-install-row">
                <input type="file" id="logZip" accept=".zip,application/zip" />
                <button type="button" class="btn" id="btnLogInstall">Install</button>
              </div>
              <div class="form-error" id="logInstallErr"></div>
            </div>`;
          document.getElementById("btnLogInstall").addEventListener("click", async () => {
            const inp = document.getElementById("logZip");
            const f = inp.files && inp.files[0];
            const errEl = document.getElementById("logInstallErr");
            if (!f) { errEl.textContent = "Choose .zip first"; return; }
            errEl.textContent = "Installing…";
            try {
              await DnsApi.installBlockingLog(f);
              toast("Query Logs installed");
              await loadLog();
            } catch (e2) {
              errEl.textContent = e2.message || "Install failed";
            }
          });
          return;
        }
        box.innerHTML = `<div class="empty"><strong>Failed</strong><span>${escapeHtml(ex.message)}</span></div>`;
      }
    }

    function applyFilters() {
      const d = readDraft();
      applied.qname = d.qname;
      applied.clientIp = d.clientIp;
      applied.responseType = d.responseType;
      applied.protocol = d.protocol;
      applied.suspiciousOnly = d.suspiciousOnly;
      page = 1;
      loadLog();
    }

    function clearFilters() {
      applied.qname = "";
      applied.clientIp = "";
      applied.responseType = logAllowed ? "" : "Blocked";
      applied.protocol = "";
      applied.suspiciousOnly = false;
      writeDraft(applied);
      page = 1;
      loadLog();
    }

    allowedToggle.addEventListener("change", async () => {
      const want = allowedToggle.checked;
      allowedToggle.disabled = true;
      try {
        const r = await DnsApi.saveUiPrefs({ logAllowedQueries: want });
        logAllowed = !!r.logAllowedQueries;
        syncAllowedTypeOptions();
        const purged = r.logFilter && r.logFilter.purgedNonBlocked;
        toast(
          logAllowed
            ? "Logging all DNS queries"
            : `Blocked-only logging${purged ? ` · purged ${purged} allowed` : ""}`
        );
        page = 1;
        await loadLog();
      } catch (ex) {
        allowedToggle.checked = !want;
        toast(ex.message, "error");
      } finally {
        allowedToggle.disabled = false;
      }
    });

    document.getElementById("btnLogApply").addEventListener("click", applyFilters);
    document.getElementById("btnLogClear").addEventListener("click", clearFilters);
    document.getElementById("logQname").addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); applyFilters(); }
    });
    document.getElementById("logClient").addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); applyFilters(); }
    });
    document.getElementById("btnLogRefresh").addEventListener("click", () => loadLog());
    document.getElementById("btnLogPrev").addEventListener("click", () => {
      if (page > 1) { page -= 1; loadLog(); }
    });
    document.getElementById("btnLogNext").addEventListener("click", () => {
      if (page < totalPages) { page += 1; loadLog(); }
    });
    syncAllowedTypeOptions();
    await loadLog();
  }

  async function viewSettings(initialTab) {
    const tab = ["general", "blocking", "panel-tls"].includes(initialTab) ? initialTab : "general";
    shell("Settings", `
      <div class="subnav">
        <button type="button" class="subnav-item ${tab === "general" ? "active" : ""}" data-stab="general">General</button>
        <button type="button" class="subnav-item ${tab === "blocking" ? "active" : ""}" data-stab="blocking">Blocking</button>
        <button type="button" class="subnav-item ${tab === "panel-tls" ? "active" : ""}" data-stab="panel-tls">Panel TLS</button>
      </div>
      <div class="toolbar-spacer"></div>
      <span id="setToolbarExtra"></span>
    `, `<div id="setWork" class="form-panel"><div id="setInner"><div class="empty">Loading…</div></div></div>`, "settings");

    root.querySelectorAll("[data-stab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        location.hash = "#/settings/" + btn.getAttribute("data-stab");
      });
    });

    const inner = document.getElementById("setInner");
    const extra = document.getElementById("setToolbarExtra");

    if (tab === "general") {
      extra.innerHTML = `<button type="button" class="btn" id="btnSaveUiPrefs">Save</button>`;
      try {
        const prefs = await DnsApi.uiPrefs();
        uiPrefs = {
          timezone: prefs.timezone || "Europe/Moscow",
          options: Array.isArray(prefs.options) ? prefs.options : [],
          timezoneLabel: prefs.timezoneLabel || "",
        };
        const opts = (uiPrefs.options.length
          ? uiPrefs.options
          : [
              { value: "Europe/Moscow", label: "UTC+3 (Moscow)" },
              { value: "UTC", label: "UTC" },
              { value: "local", label: "Browser local" },
            ]
        ).map((o) => `<option value="${escapeHtml(o.value)}" ${o.value === uiPrefs.timezone ? "selected" : ""}>${escapeHtml(o.label)}</option>`).join("");
        const sample = fmtDateTime(new Date());
        const maxRec = Number(prefs.maxLogRecords) || 2500000;
        const maxDays = Number(prefs.maxLogDays);
        const daysVal = Number.isFinite(maxDays) ? maxDays : 90;
        const estLabel = prefs.logDbEstimateLabel || "";
        inner.innerHTML = `
          <div class="form-card">
            <p class="section-title">Time zone</p>
            <div class="proto-list">
              <div class="proto-row">
                <div class="proto-main">
                  <div class="field field-flush">
                    <label for="uiTimezone">Display time zone</label>
                    <select id="uiTimezone">${opts}</select>
                    <div class="hint">Default UTC+3 (Moscow). Applies to dashboard charts, query log, certificates, blocking timestamps.</div>
                  </div>
                </div>
              </div>
              <div class="proto-row">
                <div class="proto-main">
                  <label>Sample now</label>
                  <div class="cert-status is-set" id="uiTzSample">${escapeHtml(sample)}</div>
                </div>
              </div>
            </div>
          </div>

          <div class="form-card" style="margin-top:var(--space-md)">
            <p class="section-title">Query log storage</p>
            <div class="proto-list">
              <div class="proto-row">
                <div class="proto-main">
                  <div class="field field-flush">
                    <label for="uiMaxLogRecords">Max records</label>
                    <input type="number" id="uiMaxLogRecords" min="1000" max="20000000" step="1000" value="${maxRec}" />
                    <div class="hint">Default 2 500 000 ≈ ~2 GiB budget (~800 B/row). What hits first — records or days — wins.</div>
                  </div>
                </div>
              </div>
              <div class="proto-row">
                <div class="proto-main">
                  <div class="field field-flush">
                    <label for="uiMaxLogDays">Max age (days)</label>
                    <input type="number" id="uiMaxLogDays" min="0" max="3650" value="${daysVal}" />
                    <div class="hint">0 = no age cleanup. Default 90.</div>
                  </div>
                </div>
              </div>
              <div class="proto-row">
                <div class="proto-main">
                  <label>Estimate</label>
                  <div class="cert-status is-set" id="uiLogEst">${escapeHtml(estLabel)}</div>
                  <div class="hint">«Log allowed» off still keeps only blocked in DB; this cap is the hard ceiling.</div>
                </div>
              </div>
            </div>
          </div>`;
        const sel = document.getElementById("uiTimezone");
        const recInp = document.getElementById("uiMaxLogRecords");
        const daysInp = document.getElementById("uiMaxLogDays");
        const estEl = document.getElementById("uiLogEst");
        const refreshSample = () => {
          const prev = uiPrefs.timezone;
          uiPrefs.timezone = sel.value;
          document.getElementById("uiTzSample").textContent = fmtDateTime(new Date());
          uiPrefs.timezone = prev;
        };
        const refreshEst = () => {
          const n = Number(recInp.value) || 0;
          const mib = (n * 800) / (1024 * 1024);
          estEl.textContent = `~${Math.round(mib)} MiB @ ~800 B/row`;
        };
        sel.addEventListener("change", refreshSample);
        recInp.addEventListener("input", refreshEst);
        document.getElementById("btnSaveUiPrefs").addEventListener("click", async () => {
          const btn = document.getElementById("btnSaveUiPrefs");
          btn.disabled = true;
          try {
            const r = await DnsApi.saveUiPrefs({
              timezone: sel.value,
              maxLogRecords: Number(recInp.value),
              maxLogDays: Number(daysInp.value),
            });
            uiPrefs = {
              timezone: r.timezone || sel.value,
              options: Array.isArray(r.options) ? r.options : uiPrefs.options,
              timezoneLabel: r.timezoneLabel || "",
            };
            const ret = r.logRetention && r.logRetention.applied;
            toast(
              `Saved · ${uiPrefs.timezoneLabel || uiPrefs.timezone}` +
                ` · logs ${fmtNum(r.maxLogRecords)} / ${r.maxLogDays}d` +
                (ret ? " · applied to Query Logs" : "")
            );
            await viewSettings("general");
          } catch (ex) {
            toast(ex.message, "error");
            btn.disabled = false;
          }
        });
      } catch (ex) {
        inner.innerHTML = `<div class="empty"><strong>Failed to load</strong><span>${escapeHtml(ex.message)}</span></div>`;
      }
      return;
    }

    if (tab === "panel-tls") {
      extra.innerHTML = "";
      try {
        const st = await DnsApi.panelTls();
        const httpsPort = st.httpsPort || 9443;
        const httpPort = st.httpPort || 9080;
        const httpOn = st.httpEnabled !== false;
        const statusLine = st.present
          ? `set${st.selfSigned ? " (self-signed)" : ""}`
          : "not set";
        inner.innerHTML = `
          <div class="form-card">
            <p class="section-title">Panel TLS</p>
            <div class="proto-list">
              <div class="proto-row">
                <div class="proto-main">
                  <label>Status</label>
                  <div class="cert-status ${st.present ? "is-set" : ""}">Certificate: ${escapeHtml(statusLine)}</div>
                  <div class="hint">HTTPS for panel UI (nginx), not DoT/DoH. Listen ports: HTTP :${httpPort}${httpOn ? "" : " (redirect→HTTPS)"} · HTTPS :${httpsPort} — change via <code>sudo dns ports</code>.</div>
                </div>
              </div>
              <div class="proto-row">
                <div class="proto-main">
                  <div class="dash-mini-stats">
                    <div><span>Subject</span><strong>${escapeHtml(st.subject || "—")}</strong></div>
                    <div><span>Issuer</span><strong>${escapeHtml(st.issuer || "—")}</strong></div>
                    <div><span>Valid until</span><strong>${escapeHtml(st.notAfter ? fmtDateTime(st.notAfter) : "—")}</strong></div>
                    <div><span>HTTPS URL</span><strong>https://&lt;host&gt;:${httpsPort}/</strong></div>
                  </div>
                </div>
              </div>
              <div class="proto-row proto-row-cert">
                <div class="proto-main">
                  <label>PEM key + certificate (chain)</label>
                  <div class="hint">Replaces nginx TLS and reloads dns-nginx (HUP).</div>
                </div>
                <div class="cert-box">
                  <div class="cert-controls">
                    <label class="file-btn btn btn-secondary btn-sm">
                      Choose key
                      <input type="file" id="panelKeyFile" accept=".key,.pem,.txt,application/x-pem-file" hidden />
                    </label>
                    <span class="file-name" id="panelKeyName">no key</span>
                    <label class="file-btn btn btn-secondary btn-sm">
                      Choose cert
                      <input type="file" id="panelCertFile" accept=".crt,.cer,.pem,.txt,application/x-pem-file,application/x-x509-ca-cert" hidden />
                    </label>
                    <span class="file-name" id="panelCertName">no cert</span>
                    <button type="button" class="btn btn-sm" id="btnUploadPanelTls">Upload PEM</button>
                  </div>
                </div>
              </div>
            </div>
          </div>`;
        const keyInput = document.getElementById("panelKeyFile");
        const certInput = document.getElementById("panelCertFile");
        keyInput.addEventListener("change", () => {
          const f = keyInput.files && keyInput.files[0];
          document.getElementById("panelKeyName").textContent = f ? f.name : "no key";
        });
        certInput.addEventListener("change", () => {
          const f = certInput.files && certInput.files[0];
          document.getElementById("panelCertName").textContent = f ? f.name : "no cert";
        });
        document.getElementById("btnUploadPanelTls").addEventListener("click", async () => {
          const keyEl = document.getElementById("panelKeyFile");
          const certEl = document.getElementById("panelCertFile");
          const k = keyEl && keyEl.files && keyEl.files[0];
          const c = certEl && certEl.files && certEl.files[0];
          if (!k) { toast("Choose private key (.pem / .key)", "error"); return; }
          if (!c) { toast("Choose certificate (.crt / .pem)", "error"); return; }
          const btn = document.getElementById("btnUploadPanelTls");
          btn.disabled = true;
          try {
            const r = await DnsApi.uploadPanelTls(k, c);
            const reloadOk = r.reload && r.reload.reloaded;
            toast(reloadOk ? "Panel TLS uploaded · nginx reloaded" : `Panel TLS uploaded · ${r.reload?.reason || "reload pending"}`);
            await viewSettings("panel-tls");
          } catch (ex) {
            toast(ex.message, "error");
            btn.disabled = false;
          }
        });
      } catch (ex) {
        inner.innerHTML = `<div class="empty"><strong>Failed to load</strong><span>${escapeHtml(ex.message)}</span></div>`;
      }
      return;
    }

    if (tab === "blocking") {
      extra.innerHTML = `<button type="button" class="btn" id="btnSaveBlk">Save</button>`;
      try {
        const data = await DnsApi.blocking();
        const s = data.response || {};
        const bypass = Array.isArray(s.blockingBypassList) ? s.blockingBypassList.join("\n") : "";
        const custom = Array.isArray(s.customBlockingAddresses) ? s.customBlockingAddresses.join("\n") : "";
        const btype = s.blockingType || "NxDomain";
        const till = s.temporaryDisableBlockingTill
          ? fmtDateTime(s.temporaryDisableBlockingTill)
          : "—";
        inner.innerHTML = `
          <div class="form-card">
            <p class="section-title">Blocking</p>
            <div class="proto-list">
              <div class="proto-row">
                <div class="proto-main">
                  <label class="inline"><input type="checkbox" id="blkEnable" ${s.enableBlocking ? "checked" : ""} /> Enable blocking</label>
                  <div class="hint">Master switch for DNS sinkhole.</div>
                </div>
              </div>
              <div class="proto-row">
                <div class="proto-main">
                  <label class="inline"><input type="checkbox" id="blkTxtReport" ${s.allowTxtBlockingReport ? "checked" : ""} /> Allow TXT blocking report</label>
                  <div class="hint">Clients may query why a name was blocked.</div>
                </div>
              </div>
              <div class="proto-row">
                <div class="proto-main">
                  <label>Temporarily disabled till</label>
                  <div class="blk-inline">
                    <span id="blkTill">${escapeHtml(till)}</span>
                    <input type="number" id="blkTempMin" class="input-sm" min="1" value="30" title="minutes" />
                    <button type="button" class="btn btn-secondary btn-sm" id="btnTempDisable">Disable now</button>
                  </div>
                  <div class="hint">Pause blocking for N minutes without turning it off permanently.</div>
                </div>
              </div>
              <div class="proto-row">
                <div class="proto-main">
                  <label>Blocking type</label>
                  <div class="blk-radios">
                    <label class="inline"><input type="radio" name="blkType" value="NxDomain" ${btype === "NxDomain" ? "checked" : ""} /> NXDOMAIN</label>
                    <label class="inline"><input type="radio" name="blkType" value="AnyAddress" ${btype === "AnyAddress" ? "checked" : ""} /> Any address (0.0.0.0 / ::)</label>
                    <label class="inline"><input type="radio" name="blkType" value="CustomAddress" ${btype === "CustomAddress" ? "checked" : ""} /> Custom address</label>
                  </div>
                </div>
              </div>
              <div class="proto-row">
                <div class="proto-main">
                  <div class="field field-flush">
                    <label for="blkCustom">Custom blocking addresses</label>
                    <textarea id="blkCustom" rows="2" placeholder="one IP per line">${escapeHtml(custom)}</textarea>
                  </div>
                </div>
              </div>
              <div class="proto-row">
                <div class="proto-main">
                  <div class="field field-flush">
                    <label for="blkTtl">Blocking answer TTL (seconds)</label>
                    <input type="number" id="blkTtl" value="${Number(s.blockingAnswerTtl) || 30}" min="0" />
                  </div>
                </div>
              </div>
              <div class="proto-row">
                <div class="proto-main">
                  <div class="field field-flush">
                    <label for="blkBypass">Blocking bypass list</label>
                    <textarea id="blkBypass" rows="3" placeholder="client IP / network, one per line">${escapeHtml(bypass)}</textarea>
                    <div class="hint">Clients in this list skip blocking. Lists / Allowed / Blocked — раздел Blocking.</div>
                  </div>
                </div>
              </div>
            </div>
          </div>`;

        document.getElementById("btnTempDisable").addEventListener("click", async () => {
          const minutes = Number(document.getElementById("blkTempMin").value) || 30;
          try {
            const r = await DnsApi.temporaryDisableBlocking(minutes);
            const t = (r.response || {}).temporaryDisableBlockingTill;
            document.getElementById("blkTill").textContent = t ? fmtDateTime(t) : "—";
            toast("Blocking temporarily disabled");
          } catch (ex) { toast(ex.message, "error"); }
        });
        document.getElementById("btnSaveBlk").addEventListener("click", async () => {
          const lines = (id) => document.getElementById(id).value.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
          const typeEl = document.querySelector("input[name=blkType]:checked");
          try {
            await DnsApi.saveBlocking({
              enableBlocking: document.getElementById("blkEnable").checked,
              allowTxtBlockingReport: document.getElementById("blkTxtReport").checked,
              blockingType: typeEl ? typeEl.value : "NxDomain",
              customBlockingAddresses: lines("blkCustom"),
              blockingAnswerTtl: Number(document.getElementById("blkTtl").value) || 30,
              blockingBypassList: lines("blkBypass"),
            });
            toast("Blocking settings saved");
          } catch (ex) { toast(ex.message, "error"); }
        });
      } catch (ex) {
        inner.innerHTML = `<div class="empty"><strong>Failed to load</strong><span>${escapeHtml(ex.message)}</span></div>`;
      }
    }
  }

  async function viewBlocking(initialTab) {
    const tab = ["lists", "allowed", "blocked"].includes(initialTab) ? initialTab : "lists";
    shell("Blocking", `
      <div class="subnav">
        <button type="button" class="subnav-item ${tab === "lists" ? "active" : ""}" data-btab="lists">Lists</button>
        <button type="button" class="subnav-item ${tab === "allowed" ? "active" : ""}" data-btab="allowed">Allowed</button>
        <button type="button" class="subnav-item ${tab === "blocked" ? "active" : ""}" data-btab="blocked">Blocked</button>
      </div>
      <div class="toolbar-spacer"></div>
      <span id="blkToolbarExtra"></span>
    `, `<div id="blkWork" class="table-wrap"><div id="blkInner" class="table-scroll"><div class="empty">Loading…</div></div></div>`, "blocking");

    root.querySelectorAll("[data-btab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        location.hash = "#/blocking/" + btn.getAttribute("data-btab");
      });
    });

    const work = document.getElementById("blkWork");
    const inner = document.getElementById("blkInner");
    const extra = document.getElementById("blkToolbarExtra");

    function parseListUrl(raw) {
      let s = String(raw || "").trim();
      if (!s) return null;
      let disabled = false;
      if (s.startsWith("#")) {
        disabled = true;
        s = s.slice(1).trim();
        if (!s) return null;
      }
      if (s.startsWith("!")) {
        const url = s.slice(1).trim();
        if (!url) return null;
        return { kind: "allow", url, disabled, raw: String(raw).trim() };
      }
      return { kind: "block", url: s, disabled, raw: String(raw).trim() };
    }
    function encodeListUrl(item) {
      let s = item.kind === "allow" ? "!" + item.url : item.url;
      if (item.disabled) s = "#" + s;
      return s;
    }
    function listKey(item) {
      return item.kind + "\0" + item.url;
    }

    if (tab === "lists") {
      let listCache = [];
      let listSort = { key: "url", dir: 1 };
      let intervalHours = 24;
      let nextUpdatedOn = null;

      extra.innerHTML = `
        <input type="search" class="filter-input" id="blkFilter" placeholder="Filter by URL…" />
        <label class="toolbar-hint" for="blkInterval">Interval (h)</label>
        <input type="number" id="blkInterval" class="input-sm" min="0" max="168" value="24" />
        <button type="button" class="btn btn-secondary" id="btnSaveInterval">Save interval</button>
        <span class="toolbar-hint" id="blkNextHint">Next: —</span>
        <div class="toolbar-spacer"></div>
        <button type="button" class="btn btn-secondary" id="btnBlkRefresh">Refresh</button>
        <button type="button" class="btn btn-secondary" id="btnForceLists">Update now</button>
        <button type="button" class="btn" id="btnAddList">Add list</button>
      `;

      document.getElementById("btnSaveInterval").addEventListener("click", async () => {
        const hours = Number(document.getElementById("blkInterval").value);
        try {
          await DnsApi.saveBlocking({ blockListUpdateIntervalHours: hours });
          intervalHours = hours;
          toast("Interval saved");
          await loadLists();
        } catch (ex) { toast(ex.message, "error"); }
      });

      function renderLists() {
        const box = inner;
        const q = (document.getElementById("blkFilter")?.value || "").trim().toLowerCase();
        let rows = listCache.slice();
        if (q) rows = rows.filter((x) =>
          x.url.toLowerCase().includes(q)
          || x.kind.includes(q)
          || (x.note || "").toLowerCase().includes(q)
          || (x.disabled && "off disabled".includes(q))
        );
        rows.sort((a, b) => {
          const ka = String(a[listSort.key] ?? "").toLowerCase();
          const kb = String(b[listSort.key] ?? "").toLowerCase();
          if (ka < kb) return -1 * listSort.dir;
          if (ka > kb) return 1 * listSort.dir;
          return 0;
        });
        const nextLabel = nextUpdatedOn ? fmtDateTime(nextUpdatedOn) : "—";
        const nextHint = document.getElementById("blkNextHint");
        if (nextHint) nextHint.textContent = "Next: " + nextLabel;
        const iv = document.getElementById("blkInterval");
        if (iv && document.activeElement !== iv) iv.value = String(intervalHours);
        if (!rows.length) {
          box.innerHTML = `<div class="empty"><strong>No lists</strong><span>${
            listCache.length ? "Nothing matches the filter." : "No block/allow list URLs yet. Add a list."
          }</span></div>`;
          return;
        }
        box.innerHTML = `<table class="data">
          <thead><tr>
            <th class="sortable" data-sort="kind">Type${sortMark("kind", listSort)}</th>
            <th class="sortable" data-sort="url">URL${sortMark("url", listSort)}</th>
            <th>Status</th>
            <th></th>
          </tr></thead>
          <tbody>${rows.map((item, idx) => `
            <tr class="${item.disabled ? "is-disabled" : ""}">
              <td><span class="badge">${item.kind === "allow" ? "Allow" : "Block"}</span></td>
              <td class="cell-url">
                <div class="cell-url-main">${escapeHtml(item.url)}</div>
                ${item.note ? `<div class="cell-note">${escapeHtml(item.note)}</div>` : ""}
              </td>
              <td>${item.disabled ? '<span class="badge badge-muted">off</span>' : '<span class="badge">on</span>'}</td>
              <td class="actions">
                <button type="button" class="btn btn-secondary btn-sm" data-tog="${idx}">${item.disabled ? "Enable" : "Disable"}</button>
                <button type="button" class="btn btn-danger btn-sm" data-del="${idx}">Delete</button>
              </td>
            </tr>`).join("")}</tbody></table>`;
        box.querySelectorAll("[data-del]").forEach((btn) => {
          const item = rows[Number(btn.getAttribute("data-del"))];
          btn.addEventListener("click", async () => {
            const ok = await confirmModal({
              title: "Delete list?",
              text: `Remove “${item.url}” from ${item.kind === "allow" ? "allow" : "block"} lists.`,
            });
            if (!ok) return;
            listCache = listCache.filter((x) => listKey(x) !== listKey(item));
            try {
              await DnsApi.saveBlocking({ blockListUrls: listCache.map(encodeListUrl) });
              toast("List removed");
              await loadLists();
            } catch (ex) { toast(ex.message, "error"); }
          });
        });
        box.querySelectorAll("[data-tog]").forEach((btn) => {
          const item = rows[Number(btn.getAttribute("data-tog"))];
          btn.addEventListener("click", async () => {
            const next = listCache.map((x) => {
              if (listKey(x) !== listKey(item)) return x;
              return { ...x, disabled: !x.disabled, raw: encodeListUrl({ ...x, disabled: !x.disabled }) };
            });
            try {
              await DnsApi.saveBlocking({ blockListUrls: next.map(encodeListUrl) });
              toast(item.disabled ? "List enabled" : "List disabled");
              await loadLists();
            } catch (ex) { toast(ex.message, "error"); }
          });
        });
        bindSortHeaders(box, listSort, renderLists);
      }

      async function loadLists() {
        inner.innerHTML = `<div class="empty">Loading…</div>`;
        try {
          const data = await DnsApi.blocking();
          const s = data.response || {};
          if (Array.isArray(s.blockListItems) && s.blockListItems.length) {
            listCache = s.blockListItems.map((x) => ({
              kind: x.kind === "allow" ? "allow" : "block",
              url: String(x.url || ""),
              disabled: !!x.disabled,
              note: String(x.note || ""),
              raw: encodeListUrl({
                kind: x.kind === "allow" ? "allow" : "block",
                url: String(x.url || ""),
                disabled: !!x.disabled,
              }),
            })).filter((x) => x.url);
          } else {
            const raw = Array.isArray(s.blockListUrls) ? s.blockListUrls : [];
            listCache = raw.map(parseListUrl).filter(Boolean);
          }
          intervalHours = Number(s.blockListUpdateIntervalHours) || 0;
          nextUpdatedOn = s.blockListNextUpdatedOn || null;
          renderLists();
        } catch (ex) {
          inner.innerHTML = `<div class="empty"><strong>Error</strong><span>${escapeHtml(ex.message)}</span></div>`;
        }
      }

      function openAddList() {
        const back = document.createElement("div");
        back.className = "modal-back";
        back.innerHTML = `
          <div class="modal">
            <h3>Add list</h3>
            <div class="field"><label>URL</label>
              <input id="listUrl" placeholder="https://example.com/list.txt" />
              <div class="hint">http(s) or file:///… path on the DNS server</div>
            </div>
            <div class="field"><label>Type</label>
              <select id="listKind">
                <option value="block">Block list</option>
                <option value="allow">Allow list</option>
              </select>
            </div>
            <div class="form-error" id="listErr"></div>
            <div class="modal-actions">
              <button type="button" class="btn btn-secondary" data-a="cancel">Cancel</button>
              <button type="button" class="btn" data-a="ok">Add</button>
            </div>
          </div>`;
        document.body.appendChild(back);
        back.addEventListener("click", async (e) => {
          const a = e.target.getAttribute("data-a");
          if (a === "cancel" || e.target === back) { back.remove(); return; }
          if (a !== "ok") return;
          let url = back.querySelector("#listUrl").value.trim();
          const kind = back.querySelector("#listKind").value;
          if (url.startsWith("!")) url = url.slice(1).trim();
          if (!url) { back.querySelector("#listErr").textContent = "Enter a URL"; return; }
          const item = { kind, url, disabled: false, raw: kind === "allow" ? "!" + url : url };
          if (listCache.some((x) => listKey(x) === listKey(item))) {
            back.querySelector("#listErr").textContent = "This URL is already in the list";
            return;
          }
          try {
            const next = listCache.concat([item]);
            await DnsApi.saveBlocking({ blockListUrls: next.map(encodeListUrl) });
            toast("List added");
            back.remove();
            await loadLists();
          } catch (ex) {
            back.querySelector("#listErr").textContent = ex.message;
          }
        });
      }

      document.getElementById("blkFilter").addEventListener("input", renderLists);
      document.getElementById("btnBlkRefresh").addEventListener("click", loadLists);
      document.getElementById("btnForceLists").addEventListener("click", async () => {
        try {
          await DnsApi.forceUpdateBlockLists();
          toast("Block list update scheduled");
          await loadLists();
        } catch (ex) { toast(ex.message, "error"); }
      });
      document.getElementById("btnAddList").addEventListener("click", openAddList);
      await loadLists();
      return;
    }

    if (tab === "log") {
      location.hash = "#/query-log";
      return;
    }

    const isAllowed = tab === "allowed";
    const title = isAllowed ? "Allowed domains" : "Blocked domains";
    extra.innerHTML = `
      <input type="search" class="filter-input" id="blkFilter" placeholder="Filter…" />
      <div class="toolbar-spacer"></div>
      <button type="button" class="btn btn-secondary" id="btnBlkRefresh">Refresh</button>
      <button type="button" class="btn btn-danger" id="btnBlkFlush">Flush all</button>
      <button type="button" class="btn" id="btnBlkAdd">Add domain</button>
    `;
    work.className = "table-wrap";
    work.innerHTML = `<div class="table-scroll" id="blkInner"></div>`;
    const box = document.getElementById("blkInner");

    let items = [];
    async function loadList() {
      box.innerHTML = `<div class="empty">Loading…</div>`;
      try {
        const data = isAllowed ? await DnsApi.allowedList() : await DnsApi.blockedList();
        items = data.items || [];
        renderList();
      } catch (ex) {
        box.innerHTML = `<div class="empty"><strong>Failed</strong><span>${escapeHtml(ex.message)}</span></div>`;
      }
    }
    function renderList() {
      const q = (document.getElementById("blkFilter")?.value || "").trim().toLowerCase();
      let rows = items.slice();
      if (q) rows = rows.filter((d) => d.toLowerCase().includes(q));
      rows.sort((a, b) => a.localeCompare(b));
      if (!rows.length) {
        box.innerHTML = `<div class="empty"><strong>No domains</strong><span>${items.length ? "Nothing matches filter." : `${title}: empty.`}</span></div>`;
        return;
      }
      box.innerHTML = `
        <table class="data">
          <thead><tr><th>Domain</th><th></th></tr></thead>
          <tbody>
            ${rows.map((d) => `
              <tr>
                <td>${escapeHtml(d)}</td>
                <td class="actions"><button type="button" class="btn btn-danger btn-sm" data-del="${escapeHtml(d)}">Delete</button></td>
              </tr>`).join("")}
          </tbody>
        </table>`;
      box.querySelectorAll("[data-del]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const domain = btn.getAttribute("data-del");
          const ok = await confirmModal({
            title: "Delete domain?",
            text: `Remove ${domain} from ${isAllowed ? "Allowed" : "Blocked"}.`,
          });
          if (!ok) return;
          try {
            if (isAllowed) await DnsApi.deleteAllowed(domain);
            else await DnsApi.deleteBlocked(domain);
            toast("Deleted");
            await loadList();
          } catch (ex) { toast(ex.message, "error"); }
        });
      });
    }

    function openAddDomain() {
      const back = document.createElement("div");
      back.className = "modal-back";
      back.innerHTML = `
        <div class="modal">
          <h3>Add domain</h3>
          <div class="field"><label>Domain</label>
            <input id="domName" placeholder="ads.example.com" />
          </div>
          <div class="form-error" id="domErr"></div>
          <div class="modal-actions">
            <button type="button" class="btn btn-secondary" data-a="cancel">Cancel</button>
            <button type="button" class="btn" data-a="ok">Add</button>
          </div>
        </div>`;
      document.body.appendChild(back);
      back.addEventListener("click", async (e) => {
        const a = e.target.getAttribute("data-a");
        if (a === "cancel" || e.target === back) { back.remove(); return; }
        if (a !== "ok") return;
        const domain = back.querySelector("#domName").value.trim();
        if (!domain) { back.querySelector("#domErr").textContent = "Enter a domain"; return; }
        try {
          if (isAllowed) await DnsApi.addAllowed(domain);
          else await DnsApi.addBlocked(domain);
          toast("Added");
          back.remove();
          await loadList();
        } catch (ex) {
          back.querySelector("#domErr").textContent = ex.message;
        }
      });
    }

    document.getElementById("blkFilter").addEventListener("input", renderList);
    document.getElementById("btnBlkRefresh").addEventListener("click", loadList);
    document.getElementById("btnBlkAdd").addEventListener("click", openAddDomain);
    document.getElementById("btnBlkFlush").addEventListener("click", async () => {
      const ok = await confirmModal({
        title: "Flush list",
        text: `Delete ALL domains from ${isAllowed ? "Allowed" : "Blocked"}?`,
        dangerLabel: "Flush",
      });
      if (!ok) return;
      try {
        if (isAllowed) await DnsApi.flushAllowed();
        else await DnsApi.flushBlocked();
        toast("Flushed");
        await loadList();
      } catch (ex) { toast(ex.message, "error"); }
    });
    await loadList();
  }

  async function render() {
    const route = parseRoute();
    if (route.name === "login") {
      renderLogin();
      return;
    }
    const ok = await ensureAuth();
    if (!ok) {
      location.hash = "#/login";
      renderLogin();
      return;
    }
    if (route.name === "dashboard") await viewDashboard(route.type);
    else if (route.name === "records") await viewRecords(route.zone);
    else if (route.name === "forwarders") await viewForwarders();
    else if (route.name === "protocols") await viewProtocols();
    else if (route.name === "blocking") await viewBlocking(route.tab);
    else if (route.name === "querylog") await viewQueryLog();
    else if (route.name === "settings") await viewSettings(route.tab);
    else if (route.name === "zones") await viewZones();
    else await viewDashboard("LastHour");
  }

  async function boot() { await render(); }

  window.addEventListener("hashchange", () => { render(); });
  boot();
})();
