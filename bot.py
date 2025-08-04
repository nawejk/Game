import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import time
import threading
import requests

BOT_TOKEN = '8447925570:AAG5LsRoHfs3UXTJSgRa2PMjcrR291iDqfo'
BOT_WALLET = 'CKZEpwiVqAHLiSbdc8Ebf8xaQ2fofgPCNmzi4cV32M1s'
ADMIN_ID = 7919108078
RPC_URL = 'https://api.mainnet-beta.solana.com'

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')
db = sqlite3.connect("gamebot.db", check_same_thread=False)
cur = db.cursor()

# --- Datenbank-Setup
cur.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    wallet TEXT,
    balance REAL DEFAULT 0
)''')

cur.execute('''CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY,
    p1 INTEGER,
    p2 INTEGER,
    game TEXT,
    stake REAL,
    wallet1 TEXT,
    wallet2 TEXT,
    paid1 INTEGER,
    paid2 INTEGER,
    result1 TEXT,
    result2 TEXT
)''')
db.commit()

# --- Spielsystem
states = {}
checked_signatures = set()
games = ['FIFA', 'Fortnite', 'Call of Duty', 'Mario Kart']

def get_balance(uid):
    cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return r[0] if r else 0

def add_balance(uid, amount):
    cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    if r:
        new_bal = r[0] + amount
        cur.execute("UPDATE users SET balance=? WHERE user_id=?", (new_bal, uid))
        db.commit()

def set_wallet(uid, wallet):
    cur.execute("UPDATE users SET wallet=? WHERE user_id=?", (wallet, uid))
    db.commit()

def get_username(uid):
    cur.execute("SELECT username FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return r[0] if r else str(uid)

def main_menu(uid):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎮 Match starten", callback_data="start_match"),
        InlineKeyboardButton("💰 Guthaben", callback_data="balance"),
        InlineKeyboardButton("📥 Einzahlung", callback_data="deposit"),
        InlineKeyboardButton("📤 Auszahlung", callback_data="withdraw")
    )
    bot.send_message(uid, "🏠 Hauptmenü", reply_markup=markup)

# --- Start
@bot.message_handler(commands=['start'])
def cmd_start(msg):
    uid = msg.from_user.id
    username = msg.from_user.username or f"user{uid}"
    cur.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (uid, username))
    db.commit()
    main_menu(uid)

# --- Menüsteuerung
@bot.callback_query_handler(func=lambda call: True)
def cb_handler(call):
    uid = call.from_user.id
    data = call.data

    if data == "start_match":
        markup = InlineKeyboardMarkup()
        for g in games:
            markup.add(InlineKeyboardButton(g, callback_data=f"game_{g}"))
        bot.edit_message_text("🎮 Spiel auswählen:", uid, call.message.message_id, reply_markup=markup)

    elif data.startswith("game_"):
        game = data[5:]
        states[uid] = {'step': 'opponent', 'game': game}
        bot.send_message(uid, "👤 Gegner-Username (ohne @):")

    elif data == "balance":
        bal = get_balance(uid)
        bot.send_message(uid, f"💰 Dein Guthaben: <b>{bal:.4f} SOL</b>")

    elif data == "deposit":
        bot.send_message(uid, f"📥 Sende SOL an folgende Adresse:\n<code>{BOT_WALLET}</code>")

    elif data == "withdraw":
        bot.send_message(uid, "💸 Betrag zur Auszahlung (SOL):")
        states[uid] = {'step': 'withdraw'}

    elif data.startswith("trigger_result_"):
        mid = data.split("_")[-1]
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("🏆 Ich habe gewonnen", callback_data=f"res_win_{mid}"),
            InlineKeyboardButton("❌ Ich habe verloren", callback_data=f"res_lose_{mid}"),
            InlineKeyboardButton("🤝 Unentschieden", callback_data=f"res_draw_{mid}")
        )
        bot.send_message(uid, "❓ Was ist dein Ergebnis?", reply_markup=markup)

    elif data.startswith("res_"):
        # Ergebnis-Handler wird separat registriert
        pass

    elif data.startswith("unfair_"):
        mid = data.split("_")[1]
        cur.execute("SELECT p1, p2 FROM matches WHERE match_id=?", (mid,))
        match = cur.fetchone()
        if match:
            p1, p2 = match
            other_uid = p2 if uid == p1 else p1
            bot.send_message(ADMIN_ID, f"🚨 Streitfall gemeldet von @{get_username(uid)} im Match {mid}. Bitte prüfen.")
            bot.send_message(uid, "✅ Admin wurde informiert. Wir melden uns bald.")
            bot.answer_callback_query(call.id)

# --- Eingaben
@bot.message_handler(func=lambda m: m.from_user.id in states)
def state_handler(msg):
    uid = msg.from_user.id
    state = states[uid]

    if state['step'] == 'opponent':
        opponent_name = msg.text.strip().lstrip('@')
        cur.execute("SELECT user_id FROM users WHERE username=?", (opponent_name,))
        r = cur.fetchone()
        if not r:
            bot.send_message(uid, "❌ Gegner nicht gefunden.")
            states.pop(uid)
            return
        state['opponent'] = r[0]
        state['step'] = 'stake'
        bot.send_message(uid, "💵 Einsatz in SOL:")

    elif state['step'] == 'stake':
        try:
            stake = float(msg.text.strip())
            state['stake'] = stake
            state['step'] = 'wallet'
            bot.send_message(uid, "🔑 Deine Wallet-Adresse:")
        except:
            bot.send_message(uid, "❌ Ungültiger Betrag.")

    elif state['step'] == 'wallet':
        wallet = msg.text.strip()
        mid = str(int(time.time()))
        p2 = state['opponent']
        cur.execute("INSERT INTO matches VALUES (?, ?, ?, ?, ?, ?, '', 0, 0, '', '')",
            (mid, uid, p2, state['game'], state['stake'], wallet)
        )
        db.commit()
        states[p2] = {'step': 'wallet_join', 'match_id': mid}
        bot.send_message(p2, f"📨 Du wurdest zu einem Match eingeladen!\nSpiel: {state['game']}\nEinsatz: {state['stake']} SOL\nSende deine Wallet-Adresse:")
        bot.send_message(uid, f"✅ Sende {state['stake']} SOL an:\n<code>{BOT_WALLET}</code>")
        states.pop(uid)

    elif state['step'] == 'wallet_join':
        wallet2 = msg.text.strip()
        mid = state['match_id']
        cur.execute("UPDATE matches SET wallet2=? WHERE match_id=?", (wallet2, mid))
        db.commit()
        cur.execute("SELECT stake FROM matches WHERE match_id=?", (mid,))
        stake = cur.fetchone()[0]
        bot.send_message(uid, f"✅ Sende {stake} SOL an:\n<code>{BOT_WALLET}</code>")
        states.pop(uid)

    elif state['step'] == 'withdraw':
        try:
            amount = float(msg.text.strip())
            bal = get_balance(uid)
            if amount > bal:
                bot.send_message(uid, "❌ Nicht genug Guthaben.")
                return
            new_bal = bal - amount
            cur.execute("UPDATE users SET balance=? WHERE user_id=?", (new_bal, uid))
            db.commit()
            bot.send_message(uid, "✅ Auszahlung wird bearbeitet (1–2 Std).")
            bot.send_message(ADMIN_ID, f"📤 @{get_username(uid)} möchte {amount} SOL auszahlen.")
            states.pop(uid)
        except:
            bot.send_message(uid, "❌ Ungültiger Betrag.")

# --- Ergebnislogik (neu)
@bot.callback_query_handler(func=lambda c: c.data.startswith("res_"))
def result_handler(call):
    uid = call.from_user.id
    _, result, mid = call.data.split("_")

    cur.execute("SELECT p1, p2, result1, result2, stake FROM matches WHERE match_id=?", (mid,))
    match = cur.fetchone()
    if not match:
        bot.send_message(uid, "❌ Match nicht gefunden.")
        return
    p1, p2, r1, r2, stake = match

    # Wenn der Spieler schon ein Ergebnis hat, keine Doppelmeldungen
    if (uid == p1 and r1) or (uid == p2 and r2):
        bot.send_message(uid, "❌ Du hast dein Ergebnis bereits gemeldet.")
        return

    if uid == p1:
        cur.execute("UPDATE matches SET result1=? WHERE match_id=?", (result, mid))
        cur.execute("SELECT result2 FROM matches WHERE match_id=?", (mid,))
        other_result = cur.fetchone()[0]
        cur.execute("SELECT wallet1, wallet2 FROM matches WHERE match_id=?", (mid,))
        wallet1, wallet2 = cur.fetchone()
    elif uid == p2:
        cur.execute("UPDATE matches SET result2=? WHERE match_id=?", (result, mid))
        cur.execute("SELECT result1 FROM matches WHERE match_id=?", (mid,))
        other_result = cur.fetchone()[0]
        cur.execute("SELECT wallet1, wallet2 FROM matches WHERE match_id=?", (mid,))
        wallet1, wallet2 = cur.fetchone()
    else:
        bot.send_message(uid, "❌ Du bist kein Spieler in diesem Match.")
        return
    db.commit()

    # --- Logik für Auszahlung und Benachrichtigung
    if uid == p1:
        # Spieler 1 meldet Ergebnis als Erster
        if result == 'win':
            add_balance(p1, stake)
            bot.send_message(p1, f"🏆 Du hast gewonnen! +{stake:.4f} SOL gutgeschrieben.")
            bot.send_message(p2, "📢 Dein Gegner hat das Match gewonnen. Warte auf deine Eingabe.")
        elif result == 'lose':
            bot.send_message(p1, "📢 Du hast verloren. Warte auf die Bestätigung deines Gegners.")
            bot.send_message(p2, "📢 Dein Gegner hat verloren gemeldet.")
        elif result == 'draw':
            bot.send_message(p1, "🤝 Unentschieden gemeldet.")
            bot.send_message(p2, "🤝 Dein Gegner hat Unentschieden gemeldet.")

    elif uid == p2:
        # Spieler 2 meldet Ergebnis
        if result == 'win':
            add_balance(p2, stake)
            bot.send_message(p2, f"🏆 Du hast gewonnen! +{stake:.4f} SOL gutgeschrieben.")
            bot.send_message(p1, "📢 Dein Gegner hat das Match gewonnen. Warte auf deine Eingabe.")
        elif result == 'lose':
            bot.send_message(p2, "📢 Du hast verloren. Warte auf die Bestätigung deines Gegners.")
            bot.send_message(p1, "📢 Dein Gegner hat verloren gemeldet.")
        elif result == 'draw':
            bot.send_message(p2, "🤝 Unentschieden gemeldet.")
            bot.send_message(p1, "🤝 Dein Gegner hat Unentschieden gemeldet.")

    # --- Unfair Button zum Melden bei Streit
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("❗ Unfair!", callback_data=f"unfair_{mid}"))
    bot.send_message(uid, "Wenn du das Ergebnis anzweifelst, klicke unten:", reply_markup=markup)

    bot.answer_callback_query(call.id)

# --- Zahlungserkennung (vereinfacht)
def check_payments():
    while True:
        cur.execute("SELECT match_id, p1, p2, stake, wallet1, wallet2, paid1, paid2 FROM matches WHERE paid1=0 OR paid2=0")
        rows = cur.fetchall()
        for row in rows:
            mid, p1, p2, stake, w1, w2, paid1, paid2 = row
            # Beispiel: Hier müsste eine echte RPC-Abfrage stehen, die überprüft,
            # ob von w1 an BOT_WALLET mindestens stake SOL überwiesen wurde.
            # (Hier nur Dummy-Logik)
            if paid1 == 0:
                # Simuliere Zahlung
                cur.execute("UPDATE matches SET paid1=1 WHERE match_id=?", (mid,))
                bot.send_message(p1, "✅ Zahlung erhalten. Warte auf Gegner.")
            if paid2 == 0:
                cur.execute("UPDATE matches SET paid2=1 WHERE match_id=?", (mid,))
                bot.send_message(p2, "✅ Zahlung erhalten. Match startet bald.")
            db.commit()
        time.sleep(30)

threading.Thread(target=check_payments, daemon=True).start()

bot.infinity_polling()
                