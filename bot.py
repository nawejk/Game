import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import time
import threading
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import base64
import logging

# Logging konfigurieren
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = 'DEIN_BOT_TOKEN'
BOT_WALLET = 'DEINE_SOL_WALLET'
ADMIN_ID = 123456789
RPC_URL = 'https://api.mainnet-beta.solana.com'

# --- DB Setup ---
if os.path.exists("gamebot.db"):
    os.remove("gamebot.db")

db = sqlite3.connect("gamebot.db", check_same_thread=False)
cur = db.cursor()

cur.execute('''CREATE TABLE users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    wallet TEXT,
    balance REAL DEFAULT 0
)''')

cur.execute('''CREATE TABLE matches (
    match_id TEXT PRIMARY KEY,
    p1 INTEGER,
    p2 INTEGER,
    game TEXT,
    stake REAL,
    wallet1 TEXT,
    wallet2 TEXT,
    paid1 INTEGER,
    paid2 INTEGER,
    winner INTEGER DEFAULT NULL,
    created_at REAL
)''')

cur.execute('''CREATE TABLE deposits (
    signature TEXT PRIMARY KEY,
    user_id INTEGER,
    amount REAL,
    timestamp REAL
)''')

cur.execute('''CREATE TABLE withdrawals (
    withdrawal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount REAL,
    status TEXT DEFAULT 'pending',
    timestamp REAL,
    txid TEXT
)''')
db.commit()

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

states = {}
checked_signatures = set()
games = ['FIFA', 'Fortnite', 'Call of Duty', 'Mario Kart']

# ------------------- Hilfsfunktionen -------------------
def create_logo():
    size = (400, 400)
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 300)
    except:
        font = ImageFont.load_default()
    text = "V"
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    pos = ((size[0]-w)//2, (size[1]-h)//2 - 20)
    mask = Image.new('L', size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text(pos, text, font=font, fill=255)
    red_part = Image.new('RGBA', size, (220, 20, 60, 255))
    blue_part = Image.new('RGBA', size, (30, 144, 255, 255))
    mask_left = mask.crop((0, 0, size[0]//2, size[1]))
    mask_right = mask.crop((size[0]//2, 0, size[0], size[1]))
    img.paste(red_part, (0, 0), mask_left)
    img.paste(blue_part, (size[0]//2, 0), mask_right)
    return img

def get_username(uid):
    cur.execute("SELECT username FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return r[0] if r else f"user{uid}"

def get_balance(uid):
    cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return r[0] if r else 0

def add_balance(uid, amount):
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, uid))
    db.commit()

def main_menu(uid):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔵🎮 Match starten", callback_data="start_match"),
        InlineKeyboardButton("🔴💰 Guthaben", callback_data="balance"),
        InlineKeyboardButton("🔵📥 Einzahlung", callback_data="deposit"),
        InlineKeyboardButton("🔴📤 Auszahlung", callback_data="withdraw")
    )
    bot.send_message(uid, "<b>🏆 Versus Arena 🏆\n\n🏠 Hauptmenü</b>", reply_markup=markup)

# ------------------- Start -------------------
@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id
    uname = msg.from_user.username or f"user{uid}"
    cur.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (uid, uname))
    db.commit()
    try:
        img = create_logo()
        bio = BytesIO()
        bio.name = 'logo.png'
        img.save(bio, 'PNG')
        bio.seek(0)
        bot.send_photo(uid, photo=bio, caption="<b>Willkommen bei Versus Arena!</b>")
    except Exception as e:
        logger.error(f"Logo error: {e}")
    main_menu(uid)

# ------------------- Callbacks -------------------
@bot.callback_query_handler(func=lambda c: True)
def handle_callback(call):
    uid = call.from_user.id
    data = call.data
    if data == "start_match":
        markup = InlineKeyboardMarkup()
        for idx, g in enumerate(games):
            emoji = "🔵" if idx % 2 == 0 else "🔴"
            markup.add(InlineKeyboardButton(f"{emoji} {g}", callback_data=f"game_{g}"))
        bot.edit_message_text("<b>🎮 Spiel auswählen:</b>", uid, call.message.message_id, reply_markup=markup)
    elif data.startswith("game_"):
        game = data[5:]
        states[uid] = {'step': 'opponent', 'game': game}
        bot.send_message(uid, "👤 Gegner-Username (ohne @):")
    elif data == "balance":
        bot.send_message(uid, f"💰 Guthaben: <b>{get_balance(uid):.4f} SOL</b>")
    elif data == "deposit":
        bot.send_message(uid, f"📥 Sende SOL an:\n<code>{BOT_WALLET}</code>\nMemo: <code>{uid}</code>")
    elif data == "withdraw":
        states[uid] = {'step': 'withdraw'}
        bot.send_message(uid, "💸 Betrag zur Auszahlung:")

# ------------------- State Handler -------------------
@bot.message_handler(func=lambda m: m.from_user.id in states)
def state_handler(msg):
    uid = msg.from_user.id
    state = states[uid]
    text = msg.text.strip()
    if state['step'] == 'withdraw':
        try:
            amount = float(text)
            if amount <= 0 or amount > get_balance(uid):
                bot.send_message(uid, f"❌ Ungültiger Betrag. Guthaben: {get_balance(uid):.4f}")
                return
            cur.execute("INSERT INTO withdrawals (user_id, amount, timestamp) VALUES (?, ?, ?)",
                        (uid, amount, time.time()))
            db.commit()
            bot.send_message(uid, "✅ Auszahlung angefragt.")
            bot.send_message(ADMIN_ID, f"Neue Auszahlung: {amount} SOL von {get_username(uid)}")
            del states[uid]
        except:
            bot.send_message(uid, "❌ Ungültiger Betrag.")

# ------------------- Zahlungen prüfen -------------------
def check_deposits():
    while True:
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [BOT_WALLET, {"limit": 10}]
            }
            resp = requests.post(RPC_URL, json=payload).json()
            if 'error' in resp:
                logger.error(f"RPC error: {resp['error']}")
                time.sleep(60)
                continue
            signatures = [s['signature'] for s in resp.get('result', [])]
            for sig in signatures:
                if sig in checked_signatures:
                    continue
                checked_signatures.add(sig)
                tx_payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTransaction",
                    "params": [sig, "jsonParsed"]
                }
                tx_resp = requests.post(RPC_URL, json=tx_payload).json()
                if 'error' in tx_resp:
                    if tx_resp['error'].get('code') == 429:
                        logger.warning("Rate Limit erreicht, warte 5s")
                        time.sleep(5)
                        continue
                    logger.error(f"TX Error {sig}: {tx_resp['error']}")
                    continue
                tx = tx_resp.get('result', {})
                if not tx or tx.get('meta', {}).get('err'):
                    continue
                memo = None
                amount = 0
                for ix in tx.get('transaction', {}).get('message', {}).get('instructions', []):
                    if ix.get('program') == 'spl-memo' and 'data' in ix:
                        try:
                            memo = base64.b64decode(ix['data']).decode('utf-8')
                        except:
                            pass
                account_keys = tx['transaction']['message']['accountKeys']
                if BOT_WALLET in account_keys:
                    idx = account_keys.index(BOT_WALLET)
                    pre = tx['meta']['preBalances'][idx]
                    post = tx['meta']['postBalances'][idx]
                    amount = (post - pre) / 1e9
                if amount > 0 and memo:
                    try:
                        user_id = int(memo)
                        cur.execute("SELECT * FROM deposits WHERE signature=?", (sig,))
                        if cur.fetchone():
                            continue
                        add_balance(user_id, amount)
                        cur.execute("INSERT INTO deposits (signature, user_id, amount, timestamp) VALUES (?, ?, ?, ?)",
                                    (sig, user_id, amount, time.time()))
                        db.commit()
                        bot.send_message(user_id, f"✅ Einzahlung von {amount:.4f} SOL erkannt.")
                        logger.info(f"Deposit: {user_id} - {amount} SOL")
                    except Exception as e:
                        logger.error(f"Deposit error: {e}")
                time.sleep(0.2)
        except Exception as e:
            logger.error(f"check_deposits Fehler: {e}")
        time.sleep(60)

# ------------------- Threads starten -------------------
threading.Thread(target=check_deposits, daemon=True).start()

if __name__ == '__main__':
    logger.info("Bot startet...")
    bot.infinity_polling()