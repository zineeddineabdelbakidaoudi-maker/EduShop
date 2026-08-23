# EduShop v2 — Point of Sale System

A web-based POS and inventory management system. One Python process on the Admin PC serves the entire application — no installation needed on Seller PCs.

## Quick Start

### 1. Install (Admin PC only, once)
```bash
pip install -r requirements.txt
```

### 2. Run
```bash
python server.py
```

The terminal will display your LAN IP automatically:
```
  Admin UI  : http://10.x.x.x:8000/admin
  Vendeur 1 : http://10.x.x.x:8000/seller
  API Docs  : http://10.x.x.x:8000/api/docs
```

### 3. Connect Seller PCs
On each Seller PC, open any browser and go to:
```
http://<ADMIN_IP>:8000/seller
```
No installation. No file sharing. No configuration.

### 4. Default Accounts
| Username | PIN  | Role   |
|----------|------|--------|
| admin    | 1234 | Admin  |
| thel     | 0000 | Seller |
| seller2  | 0000 | Seller |
| seller3  | 0000 | Seller |
| seller4  | 0000 | Seller |

## How It Works

```
Admin PC: python server.py
          └── SQLite database (edushop.db)
          └── FastAPI REST API on port 8000
          └── WebSocket for live updates
          └── Serves HTML to all browsers

Seller PC: Browser → http://10.x.x.x:8000/seller
Admin UI:  Browser → http://10.x.x.x:8000/admin
```

## Workflow

1. **Admin** creates products and sets prices
2. **Admin** transfers stock to specific sellers (Stock page → Transférer au Vendeur)
3. **Seller** logs in via browser, sees only their allocated stock
4. **Seller** scans barcodes or searches products, builds cart, processes payment
5. **Admin dashboard** updates in real time via WebSocket

## Switch to PostgreSQL

Change one line in `db/base.py`:
```python
# SQLite (default)
DATABASE_URL = "sqlite:///./edushop.db"

# PostgreSQL
DATABASE_URL = "postgresql://user:password@localhost/edushop"
```
No model changes needed.

## Run Tests
```bash
pytest tests/ -v
```

## Firewall (Windows)
If Seller PCs cannot connect, allow port 8000 in Windows Firewall:
```
Windows Defender Firewall → Advanced Settings → Inbound Rules → New Rule
→ Port → TCP 8000 → Allow → All profiles → Name: EduShop
```
