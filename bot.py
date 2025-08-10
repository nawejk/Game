import os
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

def get_user_info_text(uid):
    cur.execute("SELECT username, balance, wallet FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    if not r:
        return "❌ User not found.\n\n"
    username, balance, wallet = r
    wallet_text = wallet if wallet else "No wallet saved"
    return (f"👤 <b>@{username}</b> | 💰 {balance:.4f} SOL | 🔑 {wallet_text}\n\n")

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
        bot.edit_message_text(menu_text, uid, call.message.message_id, reply_markup=markup, disable_web_page_preview=True)
    else:
        bot.send_message(uid, menu_text, reply_markup=markup, disable_web_page_preview=True)

@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id
    uname = msg.from_user.username or f"user{uid}"
    cur.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (uid, uname))
    db.commit()
    bot.send_message(uid, "🔥 Welcome to <b>Versus Arena</b>! 🔥")
    main_menu(uid)

@bot.callback_query_handler(func=lambda c: True)
def handle_callback(call):
    uid = call.from_user.id
    data = call.data

    if data == "start_match":
        markup = InlineKeyboardMarkup()
        for i, g in enumerate(games):
            emoji = "🔴" if i % 2 == 0 else "🔵"
            markup.add(InlineKeyboardButton(f"{emoji} {g}", callback_data=f"game_{g}"))
        user_info = get_user_info_text(uid)
        bot.edit_message_text(user_info + "🎮 Select a game:", uid, call.message.message_id, reply_markup=markup)

    elif data.startswith("game_"):
        game = data[5:]
        states[uid] = {'step': 'opponent', 'game': game}
        user_info = get_user_info_text(uid)
        bot.edit_message_text(user_info + "👤 Opponent username (without @):", uid, call.message.message_id)

    elif data == "balance":
        bal = get_balance(uid)
        user_info = get_user_info_text(uid)
        bot.edit_message_text(user_info + f"💰 Your balance: <b>{bal:.4f} SOL</b>", uid, call.message.message_id)

    elif data == "deposit":
        cur.execute("SELECT wallet FROM users WHERE user_id=?", (uid,))
        wallet = cur.fetchone()[0]
        user_info = get_user_info_text(uid)
        if not wallet:
            states[uid] = {'step': 'deposit_wallet'}
            bot.edit_message_text(user_info + "🔑 Please send your wallet address for deposits:", uid, call.message.message_id)
        else:
            bot.edit_message_text(user_info + f"📥 Send SOL to:\n<code>{BOT_WALLET}</code>", uid, call.message.message_id)

    elif data == "withdraw":
        states[uid] = {'step': 'withdraw'}
        user_info = get_user_info_text(uid)
        bot.edit_message_text(user_info + "💸 Enter amount to withdraw:", uid, call.message.message_id)

    elif data.startswith("win_"):
        mid = data.split("_")[1]
        cur.execute("SELECT p1, p2, stake, winner FROM matches WHERE match_id=?", (mid,))
        match = cur.fetchone()
        if not match:
            bot.send_message(uid, "❌ Match not found.")
            return
        p1, p2, stake, winner = match
        if winner:
            bot.send_message(uid, "⚠️ A winner has already been reported.")
            return

        cur.execute("UPDATE matches SET winner=? WHERE match_id=?", (uid, mid))
        add_balance(uid, stake * 2)
        db.commit()
        bot.send_message(uid, "🏆 You won! Your balance has been credited.")

        opponent = p2 if uid == p1 else p1
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("❗ Report issue", callback_data=f"dispute_{mid}"))
        bot.send_message(opponent, f"⚠️ @{get_username(uid)} has reported victory.\nIf you have an issue, please report:", reply_markup=markup)

    elif data.startswith("dispute_"):
        mid = data.split("_")[1]
        bot.send_message(ADMIN_ID, f"🚨 Dispute in match {mid}: A player reported an issue.")
        bot.send_message(uid, "📨 The admin has been informed. Please send any evidence if necessary.")

def handle_result_button(uid, mid):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🏆 I won", callback_data=f"win_{mid}"))
    bot.send_message(uid, "❓ Report result:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.from_user.id in states)
def state_handler(msg):
    uid = msg.from_user.id
    state = states[uid]

    if state['step'] == 'opponent':
        opponent = msg.text.strip().lstrip("@")
        cur.execute("SELECT user_id FROM users WHERE username=?", (opponent,))
        r = cur.fetchone()
        if not r:
            bot.send_message(uid, "❌ Opponent not found.")
            return
        state['opponent'] = r[0]
        state['step'] = 'stake'
        user_info = get_user_info_text(uid)
        bot.send_message(uid, user_info + "💵 Stake amount in SOL:")

    elif state['step'] == 'stake':
        try:
            stake = float(msg.text.strip())
            state['stake'] = stake
            state['step'] = 'pay_method'
            user_info = get_user_info_text(uid)
            bot.send_message(uid, user_info + "💳 Do you want to pay with your balance? Reply 'yes' or 'no'.")
        except:
            bot.send_message(uid, "❌ Invalid amount.")

    elif state['step'] == 'pay_method':
        answer = msg.text.strip().lower()
        if answer == 'yes':
            bal = get_balance(uid)
            if bal < state['stake']:
                bot.send_message(uid, f"❌ Your balance ({bal:.4f} SOL) is insufficient.")
                return
            state['pay_with_balance'] = True
            state['step'] = 'wallet'
            user_info = get_user_info_text(uid)
            bot.send_message(uid, user_info + "🔑 Please provide your wallet address (for match tracking):")
        elif answer == 'no':
            state['pay_with_balance'] = False
            state['step'] = 'wallet'
            user_info = get_user_info_text(uid)
            bot.send_message(uid, user_info + "🔑 Please provide your wallet address:")
        else:
            bot.send_message(uid, "❌ Please reply with 'yes' or 'no'.")

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
            cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (state['stake'], uid))
            cur.execute("UPDATE matches SET paid1=1 WHERE match_id=?", (mid,))
            db.commit()
            bot.send_message(uid, f"✅ You paid with your balance. The match will start soon.")
        else:
            bot.send_message(uid, f"✅ Please send {state['stake']} SOL to:\n<code>{BOT_WALLET}</code>")

        challenger_name = get_username(uid)
        states[opp] = {'step': 'wallet_join', 'match_id': mid}
        bot.send_message(opp, f"🎮 You have been challenged by <b>@{challenger_name}</b>!\n"
                              f"Game: {state['game']}\n"
                              f"Stake: {state['stake']} SOL\n"
                              f"Please send your wallet address:")

        states.pop(uid)

    elif state['step'] == 'wallet_join':
        wallet = msg.text.strip()
        mid = state['match_id']
        cur.execute("UPDATE matches SET wallet2=? WHERE match_id=?", (wallet, mid))
        cur.execute("UPDATE users SET wallet=? WHERE user_id=?", (wallet, uid))
        db.commit()
        states[uid] = {'step': 'pay_method_join', 'match_id': mid}
        user_info = get_user_info_text(uid)
        bot.send_message(uid, user_info + "💳 Do you want to pay with your balance? Reply 'yes' or 'no'.")

    elif state['step'] == 'pay_method_join':
        answer = msg.text.strip().lower()
        mid = state['match_id']
        cur.execute("SELECT stake FROM matches WHERE match_id=?", (mid,))
        stake = cur.fetchone()[0]
        if answer == 'yes':
            bal = get_balance(uid)
            if bal < stake:
                bot.send_message(uid, f"❌ Your balance ({bal:.4f} SOL) is insufficient.")
                return
            cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (stake, uid))
            cur.execute("UPDATE matches SET paid2=1 WHERE match_id=?", (mid,))
            db.commit()
            bot.send_message(uid, f"✅ You paid with your balance. The match will start soon.")
        elif answer == 'no':
            bot.send_message(uid, f"✅ Please send {stake} SOL to:\n<code>{BOT_WALLET}</code>")
        else:
            bot.send_message(uid, "❌ Please reply with 'yes' or 'no'.")
            return
        states.pop(uid)

    elif state['step'] == 'withdraw':
        try:
            amount = float(msg.text.strip())
            bal = get_balance(uid)
            if amount > bal:
                bot.send_message(uid, "❌ Insufficient balance.")
                return
            cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, uid))
            db.commit()
            bot.send_message(uid, "✅ Your withdrawal is being processed (1–2 hours).")
            bot.send_message(ADMIN_ID, f"📤 Withdrawal request from @{get_username(uid)} for {amount} SOL.")
            states.pop(uid)
        except:
            bot.send_message(uid, "❌ Invalid amount.")

    elif state['step'] == 'deposit_wallet':
        wallet = msg.text.strip()
        cur.execute("UPDATE users SET wallet=? WHERE user_id=?", (wallet, uid))
        db.commit()
        user_info = get_user_info_text(uid)
        bot.send_message(uid, user_info + f"✅ Wallet saved.\nNow send SOL to:\n<code>{BOT_WALLET}</code>")
        states.pop(uid)

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
                cur.execute("SELECT user_id FROM users WHERE wallet=?", (sender,))
                u = cur.fetchone()
                if u:
                    add_balance(u[0], amount)
                    bot.send_message(u[0], f"✅ Deposit detected: {amount:.4f} SOL")
                    continue
                cur.execute("SELECT match_id, p1, p2, wallet1, wallet2, paid1, paid2, stake FROM matches")
                for m in cur.fetchall():
                    mid, p1, p2, w1, w2, pd1, pd2, stake = m
                    updated = False
                    if sender == w1 and not pd1 and amount >= stake:
                        cur.execute("UPDATE matches SET paid1=1 WHERE match_id=?", (mid,))
                        bot.send_message(p1, f"✅ Payment received. Waiting for opponent.")
                        updated = True
                    elif sender == w2 and not pd2 and amount >= stake:
                        cur.execute("UPDATE matches SET paid2=1 WHERE match_id=?", (mid,))
                        bot.send_message(p2, f"✅ Payment received. Waiting for opponent.")
                        updated = True
                    db.commit()
                    if updated:
                        cur.execute("SELECT paid1, paid2 FROM matches WHERE match_id=?", (mid,))
                        paid1, paid2 = cur.fetchone()
                        if paid1 and paid2:
                            # NEW: Notify both players to start match
                            start_markup = InlineKeyboardMarkup()
                            start_markup.add(InlineKeyboardButton("🏁 Finish & Report Result", callback_data=f"result_{mid}"))
                            bot.send_message(p1, f"✅ Both players have paid.\nYou can start your match now!", reply_markup=start_markup)
                            bot.send_message(p2, f"✅ Both players have paid.\nYou can start your match now!", reply_markup=start_markup)
                            bot.send_message(ADMIN_ID, f"✅ Both players have paid for match {mid}.")
                            bot.send_message(ADMIN_ID_2, f"✅ Both players have paid for match {mid}.")
        except Exception as e:
            print("Payment check error:", e)
        time.sleep(5)

print("🤖 Versus Arena Bot running...")
threading.Thread(target=check_payments, daemon=True).start()
bot.infinity_polling()