import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import time
import threading
import requests
import sqlite3

BOT_TOKEN = '8447925570:AAG5LsRoHfs3UXTJSgRa2PMjcrR291iDqfo'
BOT_WALLET = 'CKZEpwiVqAHLiSbdc8Ebf8xaQ2fofgPCNmzi4cV32M1s'
RPC_URL = 'https://api.mainnet-beta.solana.com'
ADMIN_ID = 7919108078

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

conn = sqlite3.connect("gamebot.db", check_same_thread=False)
cur = conn.cursor()

cur.execute(\"""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    wallet TEXT,
    balance REAL DEFAULT 0
)\""")
cur.execute(\"""CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY,
    p1 INTEGER,
    p2 INTEGER,
    stake REAL,
    winner INTEGER,
    resolved INTEGER DEFAULT 0,
    FOREIGN KEY(p1) REFERENCES users(user_id),
    FOREIGN KEY(p2) REFERENCES users(user_id)
)\""")
conn.commit()

def get_username(uid):
    cur.execute("SELECT username FROM users WHERE user_id=?", (uid,))
    row = cur.fetchone()
    return row[0] if row else "unknown"

def main_menu(uid):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🎮 Match starten", callback_data="start_match"))
    markup.add(InlineKeyboardButton("💰 Guthaben", callback_data="balance"))
    markup.add(InlineKeyboardButton("📤 Auszahlung", callback_data="withdraw"))
    bot.send_message(uid, "🏠 Hauptmenü", reply_markup=markup)

@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id
    uname = msg.from_user.username or f"user{uid}"
    cur.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (uid, uname))
    conn.commit()
    main_menu(uid)

@bot.callback_query_handler(func=lambda call: True)
def handle_menu(call):
    uid = call.from_user.id
    data = call.data

    if data == "start_match":
        bot.send_message(uid, "👤 Username deines Gegners? (ohne @)")
        bot.register_next_step_handler(call.message, ask_opponent)

    elif data == "balance":
        cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
        bal = cur.fetchone()[0]
        bot.send_message(uid, f"💼 Dein Guthaben: <b>{bal:.4f} SOL</b>", parse_mode='HTML')

    elif data == "withdraw":
        bot.send_message(uid, "💸 Betrag zur Auszahlung?")
        bot.register_next_step_handler(call.message, handle_withdraw)

def ask_opponent(msg):
    uid = msg.from_user.id
    opponent_name = msg.text.strip().lstrip("@")
    cur.execute("SELECT user_id FROM users WHERE username=?", (opponent_name,))
    row = cur.fetchone()
    if not row:
        bot.send_message(uid, "❌ Gegner nicht gefunden. Beide müssen /start eingegeben haben.")
        return
    opponent_id = row[0]
    bot.send_message(uid, "💵 Einsatz in SOL?")
    bot.register_next_step_handler(msg, lambda m: ask_stake(m, opponent_id))

def ask_stake(msg, opponent_id):
    uid = msg.from_user.id
    try:
        stake = float(msg.text.strip())
        match_id = str(int(time.time()))
        cur.execute("INSERT INTO matches (match_id, p1, p2, stake) VALUES (?, ?, ?, ?)", (match_id, uid, opponent_id, stake))
        conn.commit()
        bot.send_message(uid, f"✅ Match erstellt. Sende <b>{stake} SOL</b> an:\n<code>{BOT_WALLET}</code>", parse_mode='HTML')
        bot.send_message(opponent_id, f"👋 Du wurdest herausgefordert!\n💵 Einsatz: {stake} SOL\nSende an:\n<code>{BOT_WALLET}</code>", parse_mode='HTML')
    except:
        bot.send_message(uid, "❌ Ungültiger Betrag.")

def handle_withdraw(msg):
    uid = msg.from_user.id
    try:
        amount = float(msg.text.strip())
        cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
        bal = cur.fetchone()[0]
        if amount > bal:
            bot.send_message(uid, "❌ Nicht genug Guthaben.")
            return
        cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, uid))
        conn.commit()
        bot.send_message(uid, "✅ Deine Auszahlung wird bearbeitet (1–2 Stunden).")
        bot.send_message(ADMIN_ID, f"📤 @{get_username(uid)} möchte {amount} SOL auszahlen.")
    except:
        bot.send_message(uid, "❌ Ungültiger Betrag.")

@bot.message_handler(commands=['ergebnis'])
def cmd_ergebnis(msg):
    uid = msg.from_user.id
    cur.execute("SELECT match_id FROM matches WHERE (p1=? OR p2=?) AND resolved=0", (uid, uid))
    row = cur.fetchone()
    if not row:
        bot.send_message(uid, "❌ Kein aktives Match.")
        return
    match_id = row[0]
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🏆 Ich habe gewonnen", callback_data=f"res_win_{match_id}"))
    markup.add(InlineKeyboardButton("❗ Unfair! Admin melden", callback_data=f"res_unfair_{match_id}"))
    bot.send_message(uid, "❓ Ergebnis:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("res_"))
def result_submit(call):
    uid = call.from_user.id
    parts = call.data.split("_")
    action, mid = parts[1], parts[2]

    cur.execute("SELECT p1, p2, winner, stake, resolved FROM matches WHERE match_id=?", (mid,))
    match = cur.fetchone()
    if not match:
        bot.send_message(uid, "❌ Match nicht gefunden.")
        return
    p1, p2, winner, stake, resolved = match

    if action == "win":
        if winner or resolved:
            bot.send_message(uid, "❗ Gewinner steht schon fest.")
            return
        cur.execute("UPDATE matches SET winner=?, resolved=1 WHERE match_id=?", (uid, mid))
        cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (stake * 2, uid))
        conn.commit()
        bot.send_message(uid, "✅ Du hast gewonnen. Guthaben gutgeschrieben.")
        opponent = p2 if uid == p1 else p1
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("❗ Unfair! Admin melden", callback_data=f"res_unfair_{mid}"))
        bot.send_message(opponent, "⚠️ Gegner hat Sieg gemeldet.", reply_markup=markup)

    elif action == "unfair":
        bot.send_message(ADMIN_ID, f"🚨 Streitfall Match {mid}: @{get_username(uid)} meldet 'Unfair!'")
        bot.send_message(uid, "🛠️ Admin wurde informiert.")

def check_payments():
    while True:
        try:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getSignaturesForAddress",
                "params": [BOT_WALLET, {"limit": 25}]
            }
            res = requests.post(RPC_URL, json=payload).json()
            for tx in res.get("result", []):
                sig = tx["signature"]
                tx_data = get_tx_details(sig)
                if not tx_data:
                    continue
                sender, amount = tx_data['from'], tx_data['amount']
                cur.execute("SELECT user_id FROM users WHERE wallet=?", (sender,))
                row = cur.fetchone()
                if row:
                    uid = row[0]
                    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, uid))
                    conn.commit()
                    bot.send_message(uid, f"✅ Einzahlung von {amount:.4f} SOL erkannt.")
        except Exception as e:
            print("Fehler bei Zahlungserkennung:", e)
        time.sleep(30)

def get_tx_details(sig):
    try:
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getTransaction",
            "params": [sig, {"encoding": "jsonParsed"}]
        }
        r = requests.post(RPC_URL, json=payload).json()
        instr = r['result']['transaction']['message']['instructions']
        for i in instr:
            if i.get('program') == 'system':
                info = i['parsed']['info']
                lamports = int(info['lamports'])
                sol = lamports / 1e9
                return {"from": info['source'], "amount": sol}
    except:
        return None

threading.Thread(target=check_payments, daemon=True).start()
print("🤖 Bot läuft...")
bot.infinity_polling()
