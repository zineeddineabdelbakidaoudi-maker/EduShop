"""EduShop v2 — Main server entry point.
Run: python server.py
Then open: http://localhost:8000
"""
import os
import socket
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# ── Import models first so they are registered with Base ─────────────────────
import models  # noqa: F401

# ── Create all tables ─────────────────────────────────────────────────────────
from db.base import engine, Base
Base.metadata.create_all(bind=engine)

# ── Import and run seed ───────────────────────────────────────────────────────
from db.seed import seed
seed()

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="EduShop", version="2.0", docs_url="/api/docs")

# ── Static files and templates ────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "frontend" / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "frontend" / "templates"))

# ── API routers ───────────────────────────────────────────────────────────────
from api.routers import auth, products, stock, sales, sellers, suppliers, sync
from api.websocket import router as ws_router

app.include_router(auth.router)
app.include_router(products.router)
app.include_router(stock.router)
app.include_router(sales.router)
app.include_router(sellers.router)
app.include_router(suppliers.router)
app.include_router(sync.router)
app.include_router(ws_router)

# ── Frontend page routes ──────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    return templates.TemplateResponse("admin/dashboard.html", {"request": request})

@app.get("/admin/products", response_class=HTMLResponse)
def admin_products(request: Request):
    return templates.TemplateResponse("admin/products.html", {"request": request})

@app.get("/admin/stock", response_class=HTMLResponse)
def admin_stock(request: Request):
    return templates.TemplateResponse("admin/stock.html", {"request": request})

@app.get("/admin/sellers", response_class=HTMLResponse)
def admin_sellers(request: Request):
    return templates.TemplateResponse("admin/sellers.html", {"request": request})

@app.get("/admin/sales", response_class=HTMLResponse)
def admin_sales(request: Request):
    return templates.TemplateResponse("admin/sales.html", {"request": request})

@app.get("/admin/suppliers", response_class=HTMLResponse)
def admin_suppliers(request: Request):
    return templates.TemplateResponse("admin/suppliers.html", {"request": request})

@app.get("/seller", response_class=HTMLResponse)
def seller_pos(request: Request):
    return templates.TemplateResponse("seller/pos.html", {"request": request})

@app.get("/seller/sales", response_class=HTMLResponse)
def seller_sales(request: Request):
    return templates.TemplateResponse("seller/sales.html", {"request": request})

# ── Startup banner ────────────────────────────────────────────────────────────
def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"

if __name__ == "__main__":
    lan_ip = get_lan_ip()
    print("\n" + "="*55)
    print("  [+]  EduShop v2 -- Serveur demarre !")
    print("="*55)
    print(f"  Admin UI  : http://{lan_ip}:8000/admin")
    print(f"  Vendeur 1 : http://{lan_ip}:8000/seller")
    print(f"  API Docs  : http://{lan_ip}:8000/api/docs")
    print("="*55)
    print(f"  Comptes de démonstration:")
    print(f"    Admin  : admin  / PIN 1234")
    print(f"    Vendeur: thel   / PIN 0000")
    print("="*55 + "\n")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
