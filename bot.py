import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import time
import threading
import requests

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
    winner INTEGER DEFAULT NULL
)''')
db.commit()

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

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
        InlineKeyboardButton("🔴 🎮 Match starten", callback_data="start_match"),
        InlineKeyboardButton("🔵 💰 Guthaben", callback_data="balance"),
        InlineKeyboardButton("🔴 📥 Einzahlung", callback_data="deposit"),
        InlineKeyboardButton("🔵 📤 Auszahlung", callback_data="withdraw"),
        InlineKeyboardButton("🏠 Home", callback_data="home")
    )
    bot.send_message(uid, "🏠 Hauptmenü - Versus Arena", reply_markup=markup)

@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id
    uname = msg.from_user.username or f"user{uid}"
    cur.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (uid, uname))
    db.commit()
    bot.send_message(uid, "🔥 Willkommen bei <b>Versus Arena</b>! 🔥")
    main_menu(uid)

@bot.message_handler(commands=['home'])
def home(msg):
    uid = msg.from_user.id
    cur.execute("SELECT username, balance, wallet FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    if not r:
        bot.send_message(uid, "❌ Benutzer nicht gefunden. Bitte /start eingeben.")
        return
    username, balance, wallet = r
    wallet_text = wallet if wallet else "Keine Wallet gespeichert"
    text = (f"👤 Benutzer: <b>@{username}</b>\n"
            f"💰 Guthaben: <b>{balance:.4f} SOL</b>\n"
            f"🔑 Wallet: <code>{wallet_text}</code>")
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🏠 Home", callback_data="home"))
    bot.send_message(uid, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: True)
def handle_callback(call):
    uid = call.from_user.id
    data = call.data

    if data == "start_match":
        markup = InlineKeyboardMarkup()
        for i, g in enumerate(games):
            emoji = "🔴" if i % 2 == 0 else "🔵"
            markup.add(InlineKeyboardButton(f"{emoji} {g}", callback_data=f"game_{g}"))
        bot.edit_message_text("🎮 Spiel auswählen:", uid, call.message.message_id, reply_markup=markup)

    elif data.startswith("game_"):
        game = data[5:]
        states[uid] = {'step': 'opponent', 'game': game}
        bot.send_message(uid, "👤 Gegner-Username (ohne @):")

    elif data == "balance":
        bal = get_balance(uid)
        bot.send_message(uid, f"💰 Dein Guthaben: <b>{bal:.4f} SOL</b>")

    elif data == "deposit":
        cur.execute("SELECT wallet FROM users WHERE user_id=?", (uid,))
        wallet = cur.fetchone()[0]
        if not wallet:
            states[uid] = {'step': 'deposit_wallet'}
            bot.send_message(uid, "🔑 Bitte sende deine Wallet-Adresse für Einzahlungen:")
        else:
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

    elif data == "home":
        # Home Callback
        cur.execute("SELECT username, balance, wallet FROM users WHERE user_id=?", (uid,))
        r = cur.fetchone()
        if not r:
            bot.answer_callback_query(call.id, "❌ Benutzer nicht gefunden.")
            return
        username, balance, wallet = r
        wallet_text = wallet if wallet else "Keine Wallet gespeichert"
        text = (f"👤 Benutzer: <b>@{username}</b>\n"
                f"💰 Guthaben: <b>{balance:.4f} SOL</b>\n"
                f"🔑 Wallet: <code>{wallet_text}</code>")
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🏠 Home", callback_data="home"))
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=markup)

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
            state['step'] = 'pay_method'
            bot.send_message(uid, "💳 Möchtest du mit deinem Guthaben zahlen? Antworte mit 'ja' oder 'nein'.")
        except:
            bot.send_message(uid, "❌ Ungültiger Betrag.")

    elif state['step'] == 'pay_method':
        answer = msg.text.strip().lower()
        if answer == 'ja':
            bal = get_balance(uid)
            if bal < state['stake']:
                bot.send_message(uid, f"❌ Dein Guthaben ({bal:.4f} SOL) reicht nicht aus.")
                return
            state['pay_with_balance'] = True
            state['step'] = 'wallet'
            bot.send_message(uid, "🔑 Bitte gib deine Wallet-Adresse an (für Match-Tracking):")
        elif answer == 'nein':
            state['pay_with_balance'] = False
            state['step'] = 'wallet'
            bot.send_message(uid, "🔑 Bitte gib deine Wallet-Adresse an:")
        else:
            bot.send_message(uid, "❌ Bitte antworte mit 'ja' oder 'nein'.")

    elif state['step'] == 'wallet':
        wallet = msg.text.strip()
        cur.execute("UPDATE users SET wallet=? WHERE user_id=?", (wallet, uid))
        db.commit()
        mid = str(int(time.time()))
        opp = state['opponent']
        pay_with_balance = state.get('pay_with_balance', False)

        cur.execute("""
            INSERT INTO matches (match_id, p1, p2, game, stake, wallet1, wallet2, paid1, paid2, winner)
            VALUES (?, ?, ?, ?, ?, ?, '', 0, 0, NULL)
        """, (mid, uid, opp, state['game'], state['stake'], wallet))
        db.commit()

        if pay_with_balance:
            # Guthaben abziehen & Match als bezahlt markieren
            cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (state['stake'], uid))
            cur.execute("UPDATE matches SET paid1=1 WHERE match_id=?", (mid,))
            db.commit()
            bot.send_message(uid, f"✅ Du hast mit deinem Guthaben bezahlt. Das Match wird gestartet.")
        else:
            bot.send_message(uid, f"✅ Bitte sende {state['stake']} SOL an:\n<code>{BOT_WALLET}</code>")

        challenger_name = get_username(uid)
        states[opp] = {'step': 'wallet_join', 'match_id': mid}
        bot.send_message(opp, f"🎮 Du wurdest von <b>@{challenger_name}</b> herausgefordert!\n"
                              f"Spiel: {state['game']}\n"
                              f"Einsatz: {state['stake']} SOL\n"
                              f"Bitte sende deine Wallet-Adresse:")

        states.pop(uid)

    elif state['step'] == 'wallet_join':
        wallet = msg.text.strip()
        mid = state['match_id']
        cur.execute("UPDATE matches SET wallet2=? WHERE match_id=?", (wallet, mid))
        cur.execute("UPDATE users SET wallet=? WHERE user_id=?", (wallet, uid))
        db.commit()

        # Gegner nach Zahlungsmethode fragen
        states[uid] = {'step': 'pay_method_join', 'match_id': mid}
        bot.send_message(uid, "💳 Möchtest du mit deinem Guthaben zahlen? Antworte mit 'ja' oder 'nein'.")

    elif state['step'] == 'pay_method_join':
        answer = msg.text.strip().lower()
        mid = state['match_id']
        cur.execute("SELECT stake FROM matches WHERE match_id=?", (mid,))
        stake = cur.fetchone()[0]

        if answer == 'ja':
            bal = get_balance(uid)
            if bal < stake:
                bot.send_message(uid, f"❌ Dein Guthaben ({bal:.4f} SOL) reicht nicht aus.")
                return
            cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (stake, uid))
            cur.execute("UPDATE matches SET paid2=1 WHERE match_id=?", (mid,))
            db.commit()
            bot.send_message(uid, f"✅ Du hast mit deinem Guthaben bezahlt. Das Match wird gestartet.")
        elif answer == 'nein':
            bot.send_message(uid, f"✅ Bitte sende {stake} SOL an:\n<code>{BOT_WALLET}</code>")
        else:
            bot.send_message(uid, "❌ Bitte antworte mit 'ja' oder 'nein'.")
            return
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

    elif state['step'] == 'deposit_wallet':
        wallet = msg.text.strip()
        cur.execute("UPDATE users SET wallet=? WHERE user_id=?", (wallet, uid))
        db.commit()
        bot.send_message(uid, f"✅ Wallet gespeichert.\nSende jetzt SOL an:\n<code>{BOT_WALLET}</code>")
        states.pop(uid)


# --- Solana-Zahlungserkennung ---
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

# --- Start ---
threading.Thread(target=check_payments, daemon=True).start()
print("🤖 Versus Arena Bot läuft...")
bot.infinity_polling()