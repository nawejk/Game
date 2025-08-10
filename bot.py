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
import json
import logging

# Logging konfigurieren
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = '8113317405:AAERiOi3TM95xU87ys9xIV_L622MLo83t6Q'
BOT_WALLET = 'CKZEpwiVqAHLiSbdc8Ebf8xaQ2fofgPCNmzi4cV32M1s'
ADMIN_ID = 7919108078
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

def create_logo():
    size = (400, 400)
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    try:
        # Versuche verschiedene Schriftarten
        try:
            font = ImageFont.truetype("arial.ttf", 300)
        except:
            font = ImageFont.truetype("DejaVuSans.ttf", 300)
    except:
        # Fallback auf Standardschrift
        font = ImageFont.load_default()
        # Für load_default skalieren wir die Größe
        if hasattr(font, 'getsize'):
            # Ältere Pillow-Versionen
            w, h = font.getsize("V")
            font.size = max(w, h)
        else:
            # Für neue Versionen
            font.size = 300

    text = "V"
    
    # Moderner Weg um Textgröße zu bekommen
    if hasattr(draw, 'textbbox'):
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
    elif hasattr(font, 'getsize'):
        # Für ältere Pillow-Versionen
        w, h = font.getsize(text)
    else:
        # Notfall
        w, h = 300, 300
    
    pos = ((size[0]-w)//2, (size[1]-h)//2 - 20)
    
    # Erstelle Maske für V
    mask = Image.new('L', size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text(pos, text, font=font, fill=255)
    
    # Links rot, rechts blau
    red_part = Image.new('RGBA', size, (220, 20, 60, 255))
    blue_part = Image.new('RGBA', size, (30, 144, 255, 255))
    
    # Maske in links/rechts teilen
    mask_left = mask.crop((0, 0, size[0]//2, size[1]))
    mask_right = mask.crop((size[0]//2, 0, size[0], size[1]))
    
    # Farbteile anwenden
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
    bot.send_message(uid, "<b>🏆 Versus Arena 🏆</b>\n\n🏠 Hauptmenü", reply_markup=markup)

@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id
    uname = msg.from_user.username or f"user{uid}"
    cur.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (uid, uname))
    db.commit()

    try:
        img = create_logo()
        bio = BytesIO()
        bio.name = 'versus_arena_logo.png'
        img.save(bio, 'PNG')
        bio.seek(0)
        bot.send_photo(uid, photo=bio, caption="<b>Willkommen bei Versus Arena!</b>\nDer Ort für spannende 1-gegen-1 Matches.", parse_mode='HTML')
    except Exception as e:
        logger.error(f"Error creating logo: {e}")
        bot.send_message(uid, "<b>Willkommen bei Versus Arena!</b>\nDer Ort für spannende 1-gegen-1 Matches.")

    main_menu(uid)

@bot.callback_query_handler(func=lambda c: True)
def handle_callback(call):
    uid = call.from_user.id
    data = call.data

    if data == "start_match":
        markup = InlineKeyboardMarkup()
        for idx, g in enumerate(games):
            emoji = "🔵" if idx % 2 == 0 else "🔴"
            markup.add(InlineKeyboardButton(f"{emoji} {g}", callback_data=f"game_{g}"))
        bot.edit_message_text("<b>🎮 Versus Arena - Spiel auswählen:</b>", uid, call.message.message_id, reply_markup=markup)

    elif data.startswith("game_"):
        game = data[5:]
        states[uid] = {'step': 'opponent', 'game': game}
        bot.send_message(uid, "👤 Gegner-Username (ohne @):")

    elif data == "balance":
        bal = get_balance(uid)
        bot.send_message(uid, f"🔵💰 Dein Guthaben: <b>{bal:.4f} SOL</b>")

    elif data == "deposit":
        bot.send_message(uid, f"🔵📥 Sende SOL an:\n<code>{BOT_WALLET}</code>\n\n<b>WICHTIG:</b> Füge im Memo-Feld deine User-ID hinzu: <code>{uid}</code>")

    elif data == "withdraw":
        states[uid] = {'step': 'withdraw'}
        bot.send_message(uid, "🔴💸 Betrag zur Auszahlung:")

    elif data.startswith("win_"):
        mid = data.split("_")[1]
        cur.execute("SELECT p1, p2, stake, winner FROM matches WHERE match_id=?", (mid,))
        match = cur.fetchone()
        if not match:
            bot.send_message(uid, "❌ Match nicht gefunden.")
            return
        p1, p2, stake, winner = match
        if winner:
            bot.send_message(uid, "⚠️ Es wurde bereits ein Sieger gemeldet.")
            return

        cur.execute("UPDATE matches SET winner=? WHERE match_id=?", (uid, mid))
        add_balance(uid, stake * 2)
        db.commit()
        bot.send_message(uid, "🏆 Du hast gewonnen! Dein Guthaben wurde gutgeschrieben.")

        opponent = p2 if uid == p1 else p1
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("❗ Problem melden", callback_data=f"dispute_{mid}"))
        bot.send_message(opponent, f"⚠️ @{get_username(uid)} hat den Sieg gemeldet.\nFalls ein Problem besteht, melde es hier:", reply_markup=markup)

    elif data.startswith("dispute_"):
        mid = data.split("_")[1]
        bot.send_message(ADMIN_ID, f"🚨 Streitfall Match {mid}: Ein Spieler meldet ein Problem.")
        bot.send_message(uid, "📨 Der Admin wurde informiert. Bitte sende ggf. Beweise.")
    
    # Admin commands
    elif data == "admin_balance":
        if uid == ADMIN_ID:
            payload = {"jsonrpc":"2.0","id":1,"method":"getBalance","params":[BOT_WALLET]}
            try:
                r = requests.post(RPC_URL, json=payload).json()
                balance = r['result']['value'] / 1e9
                bot.send_message(ADMIN_ID, f"💰 Bot Wallet Balance: {balance:.4f} SOL")
            except Exception as e:
                logger.error(f"Balance check error: {e}")
                bot.send_message(ADMIN_ID, "❌ Fehler beim Abrufen des Guthabens")

def handle_result_button(uid, mid):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🏆 Ich habe gewonnen", callback_data=f"win_{mid}"))
    bot.send_message(uid, "❓ Ergebnis melden:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.from_user.id in states)
def state_handler(msg):
    uid = msg.from_user.id
    state = states[uid]
    text = msg.text.strip()

    if state['step'] == 'opponent':
        opponent = text.lstrip("@")
        cur.execute("SELECT user_id FROM users WHERE username=?", (opponent,))
        r = cur.fetchone()
        if not r:
            bot.send_message(uid, "❌ Gegner nicht gefunden.")
            return
        state['opponent'] = r[0]
        state['step'] = 'stake'
        bot.send_message(uid, "💰 Einsatz in SOL (z.B. 0.1):")

    elif state['step'] == 'stake':
        try:
            stake = float(text.replace(",", "."))
            if stake <= 0:
                raise ValueError()
            state['stake'] = stake
            state['step'] = 'wallet1'
            bot.send_message(uid, "💼 Deine Wallet-Adresse (für Einsatz und Gewinn):")
        except:
            bot.send_message(uid, "❌ Ungültiger Betrag. Bitte Zahl eingeben (z.B. 0.1).")

    elif state['step'] == 'wallet1':
        if len(text) < 30:
            bot.send_message(uid, "❌ Ungültige Wallet-Adresse.")
            return
        state['wallet1'] = text
        state['step'] = 'wallet2'
        bot.send_message(uid, "💼 Wallet-Adresse des Gegners:")

    elif state['step'] == 'wallet2':
        if len(text) < 30:
            bot.send_message(uid, "❌ Ungültige Wallet-Adresse.")
            return
        state['wallet2'] = text

        # Create match
        match_id = str(int(time.time()*1000))
        created_at = time.time()
        cur.execute("INSERT INTO matches (match_id, p1, p2, game, stake, wallet1, wallet2, paid1, paid2, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?)",
                    (match_id, uid, state['opponent'], state['game'], state['stake'], state['wallet1'], state['wallet2'], created_at))
        db.commit()

        bot.send_message(uid, f"✅ Match erstellt mit {get_username(state['opponent'])} für {state['game']} mit Einsatz {state['stake']} SOL.\nSende jetzt die Zahlung an:\n<code>{state['wallet1']}</code>")
        bot.send_message(state['opponent'], f"📢 @{get_username(uid)} hat ein Match für {state['game']} gestartet mit Einsatz {state['stake']} SOL.\nSende deine Zahlung an:\n<code>{state['wallet2']}</code>")

        # Send result buttons
        handle_result_button(uid, match_id)
        handle_result_button(state['opponent'], match_id)

        del states[uid]

    elif state['step'] == 'withdraw':
        try:
            amount = float(text.replace(",", "."))
            bal = get_balance(uid)
            if amount <= 0 or amount > bal:
                bot.send_message(uid, f"❌ Ungültiger Betrag. Dein Guthaben: {bal:.4f} SOL")
                return
            
            # Create withdrawal request
            cur.execute("INSERT INTO withdrawals (user_id, amount, timestamp) VALUES (?, ?, ?)",
                       (uid, amount, time.time()))
            db.commit()
            
            bot.send_message(uid, "✅ Auszahlung angefragt. Die Bearbeitung dauert 1-2 Stunden.")
            bot.send_message(ADMIN_ID, f"💸 Neue Auszahlungsanfrage von @{get_username(uid)}: {amount} SOL")
            del states[uid]
        except:
            bot.send_message(uid, "❌ Ungültiger Betrag.")

# --- Payment checking ---
def check_payments():
    while True:
        try:
            # Check match payments
            cur.execute("SELECT match_id, wallet1, paid1, created_at, stake FROM matches WHERE paid1=0")
            unpaid1 = cur.fetchall()
            cur.execute("SELECT match_id, wallet2, paid2, created_at, stake FROM matches WHERE paid2=0")
            unpaid2 = cur.fetchall()

            for (mid, w, paid, created_at, stake) in unpaid1:
                if check_solana_payment(w, created_at, stake):
                    cur.execute("UPDATE matches SET paid1=1 WHERE match_id=?", (mid,))
                    db.commit()
                    p1 = get_match_player(mid, 1)
                    if p1:
                        bot.send_message(p1, "✅ Deine Zahlung wurde erkannt.")

            for (mid, w, paid, created_at, stake) in unpaid2:
                if check_solana_payment(w, created_at, stake):
                    cur.execute("UPDATE matches SET paid2=1 WHERE match_id=?", (mid,))
                    db.commit()
                    p2 = get_match_player(mid, 2)
                    if p2:
                        bot.send_message(p2, "✅ Deine Zahlung wurde erkannt.")
        except Exception as e:
            logger.error(f"Error checking match payments: {e}")
        time.sleep(60)

def check_deposits():
    while True:
        try:
            # Get recent transactions
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [
                    BOT_WALLET,
                    {"limit": 10}
                ]
            }
            response = requests.post(RPC_URL, json=payload).json()
            
            if 'error' in response:
                logger.error(f"RPC error: {response['error']}")
                time.sleep(60)
                continue
                
            signatures = [sig['signature'] for sig in response.get('result', [])]
            
            for sig in signatures:
                if sig in checked_signatures:
                    continue
                checked_signatures.add(sig)
                
                # Get transaction details
                tx_payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTransaction",
                    "params": [sig, "jsonParsed"]
                }
                tx_resp = requests.post(RPC_URL, json=tx_payload).json()
                
                if 'error' in tx_resp or 'result' not in tx_resp:
                    logger.error(f"Transaction error for {sig}: {tx_resp.get('error', 'No result')}")
                    continue
                    
                tx = tx_resp.get('result', {})
                
                # Check if valid transaction
                if tx.get('meta', {}).get('err'):
                    continue
                
                # Find memo and amount
                memo = None
                amount = 0
                
                # Check instructions for memo
                for ix in tx.get('transaction', {}).get('message', {}).get('instructions', []):
                    if ix.get('program') == 'spl-memo' and 'data' in ix:
                        try:
                            memo = base64.b64decode(ix['data']).decode('utf-8')
                        except:
                            continue
                
                # Check balance changes
                account_keys = tx['transaction']['message']['accountKeys']
                try:
                    if BOT_WALLET in account_keys:
                        wallet_index = account_keys.index(BOT_WALLET)
                        pre_balance = tx['meta']['preBalances'][wallet_index]
                        post_balance = tx['meta']['postBalances'][wallet_index]
                        amount = (post_balance - pre_balance) / 1e9
                except Exception as e:
                    logger.error(f"Balance error: {e}")
                    continue
                
                if amount <= 0 or not memo:
                    continue
                
                try:
                    user_id = int(memo)
                    # Check if deposit already processed
                    cur.execute("SELECT * FROM deposits WHERE signature=?", (sig,))
                    if cur.fetchone():
                        continue
                    
                    # Credit user
                    add_balance(user_id, amount)
                    cur.execute("INSERT INTO deposits (signature, user_id, amount, timestamp) VALUES (?, ?, ?, ?)",
                                (sig, user_id, amount, time.time()))
                    db.commit()
                    bot.send_message(user_id, f"✅ Einzahlung von {amount:.4f} SOL erkannt. Dein Guthaben wurde aktualisiert.")
                    logger.info(f"Deposit processed: {user_id} - {amount} SOL")
                except Exception as e:
                    logger.error(f"Deposit processing error: {e}")
        except Exception as e:
            logger.error(f"Error checking deposits: {e}")
        time.sleep(60)

def get_match_player(match_id, player_num):
    try:
        cur.execute("SELECT p1, p2 FROM matches WHERE match_id=?", (match_id,))
        r = cur.fetchone()
        if not r:
            return None
        return r[0] if player_num == 1 else r[1]
    except:
        return None

def check_solana_payment(wallet, created_at, stake):
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [wallet]
        }
        r = requests.post(RPC_URL, json=payload, timeout=5).json()
        lamports = r.get("result", {}).get("value", 0)
        sol = lamports / 1e9
        return sol >= stake
    except Exception as e:
        logger.error(f"Payment check error for {wallet}: {e}")
        return False

# Start threads
threading.Thread(target=check_payments, daemon=True).start()
threading.Thread(target=check_deposits, daemon=True).start()

# Admin commands
@bot.message_handler(commands=['admin'])
def admin_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💰 Wallet Guthaben", callback_data="admin_balance"))
    bot.send_message(ADMIN_ID, "👑 Admin-Menü:", reply_markup=markup)

@bot.message_handler(commands=['admin_withdrawals'])
def admin_withdrawals(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    cur.execute("SELECT withdrawal_id, user_id, amount, timestamp FROM withdrawals WHERE status='pending'")
    pending = cur.fetchall()
    if not pending:
        bot.send_message(ADMIN_ID, "Keine ausstehenden Auszahlungen.")
        return
    
    text = "📝 Ausstehende Auszahlungen:\n\n"
    for wd in pending:
        text += f"ID: {wd[0]}\nUser: @{get_username(wd[1])} ({wd[1]})\nBetrag: {wd[2]} SOL\nZeit: {time.ctime(wd[3])}\n\n"
    bot.send_message(ADMIN_ID, text)

@bot.message_handler(commands=['admin_pay'])
def admin_pay(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    
    parts = msg.text.split()
    if len(parts) < 3:
        bot.send_message(ADMIN_ID, "Verwendung: /admin_pay <withdrawal_id> <txid>")
        return
    
    try:
        wd_id = int(parts[1])
        txid = parts[2]
        
        cur.execute("SELECT user_id, amount FROM withdrawals WHERE withdrawal_id=? AND status='pending'", (wd_id,))
        wd = cur.fetchone()
        if not wd:
            bot.send_message(ADMIN_ID, "Ungültige Auszahlungs-ID oder bereits bearbeitet.")
            return
        
        user_id, amount = wd
        cur.execute("UPDATE withdrawals SET status='paid', txid=? WHERE withdrawal_id=?", (txid, wd_id))
        add_balance(user_id, -amount)
        db.commit()
        
        bot.send_message(ADMIN_ID, "✅ Auszahlung markiert als bezahlt.")
        bot.send_message(user_id, f"✅ Deine Auszahlung von {amount} SOL wurde bearbeitet. Transaktions-ID: {txid}")
        logger.info(f"Withdrawal processed: ID {wd_id} - {amount} SOL to user {user_id}")
    except Exception as e:
        logger.error(f"Withdrawal error: {e}")
        bot.send_message(ADMIN_ID, "❌ Fehler bei der Verarbeitung.")

# Start the bot
if __name__ == '__main__':
    logger.info("Starting bot...")
    bot.infinity_polling()