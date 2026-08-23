import os

templates = {
    "dashboard.html": """<!DOCTYPE html><html lang="fr"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>EduShop Admin — Tableau de bord</title>
<link rel="stylesheet" href="/static/css/app.css">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
</head><body>
<div class="layout">
  <aside class="sidebar">
    <div class="sidebar-logo">🛒 EduShop</div>
    <nav class="sidebar-nav">
      <a href="/admin" class="active">📊 Tableau de bord</a>
      <a href="/admin/products">📦 Produits</a>
      <a href="/admin/stock">🏪 Stock</a>
      <a href="/admin/inventory">📝 Inventaire & Audit</a>
      <a href="/admin/transfers">📋 Transferts Vendeurs</a>
      <a href="/admin/sellers">👥 Vendeurs</a>
      <a href="/admin/sales">💰 Ventes</a>
      <a href="/admin/suppliers">🚚 Fournisseurs</a>
    </nav>
    <div class="sidebar-footer">
      <span class="ws-status ws-disconnected" id="ws-badge">⚡ Hors ligne</span><br><br>
      <a href="#" onclick="openChangePasswordModal()" style="display:block;margin-bottom:8px;">🔒 Changer Mot de passe</a>
      <a href="#" onclick="logout()">🚪 Déconnexion</a>
    </div>
  </aside>
  <main class="main">
    <div class="page-header">
      <span class="page-title">📊 Tableau de bord</span>
      <span style="color:var(--text2);font-size:13px" id="last-update"></span>
    </div>
    <div class="kpi-grid" id="kpi-grid">
      <div class="kpi-card"><div class="kpi-label">Chiffre d'affaires (auj.)</div><div class="kpi-value" id="kpi-ca">—</div></div>
      <div class="kpi-card"><div class="kpi-label">Bénéfice net (auj.)</div><div class="kpi-value green" id="kpi-profit">—</div></div>
      <div class="kpi-card"><div class="kpi-label">Transactions (auj.)</div><div class="kpi-value" id="kpi-tx">—</div></div>
      <div class="kpi-card"><div class="kpi-label">Valeur du Stock Global</div><div class="kpi-value accent" id="kpi-stock-val">—</div></div>
    </div>
    <div class="card" style="margin-top:20px">
      <div class="card-title">Évolution des ventes (7 derniers jours)</div>
      <div style="height:280px;position:relative"><canvas id="salesChart"></canvas></div>
    </div>
    <div class="card" style="margin-top:20px">
      <div class="card-title">Performance des vendeurs aujourd'hui</div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Vendeur</th><th>Nb Ventes</th><th>Chiffre d'affaires</th><th>Bénéfice</th><th>Retours</th></tr></thead>
          <tbody id="sellers-summary-table"></tbody>
        </table>
      </div>
    </div>
  </main>
</div>

<!-- Modal: Change Password -->
<div class="modal-overlay" id="pwd-modal">
  <div class="modal">
    <h3>🔒 Changer le Mot de Passe Admin</h3>
    <p style="color:var(--text2);font-size:13px">Vous pouvez définir un mot de passe alphanumérique fort (ex: MonPass2026!).</p>
    <label>Mot de passe / PIN Actuel</label>
    <input type="password" id="cur-pwd" placeholder="Ex: 1234">
    <label>Nouveau Mot de passe</label>
    <input type="password" id="new-pwd" placeholder="Au moins 4 caractères">
    <label>Confirmer Nouveau Mot de passe</label>
    <input type="password" id="conf-pwd" placeholder="Retapez le mot de passe">
    <div id="pwd-error" class="error-box" style="display:none"></div>
    <div class="modal-actions">
      <button class="btn btn-secondary" onclick="closeChangePasswordModal()">Annuler</button>
      <button class="btn btn-primary" onclick="submitChangePassword()">Enregistrer</button>
    </div>
  </div>
</div>

<script src="/static/js/app.js"></script>
<script>
let chart = null;
async function init(){
  const today = new Date().toISOString().split("T")[0];
  const rep = await api("GET", `/api/sales/report?from_date=${today}`);
  if(rep){
    document.getElementById("kpi-ca").textContent = fmtDA(rep.total_revenue);
    document.getElementById("kpi-profit").textContent = fmtDA(rep.total_profit);
    document.getElementById("kpi-tx").textContent = rep.total_transactions;
    document.getElementById("sellers-summary-table").innerHTML = (rep.per_seller||[]).map(s=>`
      <tr>
        <td><b>${s.seller_name}</b></td>
        <td>${s.transaction_count}</td>
        <td style="color:var(--accent);font-weight:700">${fmtDA(s.revenue)}</td>
        <td style="color:var(--green)">${fmtDA(s.profit)}</td>
        <td style="color:var(--red)">${s.return_count}</td>
      </tr>
    `).join("") || "<tr><td colspan='5' style='text-align:center;color:var(--text2)'>Aucune vente aujourd'hui</td></tr>";
  }
  const stock = await api("GET", "/api/stock/global");
  if(stock){
    const val = stock.reduce((sum, item) => sum + (item.quantity * item.purchase_price), 0);
    document.getElementById("kpi-stock-val").textContent = fmtDA(val);
  }
  loadChart();
  document.getElementById("last-update").textContent = "Mis à jour à " + new Date().toLocaleTimeString();
}

async function loadChart(){
  const dTo = new Date(), dFrom = new Date(Date.now() - 6*86400000);
  const rep = await api("GET", `/api/sales/report?from_date=${dFrom.toISOString().split("T")[0]}&to_date=${dTo.toISOString().split("T")[0]}`);
  if(!rep) return;
  const ctx = document.getElementById("salesChart").getContext("2d");
  if(chart) chart.destroy();
  chart = new Chart(ctx, {
    type: "line",
    data: {
      labels: (rep.daily||[]).map(d=>d.date),
      datasets: [
        { label: "Chiffre d'affaires (DA)", data: (rep.daily||[]).map(d=>d.revenue), borderColor: "#f5a623", backgroundColor: "rgba(245,166,35,0.1)", fill: true, tension: 0.3 },
        { label: "Bénéfice Net (DA)", data: (rep.daily||[]).map(d=>d.profit), borderColor: "#27ae60", backgroundColor: "rgba(39,174,96,0.1)", fill: true, tension: 0.3 }
      ]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: "#e8e8f0" } } }, scales: { x: { ticks: { color: "#8888aa" } }, y: { ticks: { color: "#8888aa" } } } }
  });
}

function openChangePasswordModal(){
  document.getElementById("cur-pwd").value = "";
  document.getElementById("new-pwd").value = "";
  document.getElementById("conf-pwd").value = "";
  document.getElementById("pwd-error").style.display = "none";
  document.getElementById("pwd-modal").classList.add("open");
}
function closeChangePasswordModal(){ document.getElementById("pwd-modal").classList.remove("open"); }

async function submitChangePassword(){
  const cur = document.getElementById("cur-pwd").value;
  const nw = document.getElementById("new-pwd").value;
  const conf = document.getElementById("conf-pwd").value;
  const err = document.getElementById("pwd-error");
  if(!cur || !nw){ err.textContent = "Veuillez remplir tous les champs."; err.style.display = "block"; return; }
  if(nw !== conf){ err.textContent = "Les nouveaux mots de passe ne correspondent pas."; err.style.display = "block"; return; }
  if(nw.length < 4){ err.textContent = "Le mot de passe doit contenir au moins 4 caractères."; err.style.display = "block"; return; }

  const res = await api("POST", "/api/auth/change-password", { current_password: cur, new_password: nw });
  if(res){
    closeChangePasswordModal();
    showToast("Mot de passe modifié avec succès !");
  } else {
    err.textContent = "Mot de passe actuel incorrect.";
    err.style.display = "block";
  }
}

async function logout(){ await api("POST", "/api/auth/logout"); window.location.href = "/"; }

init();
connectWS("admin", 1, (e, d)=>{ init(); });
</script>
</body></html>""",

    "stock.html": """<!DOCTYPE html><html lang="fr"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stock Global — EduShop Admin</title>
<link rel="stylesheet" href="/static/css/app.css">
</head><body>
<div class="layout">
  <aside class="sidebar">
    <div class="sidebar-logo">🛒 EduShop</div>
    <nav class="sidebar-nav">
      <a href="/admin">📊 Tableau de bord</a>
      <a href="/admin/products">📦 Produits</a>
      <a href="/admin/stock" class="active">🏪 Stock</a>
      <a href="/admin/inventory">📝 Inventaire & Audit</a>
      <a href="/admin/transfers">📋 Transferts Vendeurs</a>
      <a href="/admin/sellers">👥 Vendeurs</a>
      <a href="/admin/sales">💰 Ventes</a>
      <a href="/admin/suppliers">🚚 Fournisseurs</a>
    </nav>
    <div class="sidebar-footer"><a href="#" onclick="logout()">🚪 Déconnexion</a></div>
  </aside>
  <main class="main">
    <div class="page-header">
      <span class="page-title">🏪 Stock Global</span>
      <div style="display:flex;gap:8px">
        <button class="btn btn-primary" onclick="openTransferModal()">➡️ Transférer au Vendeur</button>
      </div>
    </div>
    <div class="card">
      <div class="toolbar">
        <input class="search-box" id="search" placeholder="Rechercher par produit, code article..." oninput="filterStock()">
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Code Art.</th>
              <th>Désignation</th>
              <th>Catégorie</th>
              <th>Prix Achat</th>
              <th>Prix Vente</th>
              <th>Stock Global</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody id="stock-table"></tbody>
        </table>
      </div>
    </div>
  </main>
</div>

<!-- Modal: Add Stock -->
<div class="modal-overlay" id="add-modal">
  <div class="modal">
    <h3 id="add-modal-title">Ajouter du Stock</h3>
    <p style="color:var(--text2);font-size:13px" id="add-modal-subtitle"></p>
    <label>Quantité à ajouter *</label>
    <input type="number" id="add-qty" min="1" value="10">
    <div class="modal-actions">
      <button class="btn btn-secondary" onclick="closeAddModal()">Annuler</button>
      <button class="btn btn-primary" onclick="submitAddStock()">Ajouter au Stock</button>
    </div>
  </div>
</div>

<!-- Modal: Transfer Stock -->
<div class="modal-overlay" id="transfer-modal">
  <div class="modal">
    <h3>Transférer du Stock à un Vendeur</h3>
    <label>Produit *</label>
    <select id="t-product"></select>
    <label>Vendeur Destinataire *</label>
    <select id="t-seller"></select>
    <label>Quantité à transférer *</label>
    <input type="number" id="t-qty" min="1" value="5">
    <div id="t-error" class="error-box" style="display:none"></div>
    <div class="modal-actions">
      <button class="btn btn-secondary" onclick="closeTransferModal()">Annuler</button>
      <button class="btn btn-primary" onclick="submitTransfer()">Confirmer le Transfert</button>
    </div>
  </div>
</div>

<script src="/static/js/app.js"></script>
<script>
let stockList = [], selectedProdId = null;

async function init(){
  stockList = await api("GET", "/api/stock/global") || [];
  renderTable(stockList);
}

function renderTable(data){
  document.getElementById("stock-table").innerHTML = data.map(item => `
    <tr>
      <td><code>${item.code_article}</code></td>
      <td><b>${item.name_fr}</b></td>
      <td>${item.category || "—"}</td>
      <td>${fmtDA(item.purchase_price)}</td>
      <td style="color:var(--accent);font-weight:700">${fmtDA(item.sell_price)}</td>
      <td class="${item.quantity <= item.min_quantity ? "low-stock" : ""}"><b>${item.quantity}</b></td>
      <td style="display:flex;gap:6px">
        <button class="btn btn-secondary" style="padding:4px 8px;font-size:12px" onclick="openAddModal(${item.product_id}, '${item.name_fr.replace(/'/g,"\\\\'")}', ${item.quantity})">+ Ajouter</button>
      </td>
    </tr>
  `).join("");
}

function filterStock(){
  const q = document.getElementById("search").value.toLowerCase();
  renderTable(stockList.filter(s => s.name_fr.toLowerCase().includes(q) || s.code_article.toLowerCase().includes(q)));
}

function openAddModal(id, name, currentQty){
  selectedProdId = id;
  document.getElementById("add-modal-title").textContent = "Ajouter du Stock";
  document.getElementById("add-modal-subtitle").textContent = `Produit : ${name} (Stock actuel : ${currentQty})`;
  document.getElementById("add-qty").value = 10;
  document.getElementById("add-modal").classList.add("open");
}
function closeAddModal(){ document.getElementById("add-modal").classList.remove("open"); }

async function submitAddStock(){
  const qty = parseInt(document.getElementById("add-qty").value, 10);
  if(!qty || qty <= 0) return;
  const res = await api("POST", `/api/stock/global/${selectedProdId}/add`, { quantity: qty });
  if(res){
    closeAddModal();
    showToast("Stock ajouté avec succès !");
    init();
  }
}

async function openTransferModal(){
  const prods = await api("GET", "/api/products") || [];
  const sellers = await api("GET", "/api/sellers") || [];
  document.getElementById("t-product").innerHTML = prods.map(p=>`<option value="${p.id}">${p.name_fr} (Dispo: ${p.global_stock_quantity})</option>`).join("");
  document.getElementById("t-seller").innerHTML = sellers.map(s=>`<option value="${s.id}">${s.username}</option>`).join("");
  document.getElementById("t-qty").value = 5;
  document.getElementById("t-error").style.display = "none";
  document.getElementById("transfer-modal").classList.add("open");
}
function closeTransferModal(){ document.getElementById("transfer-modal").classList.remove("open"); }

async function submitTransfer(){
  const pid = parseInt(document.getElementById("t-product").value, 10);
  const sid = parseInt(document.getElementById("t-seller").value, 10);
  const qty = parseInt(document.getElementById("t-qty").value, 10);
  const err = document.getElementById("t-error");
  if(!qty || qty <= 0){ err.textContent = "Quantité invalide."; err.style.display = "block"; return; }
  const res = await api("POST", "/api/stock/transfer", { product_id: pid, seller_id: sid, quantity: qty });
  if(res){
    closeTransferModal();
    showToast("Transfert effectué avec succès !");
    init();
  } else {
    err.textContent = "Stock global insuffisant pour ce transfert.";
    err.style.display = "block";
  }
}

async function logout(){ await api("POST", "/api/auth/logout"); window.location.href = "/"; }

init();
</script>
</body></html>"""
}

dirs = [
    r"c:\Users\zinouuuuu\BILEL DESKTOP\EduShop_Cloud_Server\frontend\templates\admin",
    r"c:\Users\zinouuuuu\BILEL DESKTOP\EduShop_v2\frontend\templates\admin"
]

for d in dirs:
    for name, content in templates.items():
        fp = os.path.join(d, name)
        with open(fp, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Written clean {fp}")

print("Clean templates deployed successfully.")
