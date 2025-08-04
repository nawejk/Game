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
    stake REAL,
    p1_wallet TEXT,
    p2_wallet TEXT,
    paid1 INTEGER DEFAULT 0,
    paid2 INTEGER DEFAULT 0,
    winner INTEGER DEFAULT NULL,
    resolved INTEGER DEFAULT 0
)''')
conn.commit()

games = ['FIFA', 'Fortnite', 'Call of Duty', 'Mario Kart']
user_states = {}

def get_username(uid):
    cur.execute("SELECT username FROM users WHERE user_id=?", (uid,))
    row = cur.fetchone()
    return row[0] if row else f'user{uid}'

def main_menu(uid):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🎮 Match starten", callback_data="start_match"))
    markup.add(InlineKeyboardButton("💰 Guthaben", callback_data="balance"))
    markup.add(InlineKeyboardButton("📤 Auszahlung", callback_data="withdraw"))
    bot.send_message(uid, "🏠 Hauptmenü", reply_markup=markup)

@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id
    uname = msg.from_user.username or f'user{uid}'
    cur.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (uid, uname))
    conn.commit()
    main_menu(uid)

@bot.callback_query_handler(func=lambda call: True)
def handle_menu(call):
    uid = call.from_user.id
    data = call.data

    if data == "start_match":
        markup = InlineKeyboardMarkup()
        for g in games:
            markup.add(InlineKeyboardButton(g, callback_data=f"game_{g}"))
        bot.send_message(uid, "🎮 Wähle ein Spiel:", reply_markup=markup)

    elif data.startswith("game_"):
        game = data[5:]
        user_states[uid] = {"step": "get_opponent", "game": game}
        bot.send_message(uid, "👤 Gib den Telegram-Username deines Gegners ein (ohne @):")

    elif data == "balance":
        cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
        bal = cur.fetchone()[0]
        bot.send_message(uid, f"💼 Dein Guthaben: <b>{bal:.4f} SOL</b>", parse_mode="HTML")

    elif data == "withdraw":
        bot.send_message(uid, "💸 Betrag zur Auszahlung?")
        user_states[uid] = {"step": "withdraw"}

@bot.message_handler(func=lambda m: m.from_user.id in user_states)
def handle_state(msg):
    uid = msg.from_user.id
    state = user_states[uid]

    if state["step"] == "get_opponent":
        opponent = msg.text.strip().lstrip('@')
        cur.execute("SELECT user_id FROM users WHERE username=?", (opponent,))
        row = cur.fetchone()
        if not row:
            bot.send_message(uid, "❌ Gegner nicht gefunden. Beide müssen /start eingegeben haben.")
            user_states.pop(uid)
            return
        state["opponent_id"] = row[0]
        state["step"] = "stake"
        bot.send_message(uid, "💵 Einsatz in SOL:")

    elif state["step"] == "stake":
        try:
            stake = float(msg.text.strip())
            state["stake"] = stake
            state["step"] = "wallet"
            bot.send_message(uid, "🔑 Deine Wallet-Adresse (Absender):")
        except:
            bot.send_message(uid, "❌ Ungültiger Betrag.")

    elif state["step"] == "wallet":
        match_id = str(int(time.time()))
        p1 = uid
        p2 = state["opponent_id"]
        game = state["game"]
        stake = state["stake"]
        p1_wallet = msg.text.strip()

        cur.execute("INSERT INTO matches (match_id, p1, p2, stake, p1_wallet) VALUES (?, ?, ?, ?, ?)",
                    (match_id, p1, p2, stake, p1_wallet))
        conn.commit()

        user_states[p2] = {"step": "wallet_join", "match_id": match_id}
        bot.send_message(p2, f"🎮 Du wurdest herausgefordert zu <b>{game}</b>\n💵 Einsatz: {stake} SOL\nBitte sende deine Wallet-Adresse (Absender):", parse_mode='HTML')
        bot.send_message(p1, f"✅ Match erstellt. Sende {stake} SOL an:\n<code>{BOT_WALLET}</code>", parse_mode="HTML")
        user_states.pop(uid)

    elif state["step"] == "wallet_join":
        wallet = msg.text.strip()
        match_id = state["match_id"]
        cur.execute("UPDATE matches SET p2_wallet=? WHERE match_id=?", (wallet, match_id))
        conn.commit()
        bot.send_message(uid, f"✅ Wallet gespeichert. Sende den Einsatz an:\n<code>{BOT_WALLET}</code>", parse_mode="HTML")
        user_states.pop(uid)

    elif state["step"] == "withdraw":
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
            user_states.pop(uid)
        except:
            bot.send_message(uid, "❌ Ungültiger Betrag.")

@bot.message_handler(commands=['ergebnis'])
def cmd_ergebnis(msg):
    uid = msg.from_user.id
    cur.execute("SELECT match_id FROM matches WHERE (p1=? OR p2=?) AND paid1=1 AND paid2=1 AND resolved=0", (uid, uid))
    row = cur.fetchone()
    if not row:
        bot.send_message(uid, "❌ Kein aktives Match mit Zahlung.")
        return
    match_id = row[0]
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🏆 Ich habe gewonnen", callback_data=f"res_win_{match_id}"))
    markup.add(InlineKeyboardButton("❗ Unfair!", callback_data=f"res_unfair_{match_id}"))
    bot.send_message(uid, "❓ Was ist dein Ergebnis?", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("res_"))
def handle_result(call):
    uid = call.from_user.id
    action, match_id = call.data.split("_")[1:]
    cur.execute("SELECT p1, p2, stake, winner FROM matches WHERE match_id=?", (match_id,))
    row = cur.fetchone()
    if not row:
        bot.send_message(uid, "❌ Match nicht gefunden.")
        return
    p1, p2, stake, winner = row

    if action == "win":
        if winner:
            bot.send_message(uid, "❗ Gewinner steht schon fest.")
            return
        cur.execute("UPDATE matches SET winner=?, resolved=1 WHERE match_id=?", (uid, match_id))
        cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (stake * 2, uid))
        conn.commit()
        bot.send_message(uid, "✅ Du hast gewonnen. Guthaben gutgeschrieben.")
        other = p2 if uid == p1 else p1
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("❗ Unfair!", callback_data=f"res_unfair_{match_id}"))
        bot.send_message(other, "⚠️ Gegner hat Sieg gemeldet. Stimmst du zu?", reply_markup=markup)

    elif action == "unfair":
        bot.send_message(ADMIN_ID, f"🚨 Streitfall bei Match {match_id}. @{get_username(uid)} meldet 'Unfair!'.")
        bot.send_message(uid, "📩 Admin wurde benachrichtigt.")

def get_tx_details(sig):
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
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

checked_signatures = set()
def check_payments():
    while True:
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [BOT_WALLET, {"limit": 25}]
            }
            res = requests.post(RPC_URL, json=payload).json()
            for tx in res.get("result", []):
                sig = tx['signature']
                if sig in checked_signatures:
                    continue
                checked_signatures.add(sig)
                tx_data = get_tx_details(sig)
                if not tx_data:
                    continue
                sender, amount = tx_data['from'], tx_data['amount']
                cur.execute("SELECT match_id, p1, p2, p1_wallet, p2_wallet, paid1, paid2, stake FROM matches WHERE resolved=0")
                for row in cur.fetchall():
                    mid, p1, p2, w1, w2, paid1, paid2, stake = row
                    if sender == w1 and not paid1 and amount >= stake:
                        cur.execute("UPDATE matches SET paid1=1 WHERE match_id=?", (mid,))
                        bot.send_message(p1, "✅ Zahlung erkannt.")
                    elif sender == w2 and not paid2 and amount >= stake:
                        cur.execute("UPDATE matches SET paid2=1 WHERE match_id=?", (mid,))
                        bot.send_message(p2, "✅ Zahlung erkannt.")
                    conn.commit()
        except Exception as e:
            print("Fehler bei Zahlungserkennung:", e)
        time.sleep(5)

threading.Thread(target=check_payments, daemon=True).start()
print("🤖 Bot läuft...")
bot.infinity_polling()



 

              
            
            