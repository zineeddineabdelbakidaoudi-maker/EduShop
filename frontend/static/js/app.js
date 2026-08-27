// ── Shared API helper ──────────────────────────────────────────────────────────
async function api(method, url, body = null) {
  const opts = { method, headers: { "Content-Type": "application/json" }, credentials: "include" };
  if (body) opts.body = JSON.stringify(body);
  try {
    const res = await fetch(url, opts);
    if (res.status === 401) { window.location.href = "/"; return null; }
    if (res.status === 204) return true;
    const data = await res.json();
    if (!res.ok) {
      showToast(data.detail || "Erreur serveur", "error");
      return null;
    }
    return data;
  } catch (e) {
    showToast("Erreur réseau: " + e.message, "error");
    return null;
  }
}

// ── Toast notifications ─────────────────────────────────────────────────────────
function showToast(msg, type = "success") {
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    container.style.cssText = "position:fixed;bottom:20px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:8px";
    document.body.appendChild(container);
  }
  const toast = document.createElement("div");
  const bg = type === "error" ? "#e74c3c" : type === "warn" ? "#f5a623" : "#27ae60";
  toast.style.cssText = `background:${bg};color:#fff;padding:12px 20px;border-radius:10px;font-size:14px;font-weight:600;box-shadow:0 4px 20px rgba(0,0,0,.4);animation:fadeIn .3s ease`;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

// ── Format helpers ──────────────────────────────────────────────────────────────
function fmtDA(n) { return (n || 0).toLocaleString("fr-DZ", { minimumFractionDigits: 2 }) + " DA"; }
function fmtDate(d) { return new Date(d).toLocaleString("fr-FR"); }

// ── Offline queue for seller sales ─────────────────────────────────────────────
const QUEUE_KEY = "edushop_sale_queue";
function getQueue() { try { return JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]"); } catch { return []; } }
function saveQueue(q) { localStorage.setItem(QUEUE_KEY, JSON.stringify(q)); }
async function flushQueue() {
  const q = getQueue();
  if (!q.length) return;
  const remaining = [];
  for (const item of q) {
    const r = await api("POST", "/api/sales", item);
    if (!r) remaining.push(item);
  }
  saveQueue(remaining);
// ── Theme Switcher ───────────────────────────────────────────────────────────────
function initTheme() {
  const saved = localStorage.getItem("edushop_theme") || "dark";
  document.documentElement.setAttribute("data-theme", saved);
  updateThemeButton(saved);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "dark";
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("edushop_theme", next);
  updateThemeButton(next);
}

function updateThemeButton(theme) {
  const btns = document.querySelectorAll(".theme-toggle-btn");
  btns.forEach(btn => {
    btn.innerHTML = theme === "light" ? "🌙 Mode Sombre" : "☀️ Mode Clair (Lumineux)";
  });
}

// Initialize theme immediately
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initTheme);
} else {
  initTheme();
}
