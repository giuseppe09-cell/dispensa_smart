"""
Dispensa Smart - App Streamlit per la gestione intelligente della dispensa
Stile: Nordic Midnight
Autore: Senior Python Developer (v2)
"""

import streamlit as st
import requests
import hashlib
import re
from collections import Counter
from datetime import datetime, date, timedelta
from PIL import Image
import io
import os
from supabase import create_client, Client
import extra_streamlit_components as stx

# Tentativo di import di pyzbar (richiede zbar installato sul sistema)
try:
    from pyzbar.pyzbar import decode as zbar_decode
    PYZBAR_AVAILABLE = True
except Exception:
    PYZBAR_AVAILABLE = False

# Supporto HEIC (formato di default iPhone). Se non disponibile, l'app continua a funzionare
# con JPG/PNG ma rifiuta HEIC con messaggio chiaro.
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_SUPPORT = True
except Exception:
    HEIC_SUPPORT = False

# OCR per leggere la data di scadenza dalle foto. Richiede tesseract installato sul sistema:
#   brew install tesseract tesseract-lang
# e il pacchetto python: pip3 install pytesseract --break-system-packages
try:
    import pytesseract
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

# =====================================================================
# CONFIGURAZIONE GENERALE
# =====================================================================
st.set_page_config(
    page_title="Dispensa Smart",
    page_icon="🍽️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Costanti
PASSWORD = "Giuseppe2026.!"
OFF_API = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"

# Telegram: i valori vengono letti dai Secrets (locale → .streamlit/secrets.toml,
# cloud → Settings → Secrets della tua app). Se mancano, le notifiche vengono
# semplicemente disattivate senza errori.
try:
    TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")
except (KeyError, FileNotFoundError):
    TELEGRAM_TOKEN = ""
    TELEGRAM_CHAT_ID = ""

# Token persistente di login: hash della password (NON la password in chiaro)
AUTH_TOKEN = hashlib.sha256(f"{PASSWORD}-dispensa-smart-salt".encode()).hexdigest()[:24]

# Mappa emoji per categorie/parole chiave
EMOJI_MAP = {
    "latte": "🥛", "yogurt": "🥛", "formaggio": "🧀", "burro": "🧈",
    "uova": "🥚", "uovo": "🥚", "pane": "🍞", "pasta": "🍝",
    "riso": "🍚", "pizza": "🍕", "carne": "🥩", "pollo": "🍗",
    "pesce": "🐟", "tonno": "🐟", "salmone": "🐟", "gambero": "🦐",
    "mela": "🍎", "banana": "🍌", "arancia": "🍊", "limone": "🍋",
    "uva": "🍇", "fragola": "🍓", "anguria": "🍉", "pesca": "🍑",
    "pera": "🍐", "ananas": "🍍", "kiwi": "🥝", "pomodoro": "🍅",
    "carota": "🥕", "patata": "🥔", "cipolla": "🧅", "aglio": "🧄",
    "peperone": "🫑", "broccolo": "🥦", "insalata": "🥗", "lattuga": "🥬",
    "olio": "🫒", "vino": "🍷", "birra": "🍺", "acqua": "💧",
    "caffè": "☕", "caffe": "☕", "tè": "🍵", "the": "🍵",
    "biscotti": "🍪", "cioccolato": "🍫", "gelato": "🍦",
    "miele": "🍯", "zucchero": "🍬", "sale": "🧂", "farina": "🌾",
    "basilico": "🌿", "rosmarino": "🌿", "prezzemolo": "🌿",
    "menta": "🌱", "salvia": "🌿", "origano": "🌿",
    "noci": "🥜", "mandorle": "🥜", "popcorn": "🍿",
    "ketchup": "🥫", "salsa": "🥫", "fagioli": "🫘",
}

CATEGORIE = ["Dispensa", "Freezer", "Frigo", "Erbe Aromatiche", "Frutta"]

# Mappa per riconoscimento automatico della MACROCATEGORIA dal nome del prodotto.
# La logica trova il keyword più LUNGO che appare nel nome, così "fagioli borlotti"
# matcha "Fagioli" (parola chiave più specifica vince in caso di conflitto).
MACRO_KEYWORDS = {
    # Legumi
    "Fagioli": ["fagioli", "borlotti", "cannellini", "fagiolo", "azuki"],
    "Lenticchie": ["lenticchie", "lenticchia"],
    "Ceci": ["ceci"],
    "Piselli": ["piselli"],
    "Fave": ["fave"],
    # Cereali e affini
    "Pasta": ["pasta", "spaghetti", "penne", "fusilli", "rigatoni", "linguine",
              "tagliatelle", "lasagne", "maccheroni", "farfalle", "tortellini",
              "ravioli", "gnocchi", "orecchiette", "trofie"],
    "Riso": ["riso", "carnaroli", "arborio", "basmati"],
    "Cous Cous": ["cous cous", "couscous"],
    "Farina": ["farina"],
    # Conserve di pomodoro
    "Pomodoro (conserva)": ["pelati", "passata", "polpa di pomodoro", "datterini",
                            "pomodorini in scatola"],
    # Pesce in scatola
    "Tonno": ["tonno"],
    "Sgombro": ["sgombro"],
    "Pesce in scatola": ["sardine", "alici", "acciughe", "filetti di sgombro"],
    # Sughi e salse
    "Pesto": ["pesto"],
    "Sugo pronto": ["sugo", "ragù", "ragu", "pomarola", "arrabbiata", "amatriciana"],
    "Salse": ["ketchup", "maionese", "senape", "salsa rosa", "barbecue"],
    # Base cucina
    "Olio": ["olio"],
    "Aceto": ["aceto"],
    "Sale": ["sale"],
    "Zucchero": ["zucchero"],
    # Latticini
    "Latte": ["latte"],
    "Yogurt": ["yogurt"],
    "Formaggio": ["formaggio", "parmigiano", "grana", "mozzarella", "stracchino",
                  "ricotta", "crescenza", "gorgonzola", "pecorino", "asiago",
                  "fontina", "scamorza", "philadelphia"],
    "Burro": ["burro"],
    "Panna": ["panna"],
    # Uova e proteine fresche
    "Uova": ["uova", "uovo"],
    "Pollo": ["pollo"],
    "Manzo": ["manzo", "carne di manzo", "macinato"],
    "Maiale": ["maiale"],
    "Salumi": ["prosciutto", "salame", "mortadella", "speck", "bresaola", "pancetta",
               "coppa", "guanciale"],
    "Wurstel": ["wurstel", "würstel"],
    # Pane e snack
    "Pane": ["pane", "panini", "piadina", "tortilla", "wrap"],
    "Cracker / Grissini": ["cracker", "grissini", "fette biscottate", "taralli"],
    "Biscotti": ["biscotti", "biscotto"],
    "Cioccolato": ["cioccolato", "cioccolata", "nutella", "cacao"],
    "Snack salati": ["patatine", "popcorn", "tarallucci"],
    # Bevande
    "Caffè": ["caffè", "caffe"],
    "Tè / Tisane": ["tè", "the ", "tisana", "infuso"],
    "Acqua": ["acqua"],
    "Vino": ["vino"],
    "Birra": ["birra"],
    "Succhi / Bibite": ["succo", "spremuta", "coca cola", "coca-cola", "fanta",
                        "sprite", "nettare", "gassosa", "aranciata", "chinotto"],
    # Frutta
    "Mele": ["mela", "mele"],
    "Banane": ["banana", "banane"],
    "Arance": ["arancia", "arance"],
    "Limoni": ["limone", "limoni"],
    "Pere": ["pera", "pere"],
    "Uva": ["uva"],
    "Fragole": ["fragola", "fragole"],
    "Pesche": ["pesca", "pesche"],
    "Kiwi": ["kiwi"],
    "Ananas": ["ananas"],
    # Verdure
    "Patate": ["patate", "patata"],
    "Carote": ["carote", "carota"],
    "Cipolle": ["cipolla", "cipolle"],
    "Aglio": ["aglio"],
    "Insalata": ["insalata", "lattuga", "rucola", "valeriana", "songino"],
    "Pomodori freschi": ["pomodori freschi", "pomodorini freschi", "ciliegino"],
    "Zucchine": ["zucchine", "zucchina"],
    "Melanzane": ["melanzane", "melanzana"],
    # Erbe aromatiche
    "Basilico": ["basilico"],
    "Rosmarino": ["rosmarino"],
    "Prezzemolo": ["prezzemolo"],
    "Menta": ["menta"],
    "Salvia": ["salvia"],
    "Origano": ["origano"],
    "Timo": ["timo"],
    "Alloro": ["alloro"],
    # Dolci e dispensa varia
    "Miele": ["miele"],
    "Marmellata": ["marmellata", "confettura"],
    "Gelato": ["gelato"],
    "Surgelati": ["surgelat", "minestrone", "spinaci surgelati"],
}


def guess_macro(nome: str, categoria_off: str = "") -> str:
    """
    Riconosce la macrocategoria a partire dal nome del prodotto (e in subordine
    dalla categoria OFF). Restituisce stringa vuota se non trova match.
    """
    if not nome and not categoria_off:
        return ""
    target = f"{nome} {categoria_off}".lower()
    best = ""
    best_len = 0
    for macro, keywords in MACRO_KEYWORDS.items():
        for kw in keywords:
            kw_low = kw.lower()
            if kw_low in target and len(kw_low) > best_len:
                best = macro
                best_len = len(kw_low)
    return best

# =====================================================================
# CSS PERSONALIZZATO - NORDIC MIDNIGHT
# =====================================================================
NORDIC_CSS = """
<style>
    /* Palette Nordic Midnight */
    :root {
        --nm-bg: #0F1419;
        --nm-surface: #1A2332;
        --nm-surface-2: #243447;
        --nm-accent: #88C0D0;
        --nm-accent-2: #5E81AC;
        --nm-text: #ECEFF4;
        --nm-text-muted: #D8DEE9;
        --nm-green: #A3BE8C;
        --nm-orange: #EBCB8B;
        --nm-red: #BF616A;
    }

    /* Sfondo app */
    .stApp {
        background: linear-gradient(180deg, #0F1419 0%, #1A2332 100%);
        color: var(--nm-text);
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background-color: var(--nm-surface) !important;
        border-right: 1px solid var(--nm-surface-2);
    }
    [data-testid="stSidebar"] * {
        color: var(--nm-text) !important;
    }

    /* Header animato */
    .nm-header {
        font-family: 'Helvetica Neue', sans-serif;
        font-size: 3.2rem;
        font-weight: 700;
        text-align: center;
        background: linear-gradient(90deg, #88C0D0, #5E81AC, #B48EAD);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        animation: fadeIn 2s ease-in-out forwards;
        opacity: 0;
        margin-bottom: 0.2rem;
        letter-spacing: 2px;
    }
    .nm-subtitle {
        text-align: center;
        color: var(--nm-text-muted);
        font-size: 1rem;
        animation: fadeIn 2s ease-in-out forwards;
        opacity: 0;
        margin-bottom: 1.5rem;
    }

    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(-10px); }
        to   { opacity: 1; transform: translateY(0); }
    }

    /* Login card */
    .nm-login-card {
        max-width: 420px;
        margin: 5rem auto;
        padding: 2rem;
        background: var(--nm-surface);
        border: 1px solid var(--nm-surface-2);
        border-radius: 16px;
        box-shadow: 0 10px 40px rgba(0,0,0,0.45);
        animation: fadeIn 1.2s ease-in-out forwards;
        opacity: 0;
    }

    /* Pulsanti */
    .stButton > button {
        background: linear-gradient(135deg, #5E81AC, #88C0D0);
        color: #0F1419;
        font-weight: 600;
        border: none;
        border-radius: 10px;
        padding: 0.6rem 1.2rem;
        transition: all 0.25s ease;
    }
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(136, 192, 208, 0.35);
        color: #0F1419;
    }

    /* Input */
    .stTextInput input, .stNumberInput input, .stDateInput input, .stSelectbox div[data-baseweb="select"] {
        background-color: var(--nm-surface-2) !important;
        color: var(--nm-text) !important;
        border-radius: 8px !important;
    }

    /* Tabelle: badge colorati */
    .badge-green  { color:#0F1419; background:#A3BE8C; padding:4px 10px; border-radius:8px; font-weight:600; }
    .badge-orange { color:#0F1419; background:#EBCB8B; padding:4px 10px; border-radius:8px; font-weight:600; }
    .badge-red    { color:#ECEFF4; background:#BF616A; padding:4px 10px; border-radius:8px; font-weight:600; }

    /* Card prodotto */
    .nm-card {
        background: var(--nm-surface);
        border: 1px solid var(--nm-surface-2);
        border-radius: 12px;
        padding: 1rem;
        margin-bottom: 0.8rem;
    }

    /* Tabelle HTML */
    table.nm-table {
        width: 100%;
        border-collapse: collapse;
        background: var(--nm-surface);
        border-radius: 10px;
        overflow: hidden;
    }
    table.nm-table th {
        background: var(--nm-surface-2);
        color: var(--nm-accent);
        text-align: left;
        padding: 10px;
        font-size: 0.9rem;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    table.nm-table td {
        padding: 10px;
        border-top: 1px solid #2c3a4d;
        color: var(--nm-text);
    }
    .row-green  td { background-color: rgba(163,190,140,0.10); }
    .row-orange td { background-color: rgba(235,203,139,0.12); }
    .row-red    td { background-color: rgba(191, 97,106,0.18); }
</style>
"""

st.markdown(NORDIC_CSS, unsafe_allow_html=True)


# =====================================================================
# DATABASE — Supabase (Postgres ospitato in cloud)
# =====================================================================
@st.cache_resource
def get_supabase() -> Client:
    """
    Crea (una sola volta per sessione) il client Supabase usando le credenziali
    salvate nei Secrets di Streamlit. In locale serve il file .streamlit/secrets.toml
    con le chiavi SUPABASE_URL e SUPABASE_KEY. Su Streamlit Cloud le imposti dal
    pannello Settings → Secrets della tua app.
    """
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
    except (KeyError, FileNotFoundError):
        st.error(
            "❌ Credenziali Supabase non configurate. "
            "Imposta SUPABASE_URL e SUPABASE_KEY in `.streamlit/secrets.toml` (locale) "
            "o in Settings → Secrets (Streamlit Cloud)."
        )
        st.stop()
    return create_client(url, key)


def init_db():
    """
    Su Supabase la tabella `prodotti` è già stata creata via SQL durante il setup.
    Qui eseguiamo solo la pulizia automatica dei duplicati storici.
    """
    db_consolidate_duplicates()


def db_insert(barcode, nome, categoria, quantita, data_scadenza, foto_url, macro=""):
    """
    Inserisce un prodotto. Se esiste già una riga con lo stesso nome (case-insensitive
    e trimmed), stessa categoria e stessa data di scadenza, incrementa la quantità
    invece di creare un duplicato. Restituisce:
        {"merged": bool, "new_quantita": int, "row_id": int}
    """
    sb = get_supabase()
    nome_norm = nome.strip().lower()
    nome_clean = nome.strip()

    # Cerca candidati che potrebbero essere lo stesso prodotto (filtra per categoria + scadenza)
    query = sb.table("prodotti").select("*").eq("categoria", categoria)
    if data_scadenza:
        query = query.eq("data_scadenza", data_scadenza)
    else:
        query = query.is_("data_scadenza", "null")
    candidates = (query.execute().data) or []

    # Confronto case-insensitive trimmed in Python (Supabase non ha LOWER+TRIM nativo)
    existing = None
    for row in candidates:
        if (row.get("nome") or "").strip().lower() == nome_norm:
            existing = row
            break

    if existing:
        new_qty = int(existing["quantita"]) + int(quantita)
        update_data = {"quantita": new_qty}
        # Se l'esistente è privo di info utili e tu le hai, completale
        if barcode and not existing.get("barcode"):
            update_data["barcode"] = barcode
        if foto_url and not existing.get("foto_url"):
            update_data["foto_url"] = foto_url
        if macro and not existing.get("macro"):
            update_data["macro"] = macro
        sb.table("prodotti").update(update_data).eq("id", existing["id"]).execute()
        return {"merged": True, "new_quantita": new_qty, "row_id": existing["id"]}

    # Nuova riga
    payload = {
        "barcode": barcode or None,
        "nome": nome_clean,
        "categoria": categoria,
        "macro": macro or "",
        "quantita": int(quantita),
        "data_scadenza": data_scadenza if data_scadenza else None,
        "foto_url": foto_url or None,
    }
    inserted = sb.table("prodotti").insert(payload).execute()
    new_id = inserted.data[0]["id"] if inserted.data else None
    return {"merged": False, "new_quantita": int(quantita), "row_id": new_id}


def db_update_qty(prod_id, qty):
    get_supabase().table("prodotti").update({"quantita": int(qty)}).eq("id", prod_id).execute()


def db_consolidate_duplicates():
    """
    Trova righe con stesso nome (case-insensitive trimmed), stessa categoria e stessa
    data di scadenza, e le fonde in un'unica riga sommando le quantità.
    Restituisce il numero di gruppi consolidati.
    """
    sb = get_supabase()
    rows = (sb.table("prodotti").select("*").execute().data) or []

    # Raggruppa per chiave normalizzata
    groups = {}
    for r in rows:
        key = (
            (r.get("nome") or "").strip().lower(),
            r.get("categoria") or "",
            r.get("data_scadenza") or "",
        )
        groups.setdefault(key, []).append(r)

    consolidated = 0
    for key, group in groups.items():
        if len(group) <= 1:
            continue
        # Mantieni la riga con id più basso (la più vecchia)
        group.sort(key=lambda x: x["id"])
        keep = group[0]
        merge = group[1:]
        total_qty = sum(int(r["quantita"]) for r in group)

        update_data = {"quantita": total_qty}
        # Riempi campi vuoti dai duplicati
        for field in ("barcode", "foto_url", "macro"):
            if not keep.get(field):
                for m in merge:
                    if m.get(field):
                        update_data[field] = m[field]
                        break

        sb.table("prodotti").update(update_data).eq("id", keep["id"]).execute()

        # Cancella i duplicati
        for m in merge:
            sb.table("prodotti").delete().eq("id", m["id"]).execute()

        consolidated += 1
    return consolidated


def db_update_product(prod_id, nome=None, macro=None, quantita=None, data_scadenza=None):
    """
    Aggiorna uno o più campi di un prodotto. Passa None ai campi che NON vuoi cambiare.
    """
    update_data = {}
    if nome is not None:
        update_data["nome"] = nome
    if macro is not None:
        update_data["macro"] = macro
    if quantita is not None:
        update_data["quantita"] = int(quantita)
    if data_scadenza is not None:
        update_data["data_scadenza"] = data_scadenza
    if update_data:
        get_supabase().table("prodotti").update(update_data).eq("id", prod_id).execute()


def db_consume_one(prod_id):
    """
    Consuma una unità del prodotto. Se la quantità arriva a 0, elimina la riga.
    Restituisce (eliminato: bool, nome_prodotto: str).
    """
    sb = get_supabase()
    res = sb.table("prodotti").select("nome, quantita").eq("id", prod_id).execute()
    if not res.data:
        return False, ""
    row = res.data[0]
    nome, qty = row["nome"], int(row["quantita"])
    if qty <= 1:
        sb.table("prodotti").delete().eq("id", prod_id).execute()
        return True, nome
    sb.table("prodotti").update({"quantita": qty - 1}).eq("id", prod_id).execute()
    return False, nome


def db_delete(prod_id):
    get_supabase().table("prodotti").delete().eq("id", prod_id).execute()


def db_fetch_by_categoria(categoria=None, search=None):
    query = get_supabase().table("prodotti").select("*")
    if categoria:
        query = query.eq("categoria", categoria)
    if search:
        # ILIKE è case-insensitive in Postgres
        query = query.ilike("nome", f"%{search}%")
    # Ordina per scadenza ascendente (None vanno in fondo)
    res = query.order("data_scadenza", desc=False, nullsfirst=False).execute()
    return res.data or []


def db_fetch_expiring(days=10):
    today = date.today()
    limit = (today + timedelta(days=days)).isoformat()
    res = (
        get_supabase()
        .table("prodotti")
        .select("*")
        .lte("data_scadenza", limit)
        .gt("quantita", 0)
        .execute()
    )
    return res.data or []


def db_count_metrics():
    """
    Restituisce (totale, rossi, arancio): conteggi per la dashboard Home.
    Lo facciamo in Python perché Supabase non ha funzioni di aggregazione complesse
    senza scrivere RPC custom.
    """
    sb = get_supabase()
    rows = (
        sb.table("prodotti")
        .select("quantita, data_scadenza")
        .gt("quantita", 0)
        .execute()
        .data
    ) or []
    today = date.today()
    totale = len(rows)
    rossi = 0
    arancio = 0
    for r in rows:
        s = r.get("data_scadenza")
        if not s:
            continue
        try:
            d = datetime.strptime(s, "%Y-%m-%d").date()
        except Exception:
            continue
        gg = (d - today).days
        if gg <= 10:
            rossi += 1
        elif gg <= 30:
            arancio += 1
    return totale, rossi, arancio


def db_fetch_all_active():
    """Tutti i prodotti con quantità > 0, ordinati per scadenza."""
    res = (
        get_supabase()
        .table("prodotti")
        .select("*")
        .gt("quantita", 0)
        .order("data_scadenza", desc=False, nullsfirst=False)
        .execute()
    )
    return res.data or []


# =====================================================================
# UTILITY
# =====================================================================
def get_emoji(nome: str) -> str:
    if not nome:
        return "📦"
    n = nome.lower()
    for k, v in EMOJI_MAP.items():
        if k in n:
            return v
    return "📦"

def days_to_expiry(scadenza_str: str):
    if not scadenza_str:
        return None
    try:
        d = datetime.strptime(scadenza_str, "%Y-%m-%d").date()
        return (d - date.today()).days
    except Exception:
        return None

def expiry_class(scadenza_str: str):
    g = days_to_expiry(scadenza_str)
    if g is None:
        return "row-green", "badge-green", "—"
    if g <= 10:
        return "row-red", "badge-red", f"{g} gg"
    if g <= 30:
        return "row-orange", "badge-orange", f"{g} gg"
    return "row-green", "badge-green", f"{g} gg"


# =====================================================================
# OPEN FOOD FACTS
# =====================================================================
def fetch_off_product(barcode: str):
    """
    Interroga Open Food Facts. Tenta più endpoint perché:
    - v2 è il più aggiornato ma a volte restituisce vuoto per prodotti vecchi
    - v0 è la versione storica e ha un catalogo più ampio
    Usa un User-Agent esplicito (richiesto dalla policy di OFF).
    """
    headers = {
        "User-Agent": "DispensaSmart/1.0 (uso personale - giuseppe.pagano09@gmail.com)"
    }
    endpoints = [
        f"https://world.openfoodfacts.org/api/v2/product/{barcode}.json",
        f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json",
        f"https://it.openfoodfacts.org/api/v2/product/{barcode}.json",
        f"https://it.openfoodfacts.org/api/v0/product/{barcode}.json",
    ]

    for url in endpoints:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json()
            # OFF restituisce status=1 quando il prodotto è trovato
            if data.get("status") != 1:
                continue
            p = data.get("product") or {}
            if not p:
                continue
            # Prova diverse chiavi per il nome (priorità all'italiano)
            nome = (
                p.get("product_name_it")
                or p.get("product_name")
                or p.get("generic_name_it")
                or p.get("generic_name")
                or p.get("abbreviated_product_name")
                or p.get("brands")
                or ""
            ).strip() or "Prodotto sconosciuto"

            categoria = (p.get("categories") or "").strip()
            if categoria:
                # OFF restituisce le categorie separate da virgola: prendi la più specifica (ultima)
                parts = [c.strip() for c in categoria.split(",") if c.strip()]
                categoria = parts[-1] if parts else ""

            immagine = (
                p.get("image_url")
                or p.get("image_front_url")
                or p.get("image_front_small_url")
                or ""
            )
            return {"nome": nome, "categoria": categoria, "foto_url": immagine}
        except Exception:
            continue
    return None


# =====================================================================
# BARCODE DECODER
# =====================================================================
def extract_expiry_date(image_bytes):
    """
    Esegue OCR sull'immagine cercando una data di scadenza.
    Riconosce formati: DD/MM/YYYY, DD.MM.YYYY, DD-MM-YYYY, DD/MM/YY, YYYY-MM-DD,
    e abbreviazioni con mesi testuali (es. "12 GEN 2026").
    Restituisce un oggetto date o None.
    """
    if not OCR_AVAILABLE:
        return None, "OCR non installato. Vedi messaggio sotto."
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        # Prova ITA + ENG; se ITA non installato, fallback automatico solo a ENG
        try:
            text = pytesseract.image_to_string(img, lang="ita+eng")
        except Exception:
            text = pytesseract.image_to_string(img, lang="eng")

        text_clean = text.replace("\n", " ").upper()

        candidates = []

        # Mesi testuali italiani/inglesi → numero
        mesi = {
            "GEN": 1, "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAG": 5, "MAY": 5,
            "GIU": 6, "JUN": 6, "LUG": 7, "JUL": 7, "AGO": 8, "AUG": 8,
            "SET": 9, "SEP": 9, "OTT": 10, "OCT": 10, "NOV": 11, "DIC": 12, "DEC": 12,
        }

        # Pattern: DD MMM YYYY (es. "12 GEN 2026" o "12-GEN-26")
        for m in re.finditer(r"(\d{1,2})[\s/.\-]*([A-Z]{3})[A-Z]*[\s/.\-]*(\d{2,4})", text_clean):
            d, mese_txt, y = m.groups()
            if mese_txt in mesi:
                try:
                    d, y = int(d), int(y)
                    if y < 100:
                        y += 2000
                    candidates.append(date(y, mesi[mese_txt], d))
                except Exception:
                    pass

        # Pattern: DD/MM/YYYY o varianti
        for m in re.finditer(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", text_clean):
            d, mn, y = m.groups()
            try:
                d, mn, y = int(d), int(mn), int(y)
                if y < 100:
                    y += 2000
                candidates.append(date(y, mn, d))
            except Exception:
                pass

        # Pattern: YYYY-MM-DD
        for m in re.finditer(r"(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})", text_clean):
            y, mn, d = m.groups()
            try:
                candidates.append(date(int(y), int(mn), int(d)))
            except Exception:
                pass

        # Filtra date plausibili (da oggi -1 anno fino a +10 anni)
        today = date.today()
        valid = [d for d in candidates if today - timedelta(days=365) <= d <= today + timedelta(days=365 * 10)]

        if not valid:
            return None, f"Nessuna data riconosciuta. Testo letto: {text_clean[:120]}..."
        # Restituisce la più lontana nel futuro (di solito è la scadenza, non il lotto)
        return max(valid), None
    except Exception as e:
        return None, f"Errore OCR: {e}"


def decode_barcode(image_bytes) -> str:
    if not PYZBAR_AVAILABLE:
        return ""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        # Converte in RGB per compatibilità (HEIC, RGBA, P, ecc.)
        if img.mode != "RGB":
            img = img.convert("RGB")
        codes = zbar_decode(img)
        if codes:
            return codes[0].data.decode("utf-8")
    except Exception as e:
        # Errore tipico: HEIC senza pillow-heif installato
        if "cannot identify image" in str(e).lower() and not HEIC_SUPPORT:
            return "__HEIC_ERROR__"
    return ""


# =====================================================================
# TELEGRAM
# =====================================================================
def telegram_send(text: str) -> bool:
    # Se le credenziali non sono configurate, salta silenziosamente
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
        r = requests.post(url, data=payload, timeout=8)
        return r.status_code == 200
    except Exception:
        return False

def notify_expiring_on_startup():
    if st.session_state.get("telegram_sent"):
        return
    expiring = db_fetch_expiring(days=10)
    if expiring:
        msg_lines = ["<b>⚠️ Dispensa Smart – Prodotti in scadenza (≤10 gg)</b>", ""]
        for p in expiring:
            g = days_to_expiry(p["data_scadenza"])
            emoji = get_emoji(p["nome"])
            msg_lines.append(f"{emoji} <b>{p['nome']}</b> – {p['categoria']} – {g} gg")
        telegram_send("\n".join(msg_lines))
    st.session_state["telegram_sent"] = True


# =====================================================================
# LOGIN PERSISTENTE — combina query param + COOKIE HTTP
# Su iOS PWA i query param a volte spariscono al riavvio; il cookie persiste
# nel local storage del browser per molti giorni anche da web app.
# =====================================================================
COOKIE_NAME = "dispensa_auth"
COOKIE_DAYS = 365   # quanto a lungo restare loggati


@st.cache_resource
def get_cookie_manager():
    """Singleton del CookieManager (deve esistere uno solo per sessione)."""
    return stx.CookieManager(key="dispensa_cookie_mgr")


def check_persistent_auth():
    """
    Verifica autenticazione da:
      1. session_state (più rapido, sessione corrente)
      2. query param ?auth=...
      3. cookie HTTP "dispensa_auth"
    """
    if st.session_state.get("authenticated"):
        return True

    # 1) URL query param (modo veloce, funziona su desktop e Safari mobile)
    token = st.query_params.get("auth")
    if token == AUTH_TOKEN:
        st.session_state["authenticated"] = True
        return True

    # 2) Cookie HTTP (modo affidabile, sopravvive anche su iOS PWA)
    cm = get_cookie_manager()
    cookie_token = cm.get(cookie=COOKIE_NAME)
    if cookie_token == AUTH_TOKEN:
        st.session_state["authenticated"] = True
        return True

    return False


def login_screen():
    st.markdown('<div class="nm-header">Dispensa Smart</div>', unsafe_allow_html=True)
    st.markdown('<div class="nm-subtitle">🔐 Accesso Riservato</div>', unsafe_allow_html=True)
    st.markdown('<div class="nm-login-card">', unsafe_allow_html=True)

    cm = get_cookie_manager()

    with st.form("login_form", clear_on_submit=False):
        pwd = st.text_input("Password", type="password", placeholder="Inserisci la password")
        submit = st.form_submit_button("Accedi")
        if submit:
            if pwd == PASSWORD:
                st.session_state["authenticated"] = True
                # Imposta il token sia nell'URL (per browser desktop) sia come cookie
                # (per Safari/iPhone in modalità web app)
                st.query_params["auth"] = AUTH_TOKEN
                cm.set(
                    COOKIE_NAME,
                    AUTH_TOKEN,
                    expires_at=datetime.now() + timedelta(days=COOKIE_DAYS),
                )
                st.success("Accesso effettuato! Da ora resterai loggato anche da iPhone.")
                st.rerun()
            else:
                st.error("Password errata.")
    st.markdown("</div>", unsafe_allow_html=True)


# =====================================================================
# RENDER ELENCO PRODOTTI — raggruppamento per MACROCATEGORIA
# =====================================================================
def _render_single_product(p):
    """
    Renderizza una singola card prodotto su UNA SOLA RIGA, senza emoji
    (l'emoji compare solo nell'header della macrocategoria, sopra).
    Layout: nome + quantità · scadenza · badge giorni · 🍽️ · 🗑️
    """
    row_cls, badge_cls, badge_label = expiry_class(p["data_scadenza"])
    scad = p["data_scadenza"] or "—"
    qty = int(p["quantita"])
    qty_str = f" <span style='color:#88C0D0'>×{qty}</span>" if qty > 1 else ""

    with st.container(border=True):
        # Solo 3 colonne: info testuale + Usa + Cestino — niente emoji per riga
        cols = st.columns([5, 1, 0.8])

        with cols[0]:
            st.markdown(
                f"<div style='line-height:1.55;padding-top:0.35rem'>"
                f"<b>{p['nome']}</b>{qty_str} "
                f"<span style='color:#88C0D0;font-size:0.88rem'>· 📅 {scad}</span> "
                f"<span class='{badge_cls}'>{badge_label}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

        if cols[1].button(
            "🍽️", key=f"consume_{p['id']}", use_container_width=True,
            help="Consuma una unità. Se arrivi a 0, il prodotto sparisce dall'elenco.",
        ):
            eliminato, nome = db_consume_one(p["id"])
            if eliminato:
                st.toast(f"✅ {nome} consumato e rimosso.", icon="🍽️")
            else:
                st.toast(f"✅ Una unità di {nome} consumata.", icon="🍽️")
            st.rerun()

        if cols[2].button(
            "🗑️", key=f"del_{p['id']}", use_container_width=True,
            help="Elimina dall'inventario",
        ):
            db_delete(p["id"])
            st.rerun()


def _brand_from_name(nome: str) -> str:
    """Estrae la 'marca' come prima parola significativa del nome (per il conteggio)."""
    if not nome:
        return ""
    parts = nome.strip().split()
    return parts[0].lower() if parts else ""


def render_products_table(rows):
    if not rows:
        st.info("Nessun prodotto in questa categoria. Aggiungine uno!")
        return

    # Raggruppa per macrocategoria. I prodotti senza macro finiscono in "Altri".
    gruppi = {}
    for r in rows:
        macro = (r["macro"] or "").strip() if "macro" in r.keys() else ""
        if not macro:
            macro = "Altri"
        gruppi.setdefault(macro, []).append(r)

    # Ordina i gruppi: prima quelli con scadenza più imminente al loro interno
    def gruppo_urgenza(items):
        gg = [days_to_expiry(p["data_scadenza"]) for p in items]
        gg = [g for g in gg if g is not None]
        return min(gg) if gg else 9999

    sorted_macros = sorted(gruppi.items(), key=lambda kv: (gruppo_urgenza(kv[1]), kv[0]))

    # Se c'è un solo gruppo (o solo "Altri"), renderizza piatto senza header
    if len(gruppi) == 1 and "Altri" in gruppi:
        for p in rows:
            _render_single_product(p)
        _render_manual_edit_panel(rows)
        return

    # Render con sezioni per macrocategoria
    for macro_name, products in sorted_macros:
        n_confezioni = sum(p["quantita"] for p in products)
        n_marche = len(set(_brand_from_name(p["nome"]) for p in products if p["nome"]))
        # Emoji rappresentativa: usa quella del primo prodotto
        macro_emoji = get_emoji(products[0]["nome"]) if products else "📦"

        # Trova lo stato peggiore del gruppo per colorare l'header
        worst_days = gruppo_urgenza(products)
        if worst_days <= 10:
            header_style = "background:rgba(191,97,106,0.18);border-left:4px solid #BF616A;"
        elif worst_days <= 30:
            header_style = "background:rgba(235,203,139,0.18);border-left:4px solid #EBCB8B;"
        else:
            header_style = "background:rgba(163,190,140,0.12);border-left:4px solid #A3BE8C;"

        marche_str = f" · {n_marche} marche diverse" if n_marche > 1 else ""
        st.markdown(
            f"<div style='{header_style}padding:0.7rem 1rem;border-radius:8px;"
            f"margin:1rem 0 0.5rem 0;font-size:1.15rem;font-weight:600'>"
            f"{macro_emoji} {macro_name} "
            f"<span style='font-weight:400;font-size:0.9rem;color:#D8DEE9'>"
            f"({len(products)} righe · {n_confezioni} confezioni{marche_str})</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        for p in products:
            _render_single_product(p)

    _render_manual_edit_panel(rows)


def _render_manual_edit_panel(rows):
    """
    Pannello per modificare TUTTI i campi di un prodotto: nome, macrocategoria,
    data di scadenza e quantità. Utile per correggere errori di inserimento.
    """
    with st.expander("✏️ Modifica prodotti (nome, scadenza, macro, quantità)"):
        st.caption(
            "Correggi qualsiasi campo: ti sei sbagliato a inserire la data, "
            "vuoi rinominare o assegnare una macrocategoria diversa? Modifica e clicca 💾."
        )
        for p in rows:
            # Parse della data corrente: se assente o malformata, usa oggi come default
            try:
                cur_date = (
                    datetime.strptime(p["data_scadenza"], "%Y-%m-%d").date()
                    if p["data_scadenza"] else date.today()
                )
            except Exception:
                cur_date = date.today()

            with st.container(border=True):
                st.markdown(
                    f"{get_emoji(p['nome'])} **{p['nome']}** — "
                    f"<span style='color:#88C0D0'>scad. attuale: {p['data_scadenza'] or '—'}</span>",
                    unsafe_allow_html=True,
                )
                c1, c2 = st.columns(2)
                new_nome = c1.text_input(
                    "Nome", value=p["nome"], key=f"e_nome_{p['id']}"
                )
                new_macro = c2.text_input(
                    "Macrocategoria",
                    value=(p["macro"] if "macro" in p.keys() and p["macro"] else ""),
                    key=f"e_macro_{p['id']}",
                )
                c3, c4, c5 = st.columns([2, 1.5, 1.2])
                new_date = c3.date_input(
                    "📅 Nuova data di scadenza",
                    value=cur_date,
                    key=f"e_date_{p['id']}",
                )
                new_qty = c4.number_input(
                    "Quantità",
                    min_value=0,
                    value=int(p["quantita"]),
                    key=f"e_qty_{p['id']}",
                )
                c5.markdown("<div style='padding-top:1.7rem'></div>", unsafe_allow_html=True)
                if c5.button("💾 Salva", key=f"e_save_{p['id']}", use_container_width=True):
                    db_update_product(
                        p["id"],
                        nome=new_nome.strip() or p["nome"],
                        macro=new_macro.strip(),
                        quantita=int(new_qty),
                        data_scadenza=new_date.isoformat(),
                    )
                    st.toast(f"✅ {new_nome} aggiornato", icon="✏️")
                    st.rerun()


# =====================================================================
# FORM AGGIUNTA PRODOTTO (con OCR opzionale per la scadenza)
# =====================================================================
def add_product_form(default_categoria: str, prefill: dict = None):
    prefill = prefill or {}
    form_key = f"add_form_{default_categoria}_{prefill.get('barcode','')}"

    # ---- OCR scadenza (FUORI dal form per poter aggiornare lo state) ----
    suggested_date_key = f"suggested_date_{default_categoria}"
    if suggested_date_key not in st.session_state:
        st.session_state[suggested_date_key] = date.today() + timedelta(days=30)

    with st.expander("📅 Leggi automaticamente la data di scadenza dalla confezione (OCR)"):
        st.caption(
            "Carica o scatta una foto **ravvicinata e ben illuminata** della parte della confezione "
            "dove c'è la data di scadenza. L'app proverà a leggerla."
        )
        ocr_img = st.file_uploader(
            "Foto della scadenza",
            key=f"ocr_uploader_{default_categoria}",
            label_visibility="collapsed",
        )
        if ocr_img is not None:
            if not OCR_AVAILABLE:
                st.warning(
                    "⚠️ OCR non installato. Esegui nel Terminale:\n"
                    "`brew install tesseract tesseract-lang` poi "
                    "`pip3 install pytesseract --break-system-packages`."
                )
            else:
                with st.spinner("Leggo la data..."):
                    found, msg = extract_expiry_date(ocr_img.getvalue())
                if found:
                    st.session_state[suggested_date_key] = found
                    st.success(f"✅ Data trovata: **{found.strftime('%d/%m/%Y')}** — verifica e salva qui sotto.")
                else:
                    st.warning(f"Non sono riuscito a leggere la data. {msg or ''}")

    # ---- FORM vero e proprio ----
    # Pre-calcola il suggerimento di macrocategoria dal nome (per pre-popolarlo)
    suggested_macro = guess_macro(prefill.get("nome", ""), prefill.get("categoria_off", ""))

    with st.form(form_key, clear_on_submit=True):
        st.subheader("➕ Aggiungi prodotto")
        c1, c2 = st.columns(2)
        nome = c1.text_input("Nome prodotto", value=prefill.get("nome", ""))
        categoria = c2.selectbox(
            "Categoria",
            CATEGORIE,
            index=CATEGORIE.index(default_categoria) if default_categoria in CATEGORIE else 0,
        )

        # Campo Macrocategoria con suggerimento automatico ed editabile
        macro = st.text_input(
            "Macrocategoria (es. Fagioli, Pasta, Pesto)",
            value=suggested_macro,
            help="Permette di raggruppare prodotti simili di marche diverse. "
                 "Lascia vuoto se non vuoi raggruppamento. "
                 "Verrà suggerita automaticamente in base al nome."
        )

        c3, c4 = st.columns(2)
        quantita = c3.number_input("Quantità", min_value=1, value=int(prefill.get("quantita", 1)))
        scadenza = c4.date_input("Data scadenza", value=st.session_state[suggested_date_key])
        barcode = st.text_input("Barcode (opzionale)", value=prefill.get("barcode", ""))
        foto_url = st.text_input("URL foto (opzionale)", value=prefill.get("foto_url", ""))
        st.caption(
            "💡 Stessa marca, scadenze diverse? Salva ogni confezione separatamente: l'app crea righe distinte e "
            "ti farà scegliere quale consumare per prima."
        )
        submit = st.form_submit_button("Salva prodotto")
        if submit:
            if not nome.strip():
                st.error("Il nome è obbligatorio.")
            else:
                result = db_insert(
                    barcode, nome.strip(), categoria, int(quantita),
                    scadenza.isoformat(), foto_url, macro=macro.strip()
                )
                if result["merged"]:
                    st.success(
                        f"{get_emoji(nome)} **{nome}** con scadenza {scadenza.strftime('%d/%m/%Y')} "
                        f"esisteva già: quantità aggiornata a **{result['new_quantita']}**."
                    )
                else:
                    st.success(f"{get_emoji(nome)} **{nome}** aggiunto a {categoria}.")
                # Reset del suggerimento OCR
                st.session_state[suggested_date_key] = date.today() + timedelta(days=30)
                st.rerun()


# =====================================================================
# SEZIONI
# =====================================================================
def section_home(search):
    st.markdown("### 🏠 Visione generale")
    totale, rossi, arancio = db_count_metrics()

    c1, c2, c3 = st.columns(3)
    c1.metric("📦 Totale prodotti", totale)
    c2.metric("🔴 In scadenza ≤10gg", rossi)
    c3.metric("🟠 In scadenza 11–30gg", arancio)

    # Pulsante per consolidare duplicati a richiesta
    if st.button("🧹 Consolida duplicati", help="Fonde righe con stesso nome+categoria+scadenza in un'unica riga"):
        n = db_consolidate_duplicates()
        if n > 0:
            st.success(f"✅ Consolidati {n} gruppi di duplicati.")
        else:
            st.info("Nessun duplicato trovato.")
        st.rerun()

    st.markdown("#### Tutti i prodotti")
    rows = []
    for cat in CATEGORIE:
        rows.extend(db_fetch_by_categoria(cat, search))
    render_products_table(rows)


def section_categoria(nome_cat: str, icona: str, search):
    st.markdown(f"### {icona} {nome_cat}")
    rows = db_fetch_by_categoria(nome_cat, search)
    render_products_table(rows)
    st.divider()
    add_product_form(nome_cat)


def section_ricettario():
    st.markdown("### 👨‍🍳 Ricettario Smart")
    st.write("Genera un prompt da copiare in un'IA (Gemini/Claude/ChatGPT) basato sui tuoi ingredienti disponibili, con priorità a quelli in scadenza.")

    rows = db_fetch_all_active()

    if not rows:
        st.info("Nessun ingrediente disponibile. Aggiungi prodotti alle tue categorie!")
        return

    rossi, arancio, verdi = [], [], []
    for p in rows:
        g = days_to_expiry(p["data_scadenza"])
        emoji = get_emoji(p["nome"])
        item = f"{emoji} {p['nome']} ({p['quantita']})"
        if g is None or g > 30:
            verdi.append(item)
        elif g <= 10:
            rossi.append(item)
        else:
            arancio.append(item)

    st.markdown("**Ingredienti disponibili:**")
    if rossi:
        st.markdown("🔴 **Da consumare subito:** " + ", ".join(rossi))
    if arancio:
        st.markdown("🟠 **Da consumare a breve:** " + ", ".join(arancio))
    if verdi:
        st.markdown("🟢 **Disponibili:** " + ", ".join(verdi))

    if st.button("✨ Genera Suggerimento Ricetta"):
        prompt = (
            "Sei uno chef esperto. Suggeriscimi 3 ricette creative e pratiche utilizzando "
            "PRIORITARIAMENTE gli ingredienti in scadenza imminente. "
            "Indica per ognuna: nome, ingredienti, tempo di preparazione e procedimento.\n\n"
            f"🔴 INGREDIENTI URGENTI (da consumare entro 10 giorni): {', '.join(rossi) if rossi else 'nessuno'}\n"
            f"🟠 INGREDIENTI A BREVE (11-30 giorni): {', '.join(arancio) if arancio else 'nessuno'}\n"
            f"🟢 ALTRI INGREDIENTI DISPONIBILI: {', '.join(verdi) if verdi else 'nessuno'}\n\n"
            "Suggerisci ricette tipiche italiane quando possibile."
        )
        st.success("✅ Prompt pronto! Copialo e incollalo nella tua IA preferita.")
        st.code(prompt, language="markdown")


# =====================================================================
# MAIN APP
# =====================================================================
def main_app():
    # Header animato
    st.markdown('<div class="nm-header">Dispensa Smart</div>', unsafe_allow_html=True)
    st.markdown('<div class="nm-subtitle">La tua dispensa, sempre sotto controllo ❄️</div>', unsafe_allow_html=True)

    # Notifica Telegram all'avvio
    notify_expiring_on_startup()

    # Top bar: ricerca + barcode
    top_left, top_right = st.columns([3, 1])
    with top_left:
        search = st.text_input("🔍 Cerca prodotto", placeholder="Es. latte, pasta, mela...", key="search_input")
    with top_right:
        st.write("")
        st.write("")
        scan_active = st.toggle("📷 SCANSIONA BARCODE", key="scan_toggle")

    # Sezione scansione
    if scan_active:
        st.markdown("#### Acquisisci il codice a barre")

        img_bytes = None

        # OPZIONE 1: Fotocamera diretta dal browser
        st.markdown("**📷 Opzione 1 — Fotocamera del browser**")
        st.caption("Funziona da Mac. Su iPhone richiede HTTPS (es. ngrok).")
        cam = st.camera_input("Scatta foto", key="cam_input", label_visibility="collapsed")
        if cam is not None:
            img_bytes = cam.getvalue()

        st.markdown("---")

        # OPZIONE 2: Upload da galleria / fotocamera nativa iPhone
        st.markdown("**🖼️ Opzione 2 — Carica una foto**")
        st.caption(
            "Tocca il pulsante: l'iPhone ti farà scegliere tra **Libreria foto**, "
            "**Scatta foto** o **Sfoglia**. Funziona sempre, anche senza HTTPS."
        )
        # Nessun filtro su 'type' per evitare problemi con HEIC (formato standard iPhone)
        uploaded = st.file_uploader(
            "Carica foto del barcode",
            key="upload_input",
            label_visibility="collapsed",
            accept_multiple_files=False,
        )
        if uploaded is not None:
            img_bytes = uploaded.getvalue()
            try:
                st.image(img_bytes, width=240)
            except Exception:
                st.info("Anteprima non disponibile per questo formato, ma proverò comunque a leggerlo.")

        if img_bytes:
            if not PYZBAR_AVAILABLE:
                st.warning("⚠️ Libreria `pyzbar` non disponibile. Installa: `pip install pyzbar` e libreria di sistema `zbar`.")
            else:
                code = decode_barcode(img_bytes)
                if code == "__HEIC_ERROR__":
                    st.error(
                        "⚠️ Formato HEIC non supportato. Installa il pacchetto: "
                        "`pip3 install pillow-heif --break-system-packages` "
                        "oppure imposta l'iPhone su Impostazioni → Fotocamera → Formati → **Più compatibile** (salva come JPG)."
                    )
                    code = ""
                if code:
                    st.success(f"✅ Barcode rilevato: **{code}**")
                    info = fetch_off_product(code)
                    if info:
                        emoji = get_emoji(info["nome"])
                        st.markdown(f"### {emoji} {info['nome']}")
                        if info.get("foto_url"):
                            st.image(info["foto_url"], width=180)
                        st.caption(f"Categoria OFF: {info.get('categoria') or '—'}")
                        # Form precompilato
                        cat_default = "Dispensa"
                        if info.get("categoria"):
                            ic = info["categoria"].lower()
                            if "frozen" in ic or "surgel" in ic:
                                cat_default = "Freezer"
                            elif "dairy" in ic or "latt" in ic or "yogurt" in ic:
                                cat_default = "Frigo"
                            elif "fruit" in ic or "frut" in ic:
                                cat_default = "Frutta"
                            elif "herb" in ic or "erba" in ic or "spez" in ic:
                                cat_default = "Erbe Aromatiche"
                        add_product_form(cat_default, prefill={
                            "nome": info["nome"],
                            "barcode": code,
                            "foto_url": info.get("foto_url", ""),
                            "categoria_off": info.get("categoria", ""),
                        })
                    else:
                        off_link = f"https://world.openfoodfacts.org/product/{code}"
                        st.warning(
                            f"Prodotto non trovato su Open Food Facts. "
                            f"[Verifica manualmente qui]({off_link}) — se il prodotto esiste online "
                            f"ma l'app non lo trova, riprova; altrimenti inseriscilo manualmente sotto."
                        )
                        add_product_form("Dispensa", prefill={"barcode": code})
                else:
                    st.error("Nessun barcode rilevato. Riprova con una foto più nitida e ben inquadrata.")

    st.divider()

    # Sidebar: navigazione
    with st.sidebar:
        st.markdown("## 🍽️ Menu")
        scelta = st.radio(
            "Naviga",
            [
                "🏠 Home",
                "🥫 Dispensa",
                "❄️ Freezer",
                "🧊 Frigo",
                "🌿 Erbe Aromatiche",
                "🍎 Frutta",
                "👨‍🍳 Ricettario Smart",
            ],
            label_visibility="collapsed",
        )
        st.divider()
        if st.button("🚪 Logout"):
            st.session_state["authenticated"] = False
            st.session_state["telegram_sent"] = False
            # Rimuove il token dall'URL e dal cookie così il prossimo accesso richiede password
            st.query_params.clear()
            try:
                get_cookie_manager().delete(COOKIE_NAME)
            except Exception:
                pass
            st.rerun()
        st.caption("Nordic Midnight • v1.0")

    # Routing
    if scelta == "🏠 Home":
        section_home(search)
    elif scelta == "🥫 Dispensa":
        section_categoria("Dispensa", "🥫", search)
    elif scelta == "❄️ Freezer":
        section_categoria("Freezer", "❄️", search)
    elif scelta == "🧊 Frigo":
        section_categoria("Frigo", "🧊", search)
    elif scelta == "🌿 Erbe Aromatiche":
        section_categoria("Erbe Aromatiche", "🌿", search)
    elif scelta == "🍎 Frutta":
        section_categoria("Frutta", "🍎", search)
    elif scelta == "👨‍🍳 Ricettario Smart":
        section_ricettario()


# =====================================================================
# ENTRY POINT
# =====================================================================
def main():
    init_db()
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    # Controlla se c'è già un token valido nell'URL (login persistente)
    if check_persistent_auth():
        main_app()
    else:
        login_screen()


if __name__ == "__main__":
    main()
