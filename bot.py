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

conn = sqlite3.connect("gamebot.db", check_same_thread=False)
cur = conn.cursor()

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
conn.commit()

states = {}
checked_signatures = set()
games = ['FIFA', 'Fortnite', 'Call of Duty', 'Mario Kart']

def main_menu(user_id):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎮 Match starten", callback_data="start_match"),
        InlineKeyboardButton("💰 Guthaben", callback_data="balance"),
        InlineKeyboardButton("📥 Einzahlung", callback_data="deposit"),
        InlineKeyboardButton("📤 Auszahlung", callback_data="withdraw")
    )
    bot.send_message(user_id, "🏠 Hauptmenü", reply_markup=markup)

def get_balance(uid):
    cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return r[0] if r else 0

def update_balance(uid, amount):
    cur.execute("UPDATE users SET balance=? WHERE user_id=?", (amount, uid))
    conn.commit()

def add_balance(uid, amount):
    bal = get_balance(uid)
    update_balance(uid, bal + amount)

@bot.message_handler(commands=['start'])
def cmd_start(msg):
    uid = msg.from_user.id
    username = msg.from_user.username or f"user{uid}"
    cur.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (uid, username))
    conn.commit()
    main_menu(uid)

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
        states[uid] = {"step": "opponent", "game": game}
        bot.send_message(uid, "👤 Gegner-Username (ohne @):")

    elif data == "balance":
        bal = get_balance(uid)
        bot.send_message(uid, f"💰 Dein Guthaben: <b>{bal:.4f} SOL</b>")

    elif data == "deposit":
        bot.send_message(uid, f"📥 Sende SOL an folgende Adresse:\n<code>{BOT_WALLET}</code>")

    elif data == "withdraw":
        bot.send_message(uid, "💸 Betrag zur Auszahlung (SOL):")
        states[uid] = {"step": "withdraw"}

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
        opponent_id = r[0]
        state['opponent'] = opponent_id
        state['step'] = 'stake'
        bot.send_message(uid, "💵 Einsatz (SOL):")

    elif state['step'] == 'stake':
        try:
            stake = float(msg.text.strip())
            state['stake'] = stake
            state['step'] = 'wallet'
            bot.send_message(uid, "🔑 Deine Wallet-Adresse:")
        except:
            bot.send_message(uid, "❌ Ungültiger Betrag.")

    elif state['step'] == 'wallet':
        mid = str(int(time.time()))
        opponent_id = state['opponent']
        stake = state['stake']
        game = state['game']
        wallet1 = msg.text.strip()
        cur.execute('''INSERT INTO matches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (mid, uid, opponent_id, game, stake, wallet1, '', 0, 0, '', '')
        )
        conn.commit()
        states[opponent_id] = {'step': 'wallet_join', 'match_id': mid}
        bot.send_message(opponent_id, f"👋 Du wurdest zu einem <b>{game}</b>-Match eingeladen!\nEinsatz: {stake} SOL\nBitte sende deine Wallet:", parse_mode='HTML')
        bot.send_message(uid, f"✅ Sende <b>{stake} SOL</b> an:\n<code>{BOT_WALLET}</code>", parse_mode='HTML')
        states.pop(uid)

    elif state['step'] == 'wallet_join':
        mid = state['match_id']
        wallet2 = msg.text.strip()
        cur.execute("UPDATE matches SET wallet2=? WHERE match_id=?", (wallet2, mid))
        conn.commit()
        cur.execute("SELECT stake FROM matches WHERE match_id=?", (mid,))
        stake = cur.fetchone()[0]
        bot.send_message(uid, f"✅ Sende <b>{stake} SOL</b> an:\n<code>{BOT_WALLET}</code>", parse_mode='HTML')
        states.pop(uid)

    elif state['step'] == 'withdraw':
        try:
            amount = float(msg.text.strip())
            bal = get_balance(uid)
            if amount > bal:
                bot.send_message(uid, "❌ Nicht genug Guthaben.")
                return
            update_balance(uid, bal - amount)
            bot.send_message(uid, "✅ Deine Auszahlung wird bearbeitet (1–2 Std).")
            cur.execute("SELECT username FROM users WHERE user_id=?", (uid,))
            name = cur.fetchone()[0]
            bot.send_message(ADMIN_ID, f"📤 @{name} möchte {amount} SOL auszahlen.")
            states.pop(uid)
        except:
            bot.send_message(uid, "❌ Ungültiger Betrag.")

@bot.message_handler(commands=['ergebnis'])
def cmd_result(msg):
    uid = msg.from_user.id
    cur.execute("SELECT match_id FROM matches WHERE (p1=? OR p2=?) AND paid1=1 AND paid2=1", (uid, uid))
    row = cur.fetchone()
    if not row:
        bot.send_message(uid, "❌ Kein Match gefunden.")
        return
    mid = row[0]
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("🏆 Gewonnen", callback_data=f"res_win_{mid}"),
        InlineKeyboardButton("❌ Verloren", callback_data=f"res_lose_{mid}"),
        InlineKeyboardButton("🤝 Unentschieden", callback_data=f"res_draw_{mid}")
    )
    bot.send_message(uid, "🧾 Was ist dein Ergebnis?", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("res_"))
def result_handler(call):
    uid = call.from_user.id
    _, res, mid = call.data.split("_")

    cur.execute("SELECT p1, p2 FROM matches WHERE match_id=?", (mid,))
    row = cur.fetchone()
    if not row:
        bot.send_message(uid, "❌ Match nicht gefunden.")
        return
    p1, p2 = row

    col = 'result1' if uid == p1 else 'result2'
    cur.execute(f"UPDATE matches SET {col}=? WHERE match_id=?", (res, mid))
    conn.commit()

    cur.execute("SELECT result1, result2, stake FROM matches WHERE match_id=?", (mid,))
    r1, r2, stake = cur.fetchone()

    if r1 and r2:
        if r1 == r2 == 'draw':
            for p in [p1, p2]:
                add_balance(p, stake)
            msg = "🤝 Unentschieden! Beide erhalten den Einsatz zurück."
        elif r1 == 'win' and r2 == 'lose':
            add_balance(p1, stake * 2)
            msg = f"🏆 @{call.from_user.username} hat gewonnen!"
        elif r2 == 'win' and r1 == 'lose':
            add_balance(p2, stake * 2)
            msg = f"🏆 @{call.from_user.username} hat gewonnen!"
        else:
            msg = "⚠️ Streitfall! Admin wird informiert."
            bot.send_message(ADMIN_ID, f"🚨 Streitfall im Match {mid} zwischen {p1} und {p2}")
        bot.send_message(p1, msg)
        bot.send_message(p2, msg)
        cur.execute("DELETE FROM matches WHERE match_id=?", (mid,))
        conn.commit()
    else:
        bot.send_message(uid, "✅ Ergebnis gespeichert. Warte auf den Gegner.")

def get_tx_details(sig):
    try:
        payload = {
            "jsonrpc":"2.0",
            "id":1,
            "method":"getTransaction",
            "params":[sig, {"encoding":"jsonParsed"}]
        }
        r = requests.post(RPC_URL, json=payload).json()
        instr = r['result']['transaction']['message']['instructions']
        for i in instr:
            if i.get('program') == 'system':
                info = i['parsed']['info']
                lamports = int(info['lamports'])
                return {"from": info['source'], "amount": lamports / 1e9}
    except:
        return None

def check_payments():
    while True:
        try:
            payload = {
                "jsonrpc":"2.0",
                "id":1,
                "method":"getSignaturesForAddress",
                "params":[BOT_WALLET, {"limit":30}]
            }
            r = requests.post(RPC_URL, json=payload).json()
            for tx in r.get("result", []):
                sig = tx['signature']
                if sig in checked_signatures:
                    continue
                checked_signatures.add(sig)
                txdata = get_tx_details(sig)
                if not txdata: continue
                sender = txdata['from']
                amount = txdata['amount']

                # Einzahlung prüfen
                cur.execute("SELECT user_id FROM users WHERE wallet=?", (sender,))
                row = cur.fetchone()
                if row:
                    add_balance(row[0], amount)
                    bot.send_message(row[0], f"✅ Einzahlung erkannt: {amount:.4f} SOL")
                    continue

                # Match-Zahlung prüfen
                cur.execute("SELECT match_id, p1, p2, wallet1, wallet2, paid1, paid2, stake FROM matches")
                for match in cur.fetchall():
                    mid, p1, p2, w1, w2, paid1, paid2, stake = match
                    if sender == w1 and not paid1 and amount >= stake:
                        cur.execute("UPDATE matches SET paid1=1 WHERE match_id=?", (mid,))
                        conn.commit()
                        bot.send_message(p1, f"✅ Zahlung über {amount:.4f} SOL erkannt.")
                    elif sender == w2 and not paid2 and amount >= stake:
                        cur.execute("UPDATE matches SET paid2=1 WHERE match_id=?", (mid,))
                        conn.commit()
                        bot.send_message(p2, f"✅ Zahlung über {amount:.4f} SOL erkannt.")
        except Exception as e:
            print("Zahlungsprüfung Fehler:", e)
        time.sleep(30)

# Starte Background-Thread
threading.Thread(target=check_payments, daemon=True).start()
print("🤖 Bot läuft...")
bot.infinity_polling()