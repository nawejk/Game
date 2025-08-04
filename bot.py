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

# --- DB Setup
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
    winner INTEGER DEFAULT NULL
)''')
db.commit()

states = {}
checked_signatures = set()
games = ['FIFA', 'Fortnite', 'Call of Duty', 'Mario Kart']

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
        InlineKeyboardButton("🎮 Match starten", callback_data="start_match"),
        InlineKeyboardButton("💰 Guthaben", callback_data="balance"),
        InlineKeyboardButton("📥 Einzahlung", callback_data="deposit"),
        InlineKeyboardButton("📤 Auszahlung", callback_data="withdraw")
    )
    bot.send_message(uid, "🏠 Hauptmenü", reply_markup=markup)

@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id
    uname = msg.from_user.username or f"user{uid}"
    cur.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (uid, uname))
    db.commit()
    main_menu(uid)

@bot.callback_query_handler(func=lambda c: True)
def handle_callback(call):
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
        bot.send_message(uid, f"📥 Sende SOL an:\n<code>{BOT_WALLET}</code>")

    elif data == "withdraw":
        states[uid] = {'step': 'withdraw'}
        bot.send_message(uid, "💸 Betrag zur Auszahlung:")

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

        # Gewinner festlegen
        cur.execute("UPDATE matches SET winner=? WHERE match_id=?", (uid, mid))
        add_balance(uid, stake * 2)
        db.commit()
        bot.send_message(uid, "🏆 Du hast gewonnen! Guthaben wurde gutgeschrieben.")

        opponent = p2 if uid == p1 else p1
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("❗ Problem melden", callback_data=f"dispute_{mid}"))
        bot.send_message(opponent, f"⚠️ @{get_username(uid)} hat sich als Gewinner gemeldet.\nWenn du ein Problem hast, melde es:", reply_markup=markup)

    elif data.startswith("dispute_"):
        mid = data.split("_")[1]
        bot.send_message(ADMIN_ID, f"🚨 Streitfall Match {mid}: Ein Spieler meldet ein Problem.")
        bot.send_message(uid, "📨 Der Admin wurde informiert. Bitte ggf. Beweise senden.")

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
        opp = state['opponent']
        cur.execute("INSERT INTO matches VALUES (?, ?, ?, ?, ?, ?, '', 0, 0, NULL)",
            (mid, uid, opp, state['game'], state['stake'], wallet))
        db.commit()
        states[opp] = {'step': 'wallet_join', 'match_id': mid}
        bot.send_message(opp, f"🎮 Du wurdest herausgefordert!\nSpiel: {state['game']}\nEinsatz: {state['stake']} SOL\nBitte sende deine Wallet-Adresse:")
        bot.send_message(uid, f"✅ Sende {state['stake']} SOL an:\n<code>{BOT_WALLET}</code>")
        states.pop(uid)

    elif state['step'] == 'wallet_join':
        wallet = msg.text.strip()
        mid = state['match_id']
        cur.execute("UPDATE matches SET wallet2=? WHERE match_id=?", (wallet, mid))
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
            cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, uid))
            db.commit()
            bot.send_message(uid, "✅ Deine Auszahlung wird bearbeitet (1–2 Stunden).")
            bot.send_message(ADMIN_ID, f"📤 Auszahlung von @{get_username(uid)} über {amount} SOL.")
            states.pop(uid)
        except:
            bot.send_message(uid, "❌ Ungültiger Betrag.")

# --- Solana-Zahlungserkennung
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
                "params":[BOT_WALLET, {"limit": 25}]
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
                # normale Einzahlung
                cur.execute("SELECT user_id FROM users WHERE wallet=?", (sender,))
                u = cur.fetchone()
                if u:
                    add_balance(u[0], amount)
                    bot.send_message(u[0], f"✅ Einzahlung erkannt: {amount:.4f} SOL")
                    continue
                # Match-Zahlung
                cur.execute("SELECT match_id, p1, p2, wallet1, wallet2, paid1, paid2, stake FROM matches")
                for m in cur.fetchall():
                    mid, p1, p2, w1, w2, pd1, pd2, stake = m
                    updated = False
                    if sender == w1 and not pd1 and amount >= stake:
                        cur.execute("UPDATE matches SET paid1=1 WHERE match_id=?", (mid,))
                        bot.send_message(p1, f"✅ Zahlung erhalten. Match startet bald.")
                        updated = True
                    elif sender == w2 and not pd2 and amount >= stake:
                        cur.execute("UPDATE matches SET paid2=1 WHERE match_id=?", (mid,))
                        bot.send_message(p2, f"✅ Zahlung erhalten. Match startet bald.")
                        updated = True
                    db.commit()
                    if updated:
                        cur.execute("SELECT paid1, paid2 FROM matches WHERE match_id=?", (mid,))
                        if all(cur.fetchone()):
                            handle_result_button(p1, mid)
                            handle_result_button(p2, mid)
        except Exception as e:
            print("Fehler bei Zahlungserkennung:", e)
        time.sleep(5)

# --- Start
threading.Thread(target=check_payments, daemon=True).start()
print("🤖 Bot läuft...")
bot.infinity_polling()