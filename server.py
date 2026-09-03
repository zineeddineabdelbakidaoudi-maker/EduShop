"""EduShop v2 — Main server entry point.
Run: python server.py
Then open: http://localhost:8000
"""
import os
import socket
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# ── Import models first so they are registered with Base ─────────────────────
import models  # noqa: F401

# ── Create all tables ─────────────────────────────────────────────────────────
from db.base import engine, Base
from sqlalchemy import text
try:
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        for col_sql in [
            "ALTER TABLE products ADD COLUMN fast_panel BOOLEAN DEFAULT FALSE",
            "ALTER TABLE products ADD COLUMN buyer VARCHAR DEFAULT 'Bilal'"
        ]:
            try:
                conn.execute(text(col_sql))
                conn.commit()
            except Exception:
                pass

        # Ensure barcode is NOT UNIQUE: allows same barcode across different gérants (Houari, Bilel, etc.)
        barcode_drop_sqls = [
            "DROP INDEX IF EXISTS ix_products_barcode",
            "ALTER TABLE products DROP CONSTRAINT IF EXISTS uq_products_barcode",
            "ALTER TABLE products DROP CONSTRAINT IF EXISTS products_barcode_key",
            """DO $$
            DECLARE r RECORD;
            BEGIN
                FOR r IN (
                    SELECT conname FROM pg_constraint 
                    WHERE conrelid = 'products'::regclass 
                    AND contype = 'u' 
                    AND conname LIKE '%barcode%'
                ) LOOP
                    EXECUTE 'ALTER TABLE products DROP CONSTRAINT IF EXISTS ' || quote_ident(r.conname);
                END LOOP;
            END $$;""",
            "CREATE INDEX IF NOT EXISTS ix_products_barcode ON products (barcode)"
        ]
        for b_sql in barcode_drop_sqls:
            try:
                conn.execute(text(b_sql))
                conn.commit()
            except Exception:
                pass
except Exception as e:
    print(f"[WARN] Table creation or auto-migration failed on primary engine ({e})")

# ── Import and run seed ───────────────────────────────────────────────────────
from db.seed import seed
try:
    seed()
except Exception as e:
    print(f"[WARN] Seed initialization failed: {e}")

# ── FastAPI app ───────────────────────────────────────────────────────────────
from fastapi.middleware.cors import CORSMiddleware
app = FastAPI(title="EduShop", version="2.0", docs_url="/api/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static files and templates ────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "frontend" / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "frontend" / "templates"))

# ── API routers ───────────────────────────────────────────────────────────────
from api.routers import auth, products, stock, sales, sellers, suppliers, sync, inventory
from api.websocket import router as ws_router

app.include_router(auth.router)
app.include_router(products.router)
app.include_router(stock.router)
app.include_router(sales.router)
app.include_router(sellers.router)
app.include_router(suppliers.router)
app.include_router(sync.router)
app.include_router(inventory.router)
app.include_router(ws_router)

# ── Frontend page routes ──────────────────────────────────────────────────────
@app.get("/downloads", response_class=HTMLResponse)
def downloads_page(request: Request):
    return templates.TemplateResponse(request=request, name="downloads.html")

@app.get("/download/caisse")
def download_caisse():
    p = BASE_DIR / "frontend" / "static" / "downloads" / "EduShop_Caisse.exe"
    if p.exists():
        return FileResponse(path=str(p), filename="EduShop_Caisse.exe", media_type="application/octet-stream")
    return RedirectResponse("/downloads")

@app.get("/download/admin")
def download_admin():
    p = BASE_DIR / "frontend" / "static" / "downloads" / "EduShop_Admin.exe"
    if p.exists():
        return FileResponse(path=str(p), filename="EduShop_Admin.exe", media_type="application/octet-stream")
    return RedirectResponse("/downloads")

@app.get("/download/pack")
def download_pack():
    p = BASE_DIR / "frontend" / "static" / "downloads" / "EduShop_Pack_Complet.zip"
    if p.exists():
        return FileResponse(path=str(p), filename="EduShop_Pack_Complet.zip", media_type="application/zip")
    return RedirectResponse("/downloads")

@app.get("/", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="admin/dashboard.html")

@app.get("/admin/products", response_class=HTMLResponse)
def admin_products(request: Request):
    return templates.TemplateResponse(request=request, name="admin/products.html")

@app.get("/admin/stock", response_class=HTMLResponse)
def admin_stock(request: Request):
    return templates.TemplateResponse(request=request, name="admin/stock.html")

@app.get("/admin/inventory", response_class=HTMLResponse)
def admin_inventory(request: Request):
    return templates.TemplateResponse(request=request, name="admin/inventory.html")

@app.get("/admin/sellers", response_class=HTMLResponse)
def admin_sellers(request: Request):
    return templates.TemplateResponse(request=request, name="admin/sellers.html")

@app.get("/admin/sales", response_class=HTMLResponse)
def admin_sales(request: Request):
    return templates.TemplateResponse(request=request, name="admin/sales.html")

@app.get("/admin/suppliers", response_class=HTMLResponse)
def admin_suppliers(request: Request):
    return templates.TemplateResponse(request=request, name="admin/suppliers.html")

@app.get("/admin/transfers", response_class=HTMLResponse)
def admin_transfers(request: Request):
    return templates.TemplateResponse(request=request, name="admin/transfers.html")

@app.get("/seller", response_class=HTMLResponse)
def seller_pos(request: Request):
    return templates.TemplateResponse(request=request, name="seller/pos.html")

@app.get("/seller/sales", response_class=HTMLResponse)
def seller_sales(request: Request):
    return templates.TemplateResponse(request=request, name="seller/sales.html")

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
