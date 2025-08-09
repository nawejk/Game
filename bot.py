import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import time
import threading
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

BOT_TOKEN = '8447925570:AAG5LsRoHfs3UXTJSgRa2PMjcrR291iDqfo'
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
    winner INTEGER DEFAULT NULL
)''')
db.commit()

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

states = {}
checked_signatures = set()
games = ['FIFA', 'Fortnite', 'Call of Duty', 'Mario Kart']

def create_logo():
    # Erstelle ein 400x400 Logo mit V, links rot, rechts blau
    size = (400, 400)
    img = Image.new('RGBA', size, (255,255,255,0))
    draw = ImageDraw.Draw(img)

    # Farben
    red = (220, 20, 60)     # Crimson red
    blue = (30, 144, 255)   # Dodger blue

    # Schriftart (Versuche eine Systemschrift, falls vorhanden)
    try:
        font = ImageFont.truetype("arial.ttf", 300)
    except:
        font = ImageFont.load_default()

    # Textgröße (V)
    text = "V"
    w, h = draw.textsize(text, font=font)

    # Position zentriert
    pos = ((size[0]-w)//2, (size[1]-h)//2 - 20)

    # Erstelle Maske für V
    mask = Image.new('L', size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text(pos, text, font=font, fill=255)

    # Links rot, rechts blau
    # Teile den Buchstaben in zwei Dreiecke
    for x in range(size[0]):
        for y in range(size[1]):
            if mask.getpixel((x,y)) > 0:
                if x < size[0]//2:
                    img.putpixel((x,y), red + (255,))
                else:
                    img.putpixel((x,y), blue + (255,))
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
    # Blau = 🔵, Rot = 🔴 für Buttons
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

    # Logo generieren und senden
    img = create_logo()
    bio = BytesIO()
    bio.name = 'versus_arena_logo.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    bot.send_photo(uid, photo=bio, caption="<b>Willkommen bei Versus Arena!</b>\nDer Ort für spannende 1-gegen-1 Matches.", parse_mode='HTML')

    main_menu(uid)

@bot.callback_query_handler(func=lambda c: True)
def handle_callback(call):
    uid = call.from_user.id
    data = call.data

    if data == "start_match":
        markup = InlineKeyboardMarkup()
        for g in games:
            # Button mit Farb-Emoji passend (abwechselnd)
            emoji = "🔵" if games.index(g) % 2 == 0 else "🔴"
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
        bot.send_message(uid, f"🔵📥 Sende SOL an:\n<code>{BOT_WALLET}</code>")

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

        # Gewinner setzen und Guthaben auszahlen
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

def handle_result_button(uid, mid):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🏆 Ich habe gewonnen", callback_data=f"win_{mid}"))
    bot.send_message(uid, "❓ Ergebnis melden:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.from_user.id in states)
def state_handler(msg):
    uid = msg.from_user.id
    state = states[uid]

    if state['step'] == 'opponent':
        opponent = msg.text.strip().lstrip("@")
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
            stake = float(msg.text.replace(",", "."))
            if stake <= 0:
                raise ValueError()
            state['stake'] = stake
            state['step'] = 'wallet1'
            bot.send_message(uid, "💼 Deine Wallet-Adresse (für Einsatz und Gewinn):")
        except:
            bot.send_message(uid, "❌ Ungültiger Betrag. Bitte Zahl eingeben (z.B. 0.1).")

    elif state['step'] == 'wallet1':
        wallet1 = msg.text.strip()
        if len(wallet1) < 30:
            bot.send_message(uid, "❌ Ungültige Wallet-Adresse.")
            return
        state['wallet1'] = wallet1
        state['step'] = 'wallet2'
        bot.send_message(uid, "💼 Wallet-Adresse des Gegners:")

    elif state['step'] == 'wallet2':
        wallet2 = msg.text.strip()
        if len(wallet2) < 30:
            bot.send_message(uid, "❌ Ungültige Wallet-Adresse.")
            return
        state['wallet2'] = wallet2

        # Match anlegen
        match_id = str(int(time.time()*1000))
        cur.execute("INSERT INTO matches (match_id, p1, p2, game, stake, wallet1, wallet2, paid1, paid2) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)",
                    (match_id, uid, state['opponent'], state['game'], state['stake'], state['wallet1'], state['wallet2']))
        db.commit()

        bot.send_message(uid, f"✅ Match erstellt mit {get_username(state['opponent'])} für {state['game']} mit Einsatz {state['stake']} SOL.\nSende jetzt die Zahlung an:\n<code>{state['wallet1']}</code>")
        bot.send_message(state['opponent'], f"📢 @{get_username(uid)} hat ein Match für {state['game']} gestartet mit Einsatz {state['stake']} SOL.\nSende deine Zahlung an:\n<code>{state['wallet2']}</code>")

        # Ergebnis Buttons an beide senden
        handle_result_button(uid, match_id)
        handle_result_button(state['opponent'], match_id)

        del states[uid]

    elif state['step'] == 'withdraw':
        try:
            amount = float(msg.text.replace(",", "."))
            bal = get_balance(uid)
            if amount <= 0 or amount > bal:
                bot.send_message(uid, f"❌ Ungültiger Betrag. Dein Guthaben: {bal:.4f} SOL")
                return
            # Anfrage an Admin senden
            bot.send_message(ADMIN_ID, f"💸 Auszahlung angefragt von @{get_username(uid)} ({uid}): {amount} SOL")
            bot.send_message(uid, "✅ Auszahlung angefragt. Die Bearbeitung dauert 1-2 Stunden.")
            del states[uid]
        except:
            bot.send_message(uid, "❌ Ungültiger Betrag.")

# --- Zahlungserkennung (einfaches Polling) ---
def check_payments():
    while True:
        try:
            cur.execute("SELECT match_id, wallet1, paid1 FROM matches WHERE paid1=0")
            unpaid1 = cur.fetchall()
            cur.execute("SELECT match_id, wallet2, paid2 FROM matches WHERE paid2=0")
            unpaid2 = cur.fetchall()

            for (mid, w, paid) in unpaid1:
                if check_solana_payment(w):
                    cur.execute("UPDATE matches SET paid1=1 WHERE match_id=?", (mid,))
                    db.commit()
                    p1 = get_match_player(mid, 1)
                    bot.send_message(p1, "✅ Deine Zahlung wurde erkannt.")

            for (mid, w, paid) in unpaid2:
                if check_solana_payment(w):
                    cur.execute("UPDATE matches SET paid2=1 WHERE match_id=?", (mid,))
                    db.commit()
                    p2 = get_match_player(mid, 2)
                    bot.send_message(p2, "✅ Deine Zahlung wurde erkannt.")
        except Exception as e:
            print("Error checking payments:", e)
        time.sleep(60)

def get_match_player(match_id, player_num):
    cur.execute("SELECT p1, p2 FROM matches WHERE match_id=?", (match_id,))
    r = cur.fetchone()
    if not r:
        return None
    return r[0] if player_num == 1 else r[1]

def check_solana_payment(wallet):
    # Simplified: Check if wallet balance > 0.001 SOL (Dummy, du musst hier eine echte RPC Abfrage einbauen)
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
        return sol > 0.001
    except:
        return False

threading.Thread(target=check_payments, daemon=True).start()

bot.infinity_polling()