import re

sample_lines = [
    "FOURNITURES GENERALES DU CENTRE SARL",
    "12 Rue des Freres Bouadou, Bordj Bou Arreridj, Algerie",
    "Client: Librairie Mega Papeterie FACTURE N FAC-2026-0158 Date: 23/08/2026",
    "Code Code-barres Designation Categorie P.Achat Qte P.Vente",
    "ART-006 3000000000006 Surligneur Stabilo Boss Jaune Papeterie 15,00 DA 50 25,00 DA",
    "ART-007 3000000000007 Crayon HB Staedtler Papeterie 8,00 DA 120 14,00 DA",
    "ART-008 3000000000008 Taille-crayon Simple Accessoires 10,00 DA 70 18,00 DA",
    "ART-009 3000000000009 Gomme Blanche Milan Papeterie 6,00 DA 90 11,00 DA",
    "ART-010 3000000000010 Cahier 100 Pages Petit Format Cahiers 25,00 DA 60 45,00 DA",
    "ART-011 3000000000011 Classeur A4 Rigide Classeurs 120,00 DA 20 210,00 DA",
    "ART-012 3000000000012 Pochette Plastique A4 (x100) Accessoires 300,00 DA 15 480,00 DA",
    "ART-013 3000000000013 Stylo Bille Bleu Bic Papeterie 5,00 DA 200 10,00 DA",
    "ART-030 3000000000030 Papier A4 Ramette 500f Papeterie 550,00 DA 40 850,00 DA",
    "ART-031 3000000000031 Calculatrice Scientifique Casio Accessoires 1800,00 DA 10 2600,00 DA",
    "ART-035 3000000000035 Cartable Scolaire Standard Sacs & Cartables 900,00 DA 12 1500,00 DA",
    "TOTAL HT: 91 500.00 DA",
    "TVA (19%): 17 385.00 DA",
    "TOTAL TTC: 108 885.00 DA",
    "Merci pour votre confiance."
]

def parse_lines(lines, default_margin=25.0):
    products = []
    in_table = False
    
    for raw in lines:
        line = raw.strip()
        upper = line.upper()
        
        if "CODE" in upper and ("DESIGNATION" in upper or "P.ACHAT" in upper or "CATEGORIE" in upper):
            in_table = True
            continue
            
        if "TOTAL HT" in upper or "TOTAL TTC" in upper or "TVA" in upper or "MERCI POUR" in upper:
            in_table = False
            break
            
        if not in_table and not re.match(r'^(ART[-\s]?\d+|[A-Z0-9]{3,8}\b)', line, re.IGNORECASE):
            continue
            
        clean = re.sub(r'\b(DA|DZD|€)\b', '', line, flags=re.IGNORECASE).strip()
        
        code = ""
        m_code = re.match(r'^(ART[-\s]?\d+|[A-Z]{2,4}[-\s]?\d+)\b', clean, re.IGNORECASE)
        if m_code:
            code = m_code.group(1).replace(" ", "-").upper()
            clean = clean[len(m_code.group(0)):].strip()
            
        barcode = ""
        m_bc = re.match(r'^(\d{8,14})\b', clean)
        if m_bc:
            barcode = m_bc.group(1)
            clean = clean[len(m_bc.group(0)):].strip()
            
        pa, qty, pv = 0.0, 1, 0.0
        m_num3 = re.search(r'(\d+[\.,]?\d*)\s+(\d+)\s+(\d+[\.,]?\d*)$', clean)
        if m_num3:
            pa = float(m_num3.group(1).replace(',', '.'))
            qty = int(m_num3.group(2))
            pv = float(m_num3.group(3).replace(',', '.'))
            clean = clean[:m_num3.start()].strip()
        else:
            m_num2 = re.search(r'(\d+[\.,]?\d*)\s+(\d+)$', clean)
            if m_num2:
                pa = float(m_num2.group(1).replace(',', '.'))
                qty = int(m_num2.group(2))
                pv = round(pa * (1 + default_margin / 100), 2)
                clean = clean[:m_num2.start()].strip()
                
        categories = ["Papeterie", "Accessoires", "Cahiers", "Classeurs", "Sacs & Cartables", "Fournitures", "Bureau", "Livres"]
        cat = "Papeterie"
        for c in categories:
            if re.search(rf'\b{re.escape(c)}\b', clean, re.IGNORECASE):
                cat = c
                clean = re.sub(rf'\b{re.escape(c)}\b', '', clean, flags=re.IGNORECASE).strip()
                break
                
        designation = clean.strip(" :-|;")
        if not designation and code:
            designation = f"Article {code}"
            
        if designation and (pa > 0 or code):
            products.append({
                "code": code or f"ART-{len(products)+1:03d}",
                "barcode": barcode,
                "name": designation,
                "category": cat,
                "pa": pa,
                "qty": qty,
                "pv": pv
            })
            
    return products

results = parse_lines(sample_lines)
print(f"Detected {len(results)} items:")
for p in results:
    print(f" -> {p['code']} | {p['barcode']} | {p['name']} | {p['category']} | PA: {p['pa']:.2f} DA | Qte: {p['qty']} | PV: {p['pv']:.2f} DA")
