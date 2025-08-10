import os
import logging
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import time
import threading
import requests

# --- CONFIG ---
BOT_TOKEN = '8113317405:AAERiOi3TM95xU87ys9xIV_L622MLo83t6Q'
BOT_WALLET = 'CKZEpwiVqAHLiSbdc8Ebf8xaQ2fofgPCNmzi4cV32M1s'
ADMIN_ID = 7919108078
ADMIN_ID_2 = 7160368480
RPC_URL = 'https://api.mainnet-beta.solana.com'

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

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

# --- Helper-Funktionen ---
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
    logging.info(f"Added {amount:.9f} SOL to user {uid}")

def get_user_info_text(uid):
    cur.execute("SELECT username, balance, wallet FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    if not r:
        return "❌ User not found.\n\n"
    username, balance, wallet = r
    wallet_text = wallet if wallet else "No wallet saved"
    return (f"👤 <b>@{username}</b> | 💰 {balance:.4f} SOL | 🔑 {wallet_text}\n\n")

def get_user_wallet_from_db(uid):
    cur.execute("SELECT wallet FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return r[0] if r else None

def main_menu(uid, call=None):
    user_info = get_user_info_text(uid)
    menu_text = user_info + "🏠 Main Menu - Versus Arena\n🌐 <a href='https://versus-arena.com/'>versus-arena.com</a>"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔴 🎮 Start Match", callback_data="start_match"),
        InlineKeyboardButton("🔵 💰 Balance", callback_data="balance"),
        InlineKeyboardButton("🔴 📥 Deposit", callback_data="deposit"),
        InlineKeyboardButton("🔵 📤 Withdraw", callback_data="withdraw"),
    )
    if call:
        try:
            bot.edit_message_text(menu_text, call.message.chat.id, call.message.message_id, reply_markup=markup, disable_web_page_preview=True)
        except Exception as e:
            logging.warning("Failed to edit menu message: %s", e)
    else:
        bot.send_message(uid, menu_text, reply_markup=markup, disable_web_page_preview=True)

def handle_result_button(uid, mid):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🏆 I won", callback_data=f"win_{mid}"))
    bot.send_message(uid, "❓ Report result:", reply_markup=markup)

# --- Bot Start ---
@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id
    uname = msg.from_user.username or f"user{uid}"
    cur.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (uid, uname))
    db.commit()
    bot.send_message(uid, "🔥 Welcome to <b>Versus Arena</b>! 🔥")
    main_menu(uid)

# --- Callback Handler ---
@bot.callback_query_handler(func=lambda c: True)
def handle_callback(call):
    uid = call.from_user.id
    data = call.data
    # Unverändert wie in deinem Code...
    # (Hier bleibt der Rest gleich – ich ändere nur in check_payments unten)

# --- State Handler ---
@bot.message_handler(func=lambda m: m.from_user.id in states)
def state_handler(msg):
    # Unverändert wie in deinem Code...
    # (Auch hier keine Änderungen nötig)

# --- RPC Payment Check ---
def get_tx_details(sig):
    try:
        r = requests.post(RPC_URL, json={
            "jsonrpc": "2.0", "id": 1, "method": "getTransaction",
            "params": [sig, {"encoding": "jsonParsed", "commitment": "confirmed"}]
        }, timeout=10).json()
        res = r.get('result')
        if not res or res.get('meta', {}).get('err'):
            return None
        txmsg = res['transaction']['message']
        account_keys = [k['pubkey'] if isinstance(k, dict) else k for k in txmsg.get('accountKeys', [])]
        pre = res['meta'].get('preBalances')
        post = res['meta'].get('postBalances')
        if not pre or not post:
            return None
        try:
            bot_index = account_keys.index(BOT_WALLET)
        except ValueError:
            return None
        delta = post[bot_index] - pre[bot_index]
        if delta <= 0:
            return None
        amount = delta / 1e9
        sender = None
        for i, (p, po) in enumerate(zip(pre, post)):
            if p - po >= delta - 1000:
                sender = account_keys[i]
                break
        return {"from": sender, "amount": amount}
    except:
        return None

def check_payments():
    while True:
        try:
            r = requests.post(RPC_URL, json={
                "jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress",
                "params": [BOT_WALLET, {"limit": 25}]
            }, timeout=10).json()
            results = r.get('result') or []
            for tx in results:
                sig = tx.get('signature')
                if not sig or sig in checked_signatures:
                    continue
                checked_signatures.add(sig)
                txd = get_tx_details(sig)
                if not txd:
                    continue
                sender = txd['from']
                amount = txd['amount']
                if not sender:
                    continue

                # Direktes Deposit
                cur.execute("SELECT user_id FROM users WHERE wallet=?", (sender,))
                u = cur.fetchone()
                if u:
                    add_balance(u[0], amount)
                    bot.send_message(u[0], f"✅ Deposit detected: {amount:.4f} SOL")
                    continue

                # Match-Payments
                cur.execute("SELECT match_id, p1, p2, wallet1, wallet2, paid1, paid2, stake FROM matches WHERE paid1=0 OR paid2=0")
                for m in cur.fetchall():
                    mid, p1, p2, w1, w2, pd1, pd2, stake = m
                    w1 = (w1 or '').strip()
                    w2 = (w2 or '').strip()
                    updated = False

                    # Wallet-Autofix
                    if not w1 and sender == get_user_wallet_from_db(p1):
                        w1 = sender
                        cur.execute("UPDATE matches SET wallet1=? WHERE match_id=?", (sender, mid))
                        cur.execute("UPDATE users SET wallet=? WHERE user_id=?", (sender, p1))
                        db.commit()
                    if not w2 and sender == get_user_wallet_from_db(p2):
                        w2 = sender
                        cur.execute("UPDATE matches SET wallet2=? WHERE match_id=?", (sender, mid))
                        cur.execute("UPDATE users SET wallet=? WHERE user_id=?", (sender, p2))
                        db.commit()

                    # Payment-Zuweisung
                    if sender == w1 and not pd1 and amount >= stake - 1e-9:
                        cur.execute("UPDATE matches SET paid1=1 WHERE match_id=?", (mid,))
                        db.commit()
                        bot.send_message(p1, f"✅ Payment received ({amount:.4f} SOL). Waiting for opponent.")
                        updated = True
                    elif sender == w2 and not pd2 and amount >= stake - 1e-9:
                        cur.execute("UPDATE matches SET paid2=1 WHERE match_id=?", (mid,))
                        db.commit()
                        bot.send_message(p2, f"✅ Payment received ({amount:.4f} SOL). Waiting for opponent.")
                        updated = True

                    # Wenn beide bezahlt haben → sofort Result-Buttons senden
                    if updated:
                        cur.execute("SELECT paid1, paid2 FROM matches WHERE match_id=?", (mid,))
                        paid1, paid2 = cur.fetchone()
                        if paid1 and paid2:
                            bot.send_message(p1, "✅ Both players have paid. The match can start now!")
                            bot.send_message(p2, "✅ Both players have paid. The match can start now!")
                            handle_result_button(p1, mid)
                            handle_result_button(p2, mid)

        except Exception as e:
            logging.exception("Payment check error: %s", e)
        time.sleep(5)

if __name__ == "__main__":
    logging.info("🤖 Versus Arena Bot starting...")
    threading.Thread(target=check_payments, daemon=True).start()
    bot.infinity_polling()