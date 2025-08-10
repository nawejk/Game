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
    return f"👤 <b>@{username}</b> | 💰 {balance:.4f} SOL | 🔑 {wallet_text}\n\n"

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
        states[uid] = {'step': 'choose_game'}
        bot.send_message(uid, "Please enter the game you want to play:")
        bot.answer_callback_query(call.id)

    elif data == "balance":
        bal = get_balance(uid)
        bot.answer_callback_query(call.id, f"Your balance is {bal:.4f} SOL")
        main_menu(uid, call)

    elif data == "deposit":
        states[uid] = {'step': 'deposit_wallet'}
        bot.send_message(uid, "Please send your wallet address for deposit tracking:")
        bot.answer_callback_query(call.id)

    elif data == "withdraw":
        states[uid] = {'step': 'withdraw'}
        bot.send_message(uid, "Enter the amount of SOL you want to withdraw:")
        bot.answer_callback_query(call.id)

    elif data.startswith("win_"):
        match_id = data.split("_")[1]
        cur.execute("SELECT winner FROM matches WHERE match_id=?", (match_id,))
        r = cur.fetchone()
        if r and r[0] is None:
            cur.execute("UPDATE matches SET winner=? WHERE match_id=?", (uid, match_id))
            db.commit()
            bot.send_message(uid, f"Thanks for reporting your win for match {match_id}!")
            bot.answer_callback_query(call.id, "Result recorded.")
            main_menu(uid, call)
            bot.send_message(ADMIN_ID, f"Match {match_id} winner reported: @{get_username(uid)}")
        else:
            bot.answer_callback_query(call.id, "Result already reported or match not found.", show_alert=True)

def handle_result_button(uid, mid):
    try:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🏆 I won", callback_data=f"win_{mid}"))
        bot.send_message(uid, "❓ Report result:", reply_markup=markup)
    except Exception as e:
        print(f"[ERROR] Sending result button to user {uid}: {e}")

@bot.message_handler(func=lambda m: m.from_user.id in states)
def state_handler(msg):
    uid = msg.from_user.id
    text = msg.text.strip()
    state = states.get(uid, {})

    # --- START MATCH FLOW ---
    if state.get('step') == 'choose_game':
        if text not in games:
            bot.send_message(uid, f"Game not recognized. Please choose from: {', '.join(games)}")
            return
        state['game'] = text
        state['step'] = 'choose_opponent'
        bot.send_message(uid, "Enter the username of your opponent (without @):")

    elif state.get('step') == 'choose_opponent':
        cur.execute("SELECT user_id FROM users WHERE username=?", (text,))
        r = cur.fetchone()
        if not r:
            bot.send_message(uid, "User not found. Please enter a valid opponent username:")
            return
        if r[0] == uid:
            bot.send_message(uid, "You cannot challenge yourself. Enter another username:")
            return
        state['opponent'] = r[0]
        state['step'] = 'enter_stake'
        bot.send_message(uid, "Enter the stake amount in SOL:")

    elif state.get('step') == 'enter_stake':
        try:
            stake = float(text)
            if stake <= 0:
                raise ValueError
            state['stake'] = stake
            state['step'] = 'choose_payment_method'
            bot.send_message(uid, "Pay with balance? (yes/no)")
        except:
            bot.send_message(uid, "Invalid amount. Please enter a positive number:")

    elif state.get('step') == 'choose_payment_method':
        if text.lower() not in ['yes', 'no']:
            bot.send_message(uid, "Please answer with 'yes' or 'no':")
            return

        pay_with_balance = (text.lower() == 'yes')
        balance = get_balance(uid)

        if pay_with_balance and balance < state['stake']:
            bot.send_message(uid, f"Insufficient balance ({balance:.4f} SOL). Please answer 'no' or reduce stake.")
            return

        state['pay_with_balance'] = pay_with_balance
        state['step'] = 'enter_wallet'
        bot.send_message(uid, "Please enter your wallet address:")

    elif state.get('step') == 'enter_wallet':
        wallet = text
        # Save wallet to user
        cur.execute("UPDATE users SET wallet=? WHERE user_id=?", (wallet, uid))
        db.commit()

        # Create match_id
        match_id = str(int(time.time())) + str(uid)

        # Insert match with p1 = uid
        cur.execute("""INSERT INTO matches (match_id, p1, p2, game, stake, wallet1, paid1, paid2)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (match_id, uid, state['opponent'], state['game'], state['stake'], wallet, 0, 0))
        db.commit()

        # Handle payment for p1
        if state['pay_with_balance']:
            # Deduct balance immediately
            cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (state['stake'], uid))
            cur.execute("UPDATE matches SET paid1=1 WHERE match_id=?", (match_id,))
            db.commit()
            bot.send_message(uid, f"✅ You paid {state['stake']} SOL with your balance. Waiting for opponent payment...")
        else:
            bot.send_message(uid, f"✅ Please send {state['stake']} SOL to:\n<code>{BOT_WALLET}</code>")

        # Ask opponent for wallet
        states[state['opponent']] = {'step': 'enter_opponent_wallet', 'match_id': match_id}
        challenger_name = get_username(uid)
        bot.send_message(state['opponent'], f"You have been challenged by @{challenger_name}!\nGame: {state['game']}\nStake: {state['stake']} SOL\nPlease send your wallet address:")

        del states[uid]

    # --- OPPONENT WALLET & PAYMENT ---
    elif state.get('step') == 'enter_opponent_wallet':
        wallet = text
        match_id = state.get('match_id')
        cur.execute("UPDATE matches SET wallet2=? WHERE match_id=?", (wallet, match_id))
        cur.execute("UPDATE users SET wallet=? WHERE user_id=?", (wallet, uid))
        db.commit()
        states[uid] = {'step': 'choose_opponent_payment', 'match_id': match_id}
        bot.send_message(uid, "Pay with balance? (yes/no)")
        return

    elif state.get('step') == 'choose_opponent_payment':
        if text.lower() not in ['yes', 'no']:
            bot.send_message(uid, "Please answer with 'yes' or 'no':")
            return

        match_id = state.get('match_id')
        cur.execute("SELECT stake FROM matches WHERE match_id=?", (match_id,))
        r = cur.fetchone()
        if not r:
            bot.send_message(uid, "Match not found. Cancelled.")
            del states[uid]
            return
        stake = r[0]

        pay_with_balance = (text.lower() == 'yes')
        balance = get_balance(uid)

        if pay_with_balance and balance < stake:
            bot.send_message(uid, f"Insufficient balance ({balance:.4f} SOL). Please answer 'no' or top up your balance.")
            return

        if pay_with_balance:
            cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (stake, uid))
            cur.execute("UPDATE matches SET paid2=1 WHERE match_id=?", (match_id,))
            db.commit()
            bot.send_message(uid, f"✅ You paid {stake} SOL with your balance. Match will start soon.")
        else:
            bot.send_message(uid, f"✅ Please send {stake} SOL to:\n<code>{BOT_WALLET}</code>")

        del states[uid]

    # --- WITHDRAW ---
    elif state.get('step') == 'withdraw':
        try:
            amount = float(text)
            if amount <= 0:
                bot.send_message(uid, "Please enter a positive number:")
                return
            balance = get_balance(uid)
            if amount > balance:
                bot.send_message(uid, f"Insufficient balance ({balance:.4f} SOL). Enter smaller amount:")
                return

            cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, uid))
            db.commit()
            bot.send_message(uid, f"✅ Withdrawal request for {amount:.4f} SOL received. Processing within 1-2 hours.")
            bot.send_message(ADMIN_ID, f"Withdrawal request from @{get_username(uid)}: {amount:.4f} SOL")
            del states[uid]
        except:
            bot.send_message(uid, "Invalid amount. Please enter a number:")

    # --- DEPOSIT WALLET ---
    elif state.get('step') == 'deposit_wallet':
        wallet = text
        cur.execute("UPDATE users SET wallet=? WHERE user_id=?", (wallet, uid))
        db.commit()
        bot.send_message(uid, f"✅ Wallet saved. Please send SOL to:\n<code>{BOT_WALLET}</code>")
        del states[uid]

def start_match_if_ready(mid):
    cur.execute("SELECT p1, p2, paid1, paid2 FROM matches WHERE match_id=?", (mid,))
    r = cur.fetchone()
    if not r:
        print(f"[WARN] Match {mid} not found in DB.")
        return
    p1, p2, paid1, paid2 = r
    if paid1 == 1 and paid2 == 1:
        print(f"[INFO] Match {mid} fully paid. Sending result buttons.")
        try:
            bot.send_message(p1, "✅ Match ready! Please report the result.")
            handle_result_button(p1, mid)
        except Exception as e:
            print(f"[ERROR] p1: {e}")
        try:
            bot.send_message(p2, "✅ Match ready! Please report the result.")
            handle_result_button(p2, mid)
        except Exception as e:
            print(f"[ERROR] p2: {e}")
        bot.send_message(ADMIN_ID, f"✅ Both players have paid for match {mid}.")

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
                    if sender == w1 and pd1 == 0 and amount >= stake:
                        cur.execute("UPDATE matches SET paid1=1 WHERE match_id=?", (mid,))
                        bot.send_message(p1, f"✅ Payment received. Waiting for opponent.")
                        updated = True
                    elif sender == w2 and pd2 == 0 and amount >= stake:
                        cur.execute("UPDATE matches SET paid2=1 WHERE match_id=?", (mid,))
                        bot.send_message(p2, f"✅ Payment received. Waiting for opponent.")
                        updated = True
                    db.commit()
                    if updated:
                        start_match_if_ready(mid)
        except Exception as e:
            print("Payment check error:", e)
        time.sleep(5)

print("🤖 Versus Arena Bot running...")
threading.Thread(target=check_payments, daemon=True).start()
bot.infinity_polling()