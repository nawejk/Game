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
            InlineKeyboardButton("🏆 Gewonnen", callback_data=f"res_win_{mid}"),
            InlineKeyboardButton("❌ Verloren", callback_data=f"res_lose_{mid}"),
            InlineKeyboardButton("🤝 Unentschieden", callback_data=f"res_draw_{mid}")
        )
        bot.send_message(uid, "❓ Was ist dein Ergebnis?", reply_markup=markup)

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

# --- Ergebnislogik
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

    if uid == p1:
        cur.execute("UPDATE matches SET result1=? WHERE match_id=?", (result, mid))
    elif uid == p2:
        cur.execute("UPDATE matches SET result2=? WHERE match_id=?", (result, mid))
    else:
        return
    db.commit()
    bot.send_message(uid, f"✅ Ergebnis gespeichert: {result}")

    cur.execute("SELECT result1, result2 FROM matches WHERE match_id=?", (mid,))
    r1, r2 = cur.fetchone()

    if not r1 or not r2:
        return

    # Auswertung
    if r1 == "win" and r2 == "lose":
        add_balance(p1, stake * 2)
        msg = f"🏆 @{get_username(p1)} hat gewonnen!"
    elif r2 == "win" and r1 == "lose":
        add_balance(p2, stake * 2)
        msg = f"🏆 @{get_username(p2)} hat gewonnen!"
    elif r1 == "draw" and r2 == "draw":
        add_balance(p1, stake)
        add_balance(p2, stake)
        msg = "🤝 Unentschieden. Einsatz zurück."
    else:
        msg = "⚠️ Ergebnis widersprüchlich. Admin wird informiert."
        bot.send_message(ADMIN_ID, f"🚨 Streitfall Match {mid} zwischen @{get_username(p1)} und @{get_username(p2)}")

    bot.send_message(p1, msg)
    bot.send_message(p2, msg)
    cur.execute("DELETE FROM matches WHERE match_id=?", (mid,))
    db.commit()

# --- Einzahlungserkennung
def get_tx_details(sig):
    try:
        r = requests.post(RPC_URL, json={
            "jsonrpc":"2.0","id":1,"method":"getTransaction",
            "params":[sig, {"encoding":"jsonParsed"}]
        }).json()
        instr = r['result']['transaction']['message']['instructions']
        for i in instr:
            if i.get('program') == 'system':
                info = i['parsed']['info']
                return {"from": info['source'], "amount": int(info['lamports']) / 1e9}
    except:
        return None

def check_payments():
    while True:
        try:
            r = requests.post(RPC_URL, json={
                "jsonrpc":"2.0","id":1,"method":"getSignaturesForAddress",
                "params":[BOT_WALLET, {"limit": 30}]
            }).json()
            for tx in r['result']:
                sig = tx['signature']
                if sig in checked_signatures:
                    continue
                checked_signatures.add(sig)
                txd = get_tx_details(sig)
                if not txd:
                    continue
                sender, amount = txd['from'], txd['amount']

                # Einzahlung?
                cur.execute("SELECT user_id FROM users WHERE wallet=?", (sender,))
                u = cur.fetchone()
                if u:
                    add_balance(u[0], amount)
                    bot.send_message(u[0], f"✅ Einzahlung erkannt: {amount:.4f} SOL")
                    continue

                # Matchzahlung?
                cur.execute("SELECT match_id, p1, p2, wallet1, wallet2, paid1, paid2, stake FROM matches")
                for m in cur.fetchall():
                    mid, p1, p2, w1, w2, paid1, paid2, stake = m
                    updated = False
                    if sender == w1 and not paid1 and amount >= stake:
                        cur.execute("UPDATE matches SET paid1=1 WHERE match_id=?", (mid,))
                        bot.send_message(p1, f"✅ Zahlung erkannt: {amount:.4f} SOL")
                        updated = True
                    elif sender == w2 and not paid2 and amount >= stake:
                        cur.execute("UPDATE matches SET paid2=1 WHERE match_id=?", (mid,))
                        bot.send_message(p2, f"✅ Zahlung erkannt: {amount:.4f} SOL")
                        updated = True
                    db.commit()

                    if updated:
                        cur.execute("SELECT paid1, paid2 FROM matches WHERE match_id=?", (mid,))
                        if all(cur.fetchone()):
                            markup = InlineKeyboardMarkup()
                            markup.add(InlineKeyboardButton("🏆 Ergebnis melden", callback_data=f"trigger_result_{mid}"))
                            bot.send_message(p1, "✅ Beide haben gezahlt!", reply_markup=markup)
                            bot.send_message(p2, "✅ Beide haben gezahlt!", reply_markup=markup)
        except Exception as e:
            print("Zahlungsprüfung fehlgeschlagen:", e)
        time.sleep(30)

# --- Bot starten
threading.Thread(target=check_payments, daemon=True).start()
print("🤖 Bot läuft...")
bot.infinity_polling()