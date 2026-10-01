async function api(path, options = {}) {
  const opts = {
    credentials: "same-origin",
    headers: { ...(options.headers || {}) },
    ...options,
  };
  const isForm = typeof FormData !== "undefined" && opts.body instanceof FormData;
  if (!isForm) {
    opts.headers = { "Content-Type": "application/json", ...opts.headers };
  }
  if (opts.body && typeof opts.body === "object" && !isForm) {
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, opts);
  let data = null;
  const text = await res.text();
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
  if (!res.ok) {
    let msg = (data && (data.detail || data.errorMessage)) || `HTTP ${res.status}`;
    if (msg && typeof msg === "object") {
      msg = msg.message || msg.code || JSON.stringify(msg);
    }
    const err = new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

window.DnsApi = {
  login: (user, password) => api("/api/auth/login", { method: "POST", body: { user, password } }),
  logout: () => api("/api/auth/logout", { method: "POST", body: {} }),
  me: () => api("/api/auth/me"),
  changePassword: (currentPassword, newPassword, totp) => api("/api/auth/change-password", {
    method: "POST",
    body: { currentPassword, newPassword, totp: totp || undefined },
  }),
  zones: (q = "") => api("/api/zones" + q),
  createZone: (body) => api("/api/zones", { method: "POST", body }),
  deleteZone: (name) => api("/api/zones/" + encodeURIComponent(name), { method: "DELETE" }),
  records: (zone) => api("/api/zones/" + encodeURIComponent(zone) + "/records"),
  addRecord: (zone, body) => api("/api/zones/" + encodeURIComponent(zone) + "/records", { method: "POST", body }),
  deleteRecord: (zone, body) => api("/api/zones/" + encodeURIComponent(zone) + "/records", {
    method: "DELETE",
    body,
  }),
  settings: () => api("/api/settings"),
  saveSettings: (body) => api("/api/settings", { method: "PUT", body }),
  forwarders: () => api("/api/forwarders"),
  saveForwarders: (items) => api("/api/forwarders", { method: "PUT", body: { items } }),
  testForwarders: (items) => api("/api/forwarders/test", { method: "POST", body: { items } }),
  uploadDnsTlsCert: (file, password) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("password", password || "");
    return api("/api/settings/dns-tls-cert", { method: "POST", body: fd });
  },
  uploadDnsTlsPem: (keyFile, chainFile, keyPassword) => {
    const fd = new FormData();
    fd.append("key", keyFile);
    fd.append("chain", chainFile);
    fd.append("key_password", keyPassword || "");
    return api("/api/settings/dns-tls-pem", { method: "POST", body: fd });
  },
  panelTls: () => api("/api/settings/panel-tls"),
  uploadPanelTls: (keyFile, certFile) => {
    const fd = new FormData();
    fd.append("key", keyFile);
    fd.append("cert", certFile);
    return api("/api/settings/panel-tls", { method: "POST", body: fd });
  },
  savePanelHttpsPort: (port, httpEnabled = true) => api("/api/settings/panel-tls/https-port", {
    method: "PUT",
    body: { port: Number(port), httpEnabled: !!httpEnabled },
  }),
  blocking: () => api("/api/blocking"),
  saveBlocking: (body) => api("/api/blocking", { method: "PUT", body }),
  forceUpdateBlockLists: () => api("/api/blocking/force-update-lists", { method: "POST", body: {} }),
  seedBlocklistPresets: () => api("/api/blocking/seed-presets", { method: "POST", body: {} }),
  temporaryDisableBlocking: (minutes) => api("/api/blocking/temporary-disable", { method: "POST", body: { minutes } }),
  allowedList: () => api("/api/blocking/allowed"),
  addAllowed: (domain) => api("/api/blocking/allowed", { method: "POST", body: { domain } }),
  deleteAllowed: (domain) => api("/api/blocking/allowed/" + encodeURIComponent(domain), { method: "DELETE" }),
  flushAllowed: () => api("/api/blocking/allowed/flush", { method: "POST", body: {} }),
  importAllowed: (domains) => api("/api/blocking/allowed/import", { method: "POST", body: { domains } }),
  blockedList: () => api("/api/blocking/blocked"),
  addBlocked: (domain) => api("/api/blocking/blocked", { method: "POST", body: { domain } }),
  deleteBlocked: (domain) => api("/api/blocking/blocked/" + encodeURIComponent(domain), { method: "DELETE" }),
  flushBlocked: () => api("/api/blocking/blocked/flush", { method: "POST", body: {} }),
  importBlocked: (domains) => api("/api/blocking/blocked/import", { method: "POST", body: { domains } }),
  dashboard: (type = "LastHour") => api("/api/dashboard?type=" + encodeURIComponent(type)),
  blockingLog: (params = {}) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v === undefined || v === null || v === "") return;
      q.set(k, String(v));
    });
    const s = q.toString();
    return api("/api/blocking/log" + (s ? "?" + s : ""));
  },
  ensureBlockingLog: () => api("/api/blocking/log/ensure", { method: "POST", body: {} }),
  installBlockingLog: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return api("/api/blocking/log/install", { method: "POST", body: fd });
  },
};
