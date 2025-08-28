import os
import sys
import logging
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import time
import threading
import requests

# --- CONFIG ---
BOT_TOKEN = '8113317405:AAERiOi3TM95xU87ys9xIV_L622MLo83t6Q'
BOT_WALLET = 'G3KApJaLSDkqvxWKPo8d6HoJHrzkCAufiUzc8tLwUSFd'
ADMIN_ID = 7919108078
ADMIN_ID_2 = 7160368480
RPC_URL = 'https://api.mainnet-beta.solana.com'
INVESTOR_GROUP_LINK = 'https://t.me/+dW-n4_Yw7_Q1OTFi'
HELP_CONTACT = '@nadjad_crpt,@NkryptoN'

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

# ======================
# DB Setup + Migration
# ======================
db = sqlite3.connect("gamebot.db", check_same_thread=False)
cur = db.cursor()

# Base tables
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
    -- 'status' will be added by migration below
)''')

# Investments (whitelist)
cur.execute('''CREATE TABLE IF NOT EXISTS investments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount REAL,
    wallet TEXT,
    paid INTEGER DEFAULT 0,
    created_at INTEGER
)''')

# Matchmaking queue
cur.execute('''CREATE TABLE IF NOT EXISTS mm_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    game TEXT,
    stake REAL,
    created_at INTEGER
)''')

db.commit()

# --- helpers for schema migration ---

def column_exists(table, col):
    c = db.cursor()
    c.execute(f"PRAGMA table_info({table})")
    return any(row[1] == col for row in c.fetchall())

def ensure_schema():
    c = db.cursor()
    # matches.status
    if not column_exists('matches', 'status'):
        c.execute("ALTER TABLE matches ADD COLUMN status TEXT DEFAULT 'waiting'")
        db.commit()
        c.execute("UPDATE matches SET status='waiting' WHERE status IS NULL")
        db.commit()
    # result claims
    if not column_exists('matches', 'p1_claim'):
        c.execute("ALTER TABLE matches ADD COLUMN p1_claim TEXT")
        db.commit()
    if not column_exists('matches', 'p2_claim'):
        c.execute("ALTER TABLE matches ADD COLUMN p2_claim TEXT")
        db.commit()
    # stake proposals for quick match negotiation
    if not column_exists('matches', 'p1_prop'):
        c.execute("ALTER TABLE matches ADD COLUMN p1_prop REAL")
        db.commit()
    if not column_exists('matches', 'p2_prop'):
        c.execute("ALTER TABLE matches ADD COLUMN p2_prop REAL")
        db.commit()

ensure_schema()

# ======================
# Bot State
# ======================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

states = {}
checked_signatures = set()
games = ['FIFA', 'Fortnite', 'Call of Duty', 'Mario Kart']

# -----------------------
# DB helper funcs
# -----------------------

def get_username(uid):
    cur.execute("SELECT username FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return r[0] if r else f"user{uid}"

def get_balance(uid):
    cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return r[0] if r else 0.0

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
    return f"👤 <b>@{username}</b> | 💰 {balance:.4f} SOL | 🔑 {wallet_text}\n\n"

# -----------------------
# UI builders
# -----------------------

def main_menu(uid, call=None):
    user_info = get_user_info_text(uid)
    menu_text = user_info + "🏠 Main Menu - Versus Arena\n🌐 <a href='https://versus-arena.com/'>versus-arena.com</a>"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔴 🎮 Start Match", callback_data="start_match"),
        InlineKeyboardButton("🎲 Quick Match", callback_data="random_mode"),
        InlineKeyboardButton("🔵 💰 Balance", callback_data="balance"),
        InlineKeyboardButton("🔴 📥 Deposit", callback_data="deposit"),
        InlineKeyboardButton("🔵 📤 Withdraw", callback_data="withdraw"),
        InlineKeyboardButton("🟢 Join Whitelist Now", callback_data="whitelist"),
        InlineKeyboardButton("🆘 Help / Questions", callback_data="help")
    )
    try:
        if call:
            bot.edit_message_text(menu_text, call.message.chat.id, call.message.message_id, reply_markup=markup, disable_web_page_preview=True)
        else:
            bot.send_message(uid, menu_text, reply_markup=markup, disable_web_page_preview=True)
    except Exception as e:
        logging.warning("Failed to send/edit main menu: %s", e)

def send_result_buttons(uid, mid):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🏆 I won", callback_data=f"win_{mid}"),
        InlineKeyboardButton("😔 I lost", callback_data=f"lose_{mid}")
    )
    bot.send_message(uid, "❓ Report result:", reply_markup=markup)

# -----------------------
# Result processing
# -----------------------

def process_result(mid):
    cur.execute("SELECT p1, p2, stake, p1_claim, p2_claim, status FROM matches WHERE match_id=?", (mid,))
    row = cur.fetchone()
    if not row:
        return
    p1, p2, stake, c1, c2, status = row
    if not c1 or not c2:
        return  # wait for the other player

    if c1 == 'win' and c2 == 'lose':
        cur.execute("UPDATE matches SET winner=?, status='finished' WHERE match_id=?", (p1, mid))
        add_balance(p1, stake * 2)
        db.commit()
        bot.send_message(p1, "🏆 You won! Your balance has been credited.")
        bot.send_message(p2, "ℹ️ Opponent's win confirmed. Match finished.")
    elif c1 == 'lose' and c2 == 'win':
        cur.execute("UPDATE matches SET winner=?, status='finished' WHERE match_id=?", (p2, mid))
        add_balance(p2, stake * 2)
        db.commit()
        bot.send_message(p2, "🏆 You won! Your balance has been credited.")
        bot.send_message(p1, "ℹ️ Opponent's win confirmed. Match finished.")
    elif c1 == 'lose' and c2 == 'lose':
        # both lost -> refund both players their stake
        add_balance(p1, stake)
        add_balance(p2, stake)
        cur.execute("UPDATE matches SET status='refunded' WHERE match_id=?", (mid,))
        db.commit()
        bot.send_message(p1, f"↩️ Both players reported a loss. Your stake ({stake} SOL) was refunded.")
        bot.send_message(p2, f"↩️ Both players reported a loss. Your stake ({stake} SOL) was refunded.")
    else:
        # Same claim (both win) -> dispute, lock funds
        cur.execute("UPDATE matches SET status='disputed' WHERE match_id=?", (mid,))
        db.commit()
        alert = (
            "🚨 RESULT DISPUTE 🚫\n"
            f"Match ID: {mid}\n"
            f"P1: @{get_username(p1)} claim={c1}\n"
            f"P2: @{get_username(p2)} claim={c2}\n"
            f"Stake: {stake} SOL\n"
            "Funds locked until resolved."
        )
        for admin in (ADMIN_ID, ADMIN_ID_2):
            try:
                bot.send_message(admin, alert)
            except Exception:
                pass
        try:
            bot.send_message(p1, "⚠️ Dispute detected (both reported WIN). Admins have been notified. Funds are locked.")
            bot.send_message(p2, "⚠️ Dispute detected (both reported WIN). Admins have been notified. Funds are locked.")
        except Exception:
            pass

# -----------------------
# Telegram Handlers
# -----------------------
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
        # also offer quick match path here
        markup.add(InlineKeyboardButton("🎲 Quick Match", callback_data="random_mode"))
        user_info = get_user_info_text(uid)
        bot.edit_message_text(user_info + "🎮 Select a game:", call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif data.startswith("game_"):
        game = data[5:]
        states[uid] = {'step': 'opponent', 'game': game}
        user_info = get_user_info_text(uid)
        bot.edit_message_text(user_info + "👤 Opponent username (without @):", call.message.chat.id, call.message.message_id)

    elif data == "random_mode":
        markup = InlineKeyboardMarkup()
        for g in games:
            markup.add(InlineKeyboardButton(f"🎯 {g}", callback_data=f"rgame_{g}"))
        markup.add(InlineKeyboardButton("🏠 Back to Menu", callback_data="back_to_menu"))
        user_info = get_user_info_text(uid)
        try:
            bot.edit_message_text(user_info + "🎲 Quick Match – choose a game:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        except Exception:
            bot.send_message(uid, user_info + "🎲 Quick Match – choose a game:", reply_markup=markup)

    elif data.startswith("rgame_"):
        game = data[6:]
        # Try to find any opponent waiting in this game (stake negotiation will happen after pairing)
        cur.execute("SELECT id, user_id FROM mm_queue WHERE game=? AND user_id<>? ORDER BY created_at LIMIT 1", (game, uid))
        row = cur.fetchone()
        if row:
            qid, opp = row
            cur.execute("DELETE FROM mm_queue WHERE id=?", (qid,))
            db.commit()
            mid = str(int(time.time()))
            cur.execute(
                """
                INSERT INTO matches (match_id, p1, p2, game, stake, wallet1, wallet2, paid1, paid2, winner, status, p1_claim, p2_claim, p1_prop, p2_prop)
                VALUES (?, ?, ?, ?, 0.0, '', '', 0, 0, NULL, 'negotiating', NULL, NULL, NULL, NULL)
                """,
                (mid, opp, uid, game),
            )
            db.commit()
            for pid in (opp, uid):
                states[pid] = {'step': 'r_propose', 'match_id': mid}
                bot.send_message(pid, f"🤝 Match found in <b>{game}</b>!\nPlease propose your stake in SOL (e.g., 1.0).")
        else:
            # Put current user into queue (no stake yet)
            cur.execute("INSERT INTO mm_queue (user_id, game, stake, created_at) VALUES (?, ?, ?, ?)", (uid, game, None, int(time.time())))
            db.commit()
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("❌ Cancel Search", callback_data="r_cancel"))
            bot.send_message(uid, f"⌛ Waiting for an opponent in <b>{game}</b>...", reply_markup=markup)

    elif data == "r_cancel":
        cur.execute("DELETE FROM mm_queue WHERE user_id=?", (uid,))
        db.commit()
        bot.answer_callback_query(call.id, "Search cancelled")
        main_menu(uid, call)

    elif data == "balance":
        bal = get_balance(uid)
        user_info = get_user_info_text(uid)
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🏠 Back to Menu", callback_data="back_to_menu"))
        bot.edit_message_text(user_info + f"💰 Your balance: <b>{bal:.4f} SOL</b>", call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif data == "deposit":
        cur.execute("SELECT wallet FROM users WHERE user_id=?", (uid,))
        r = cur.fetchone()
        wallet = r[0] if r and r[0] else None
        user_info = get_user_info_text(uid)
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🏠 Back to Menu", callback_data="back_to_menu"))
        if not wallet:
            states[uid] = {'step': 'deposit_wallet'}
            bot.edit_message_text(user_info + "🔑 Please send your wallet address for deposits:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        else:
            bot.edit_message_text(user_info + f"📥 Send SOL to:\n<code>{BOT_WALLET}</code>", call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif data == "withdraw":
        states[uid] = {'step': 'withdraw'}
        user_info = get_user_info_text(uid)
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("❌ Cancel", callback_data="back_to_menu"))
        bot.edit_message_text(user_info + "💸 Enter amount to withdraw:", call.message.chat.id, call.message.message_id, reply_markup=markup)

    # --- Whitelist info ---
    elif data == "whitelist":
        user_info = get_user_info_text(uid)
        text = (
            user_info
            + "<b>🟢 Versus Arena – Whitelist Access</b>\n\n"
            + "Get early access to buy the Versus Arena token before public launch.\n"
            + "• Minimum investment: <b>1 SOL</b>\n"
            + "• Investing now gives an approximate entry at a $20–25K market cap.\n"
            + "• Your funds support launch & liquidity.\n"
            + "• After payment is detected on-chain, you will be marked as <b>invested</b> and invited to the investor group.\n"
        )
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("🚀 Invest Now", callback_data="invest_now"),
            InlineKeyboardButton("🏠 Back to Menu", callback_data="back_to_menu")
        )
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, disable_web_page_preview=False)
        except Exception:
            bot.send_message(uid, text, reply_markup=markup, disable_web_page_preview=False)

    elif data == "invest_now":
        states[uid] = {'step': 'invest_amount'}
        user_info = get_user_info_text(uid)
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("❌ Cancel", callback_data="back_to_menu"))
        bot.edit_message_text(user_info + "💵 Enter the amount to invest in SOL (min 1 SOL):", call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif data == "help":
        user_info = get_user_info_text(uid)
        text = (
            user_info
            + "<b>🆘 Help / Questions</b>\n\n"
            + f"If you need help or have any questions, please contact {HELP_CONTACT}.\n"
            + "We are happy to assist you."
        )
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🏠 Back to Menu", callback_data="back_to_menu"))
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
        except Exception:
            bot.send_message(uid, text, reply_markup=markup)

    elif data == "back_to_menu":
        states.pop(uid, None)
        main_menu(uid, call)

    # --- Results: win/lose ---
    elif data.startswith("win_") or data.startswith("lose_"):
        mid = data.split("_", 1)[1]
        claim = 'win' if data.startswith('win_') else 'lose'
        cur.execute("SELECT p1, p2, p1_claim, p2_claim FROM matches WHERE match_id=?", (mid,))
        row = cur.fetchone()
        if not row:
            bot.send_message(uid, "❌ Match not found.")
            return
        p1, p2, c1, c2 = row
        if uid == p1:
            if c1:
                bot.send_message(uid, "ℹ️ You already reported your result.")
            else:
                cur.execute("UPDATE matches SET p1_claim=? WHERE match_id=?", (claim, mid))
                db.commit()
                bot.send_message(uid, "✅ Result submitted.")
        elif uid == p2:
            if c2:
                bot.send_message(uid, "ℹ️ You already reported your result.")
            else:
                cur.execute("UPDATE matches SET p2_claim=? WHERE match_id=?", (claim, mid))
                db.commit()
                bot.send_message(uid, "✅ Result submitted.")
        else:
            bot.send_message(uid, "❌ You are not in this match.")
            return
        process_result(mid)

    # --- Dispute button kept for manual report ---
    elif data.startswith("dispute_"):
        bot.send_message(uid, "📨 The admin has been informed. Please send any evidence if necessary.")
        mid = data.split("_", 1)[1]
        cur.execute("SELECT p1, p2, game, stake FROM matches WHERE match_id=?", (mid,))
        match_info = cur.fetchone()
        if match_info:
            p1, p2, game, stake = match_info
            dispute_msg = (
                "🚨 DISPUTE REPORTED 🚨\n"
                + f"Match ID: {mid}\n"
                + f"Player 1: @{get_username(p1)}\n"
                + f"Player 2: @{get_username(p2)}\n"
                + f"Game: {game}\n"
                + f"Stake: {stake} SOL\n"
                + f"Reported by: @{get_username(uid)}"
            )
            for admin in (ADMIN_ID, ADMIN_ID_2):
                try:
                    bot.send_message(admin, dispute_msg)
                except Exception:
                    pass

    # --- Accept / Decline challenge ---
    elif data.startswith("accept_"):
        mid = data.split('_', 1)[1]
        cur.execute("SELECT p1, p2 FROM matches WHERE match_id=?", (mid,))
        row = cur.fetchone()
        if not row:
            bot.send_message(uid, "❌ Match not found.")
            return
        p1, p2 = row
        if uid not in (p1, p2):
            bot.send_message(uid, "❌ Not your match.")
            return
        # set next step to collect wallet of the accepter
        states[uid] = {'step': 'wallet_join', 'match_id': mid}
        user_info = get_user_info_text(uid)
        bot.send_message(uid, user_info + "🔑 Please provide your wallet address:")
        # inform challenger
        other = p1 if uid == p2 else p2
        try:
            bot.send_message(other, "✅ Opponent accepted your challenge. Waiting for payment from both players.")
        except Exception:
            pass

    elif data.startswith("decline_"):
        mid = data.split('_', 1)[1]
        cur.execute("SELECT p1, p2, stake, paid1, paid2 FROM matches WHERE match_id=?", (mid,))
        row = cur.fetchone()
        if not row:
            bot.send_message(uid, "❌ Match not found.")
            return
        p1, p2, stake, paid1, paid2 = row
        # refund if challenger already paid with balance
        if paid1 and uid == p2:
            cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (stake, p1))
            db.commit()
            try:
                bot.send_message(p1, f"↩️ Opponent declined. Your stake ({stake} SOL) has been refunded to your balance.")
            except Exception:
                pass
        try:
            bot.send_message(p1, "❌ Opponent declined your challenge.")
            bot.send_message(p2, "✅ You declined the challenge.")
        except Exception:
            pass
        cur.execute("UPDATE matches SET status='declined' WHERE match_id=?", (mid,))
        db.commit()

    # --- Investment: manual check button ---
    elif data.startswith("invest_check_"):
        inv_id = int(data.split("_", 2)[2])
        if verify_invest_payment_once(inv_id):
            try:
                bot.answer_callback_query(call.id, "Payment detected!")
            except Exception:
                pass
        else:
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("🔁 Check Again", callback_data=f"invest_check_{inv_id}"),
                InlineKeyboardButton("🏠 Back to Menu", callback_data="back_to_menu")
            )
            bot.send_message(uid, "⏳ Payment not detected yet. If you already sent SOL, it may take a short moment to confirm on-chain.", reply_markup=markup)

@bot.message_handler(func=lambda m: m.from_user.id in states)
def state_handler(msg):
    uid = msg.from_user.id
    state = states[uid]

    if state['step'] == 'opponent':
        opponent = msg.text.strip().lstrip("@")
        cur.execute("SELECT user_id FROM users WHERE username=?", (opponent,))
        r = cur.fetchone()
        if not r:
            bot.send_message(uid, "❌ Opponent not found. Make sure they have started the bot first.")
            return
        if r[0] == uid:
            bot.send_message(uid, "❌ You cannot challenge yourself!")
            return
        state['opponent'] = r[0]
        state['step'] = 'stake'
        user_info = get_user_info_text(uid)
        bot.send_message(uid, user_info + "💵 Stake amount in SOL:")

    elif state['step'] == 'stake':
        try:
            stake = float(msg.text.strip())
            if stake <= 0:
                bot.send_message(uid, "❌ Stake must be greater than 0.")
                return
            state['stake'] = stake
            state['step'] = 'pay_method'
            user_info = get_user_info_text(uid)
            bot.send_message(uid, user_info + "💳 Do you want to pay with your balance? Reply 'yes' or 'no'.")
        except:
            bot.send_message(uid, "❌ Invalid amount. Please enter a valid number.")

    elif state['step'] == 'pay_method':
        answer = msg.text.strip().lower()
        if answer in ('yes', 'y'):
            bal = get_balance(uid)
            if bal < state['stake']:
                bot.send_message(uid, f"❌ Your balance ({bal:.4f} SOL) is insufficient.")
                return
            state['pay_with_balance'] = True
            state['step'] = 'wallet'
            user_info = get_user_info_text(uid)
            bot.send_message(uid, user_info + "🔑 Please provide your wallet address (for match tracking):")
        elif answer in ('no', 'n'):
            state['pay_with_balance'] = False
            state['step'] = 'wallet'
            user_info = get_user_info_text(uid)
            bot.send_message(uid, user_info + "🔑 Please provide your wallet address:")
        else:
            bot.send_message(uid, "❌ Please reply with 'yes' or 'no'.")

    elif state['step'] == 'wallet':
        wallet = msg.text.strip()
        if len(wallet) < 20:
            bot.send_message(uid, "❌ Invalid wallet address. Please provide a valid Solana wallet address.")
            return

        cur.execute("UPDATE users SET wallet=? WHERE user_id=?", (wallet, uid))
        db.commit()
        mid = str(int(time.time()))
        opp = state['opponent']
        pay_with_balance = state.get('pay_with_balance', False)

        cur.execute(
            """
            INSERT INTO matches (match_id, p1, p2, game, stake, wallet1, wallet2, paid1, paid2, winner, status, p1_claim, p2_claim)
            VALUES (?, ?, ?, ?, ?, ?, '', 0, 0, NULL, 'waiting', NULL, NULL)
            """,
            (mid, uid, opp, state['game'], state['stake'], wallet)
        )
        db.commit()

        if pay_with_balance:
            cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (state['stake'], uid))
            cur.execute("UPDATE matches SET paid1=1 WHERE match_id=?", (mid,))
            db.commit()
            bot.send_message(uid, "✅ You paid with your balance. The match will start once your opponent accepts and pays.")
        else:
            bot.send_message(uid, f"✅ Please send {state['stake']} SOL to:\n<code>{BOT_WALLET}</code>")

        challenger_name = get_username(uid)
        # Ask opponent to accept or decline
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("✅ Accept", callback_data=f"accept_{mid}"),
            InlineKeyboardButton("❌ Decline", callback_data=f"decline_{mid}")
        )
        bot.send_message(
            opp,
            (
                f"🎮 You have been challenged by <b>@{challenger_name}</b>!\n"
                f"Game: {state['game']}\n"
                f"Stake: {state['stake']} SOL\n"
                f"Do you accept?"
            ),
            reply_markup=markup,
        )

        states.pop(uid)

    # Opponent collects wallet after accept
    elif state['step'] == 'wallet_join':
        wallet = msg.text.strip()
        if len(wallet) < 20:
            bot.send_message(uid, "❌ Invalid wallet address. Please provide a valid Solana wallet address.")
            return

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
        cur.execute("SELECT p1, p2, stake, paid1, paid2 FROM matches WHERE match_id=?", (mid,))
        result = cur.fetchone()
        if not result:
            bot.send_message(uid, "❌ Match not found.")
            states.pop(uid, None)
            return
        p1, p2, stake, paid1, paid2 = result

        if answer in ('yes', 'y'):
            bal = get_balance(uid)
            if bal < stake:
                bot.send_message(uid, f"❌ Your balance ({bal:.4f} SOL) is insufficient.")
                return
            if uid == p1:
                cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (stake, uid))
                cur.execute("UPDATE matches SET paid1=1 WHERE match_id=?", (mid,))
            else:
                cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (stake, uid))
                cur.execute("UPDATE matches SET paid2=1 WHERE match_id=?", (mid,))
            db.commit()
            bot.send_message(uid, "✅ You paid with your balance. Checking if both players have paid...")

        elif answer in ('no', 'n'):
            bot.send_message(uid, f"✅ Please send {stake} SOL to:\n<code>{BOT_WALLET}</code>")
        else:
            bot.send_message(uid, "❌ Please reply with 'yes' or 'no'.")
            return
        states.pop(uid)

        # After payment attempt, check both paid
        cur.execute("SELECT p1, p2, paid1, paid2 FROM matches WHERE match_id=?", (mid,))
        p1, p2, paid1, paid2 = cur.fetchone()
        if paid1 and paid2:
            for pid in (p1, p2):
                bot.send_message(pid, "✅ Both players have paid. The match can start now!")
                send_result_buttons(pid, mid)
            cur.execute("UPDATE matches SET status='playing' WHERE match_id=?", (mid,))
            db.commit()

    # Quick Match proposal stage
    elif state['step'] == 'r_propose':
        try:
            amount = float(msg.text.strip())
            if amount <= 0:
                bot.send_message(uid, "❌ Stake must be greater than 0.")
                return
            mid = state['match_id']
            cur.execute("SELECT p1, p2, p1_prop, p2_prop, game FROM matches WHERE match_id=?", (mid,))
            row = cur.fetchone()
            if not row:
                bot.send_message(uid, "❌ Match not found.")
                states.pop(uid, None)
                return
            p1, p2, prop1, prop2, game = row
            if uid == p1:
                cur.execute("UPDATE matches SET p1_prop=? WHERE match_id=?", (amount, mid))
            elif uid == p2:
                cur.execute("UPDATE matches SET p2_prop=? WHERE match_id=?", (amount, mid))
            else:
                bot.send_message(uid, "❌ Not your match.")
                return
            db.commit()

            cur.execute("SELECT p1_prop, p2_prop FROM matches WHERE match_id=?", (mid,))
            prop1, prop2 = cur.fetchone()
            if prop1 is None or prop2 is None:
                bot.send_message(uid, "✅ Proposal saved. Waiting for the opponent's proposal...")
                return

            # both proposed
            if abs(prop1 - prop2) < 1e-9:
                # agreed
                cur.execute("UPDATE matches SET stake=?, status='waiting', p1_prop=NULL, p2_prop=NULL WHERE match_id=?", (prop1, mid))
                db.commit()
                for pid in (p1, p2):
                    states[pid] = {'step': 'wallet_join', 'match_id': mid}
                    bot.send_message(pid, f"✅ Stake agreed at <b>{prop1} SOL</b> for <b>{game}</b>.\nPlease send your wallet address:")
            else:
                # ask both to type the other player's number to agree
                for pid, mine, other in ((p1, prop1, prop2), (p2, prop2, prop1)):
                    try:
                        bot.send_message(pid, (
                            "⚖️ Stake proposals don't match yet.\n"
                            f"You proposed: <b>{mine} SOL</b>\n"
                            f"Opponent proposed: <b>{other} SOL</b>\n\n"
                            "Type the opponent's number to accept it, or send a new amount."
                        ))
                    except Exception:
                        pass
        except:
            bot.send_message(uid, "❌ Invalid amount. Please enter a valid number.")

    elif state['step'] == 'withdraw':
        try:
            amount = float(msg.text.strip())
            if amount <= 0:
                bot.send_message(uid, "❌ Amount must be greater than 0.")
                return
            bal = get_balance(uid)
            if amount > bal:
                bot.send_message(uid, f"❌ Insufficient balance. Your balance: {bal:.4f} SOL")
                return
            cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, uid))
            db.commit()
            bot.send_message(uid, f"✅ Withdrawal request for {amount:.4f} SOL is being processed (1–2 hours).")

            withdrawal_msg = (
                "💸 WITHDRAWAL REQUEST\n"
                f"User: @{get_username(uid)}\n"
                f"Amount: {amount:.4f} SOL\n"
                f"User ID: {uid}"
            )
            for admin in (ADMIN_ID, ADMIN_ID_2):
                try:
                    bot.send_message(admin, withdrawal_msg)
                except Exception:
                    pass
            states.pop(uid)
        except:
            bot.send_message(uid, "❌ Invalid amount. Please enter a valid number.")

    elif state['step'] == 'deposit_wallet':
        wallet = msg.text.strip()
        if len(wallet) < 20:
            bot.send_message(uid, "❌ Invalid wallet address. Please provide a valid Solana wallet address.")
            return

        cur.execute("UPDATE users SET wallet=? WHERE user_id=?", (wallet, uid))
        db.commit()
        user_info = get_user_info_text(uid)
        bot.send_message(
            uid,
            user_info + f"✅ Wallet saved.\nNow send SOL to:\n<code>{BOT_WALLET}</code>",
        )
        states.pop(uid)

    # Investment flow
    elif state['step'] == 'invest_amount':
        try:
            amount = float(msg.text.strip())
            if amount < 1:
                bot.send_message(uid, "❌ Minimum investment is 1 SOL.")
                return
            state['amount'] = amount
            state['step'] = 'invest_wallet'
            user_info = get_user_info_text(uid)
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("❌ Cancel", callback_data="back_to_menu"))
            bot.send_message(
                uid,
                user_info + "🔑 Please provide the Solana wallet you'll use to send the investment:",
                reply_markup=markup,
            )
        except:
            bot.send_message(uid, "❌ Invalid amount. Please enter a valid number.")

    elif state['step'] == 'invest_wallet':
        wallet = msg.text.strip()
        if len(wallet) < 20:
            bot.send_message(uid, "❌ Invalid wallet address. Please provide a valid Solana wallet address.")
            return
        amount = state['amount']
        cur.execute("UPDATE users SET wallet=? WHERE user_id=?", (wallet, uid))
        created_at = int(time.time())
        cur.execute(
            "INSERT INTO investments (user_id, amount, wallet, created_at) VALUES (?, ?, ?, ?)",
            (uid, amount, wallet, created_at),
        )
        inv_id = cur.lastrowid
        db.commit()

        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("✅ I've paid – check now", callback_data=f"invest_check_{inv_id}"),
            InlineKeyboardButton("🏠 Back to Menu", callback_data="back_to_menu"),
        )
        text = (
            f"🚀 <b>Investment started</b>\n\n"
            f"Amount: <b>{amount:.4f} SOL</b>\n"
            f"From wallet: <code>{wallet}</code>\n\n"
            f"📥 Please send <b>{amount:.4f} SOL</b> to:\n<code>{BOT_WALLET}</code>\n\n"
            "Once the transaction is confirmed on-chain, tap the button below to verify."
        )
        bot.send_message(uid, text, reply_markup=markup)
        states.pop(uid)

# -----------------------
# Solana RPC Helpers
# -----------------------

def rpc(method, params):
    return requests.post(RPC_URL, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=15).json()


def get_new_signatures_for_address(address, limit=50):
    try:
        res = rpc("getSignaturesForAddress", [address, {"limit": limit}])
        arr = res.get("result") or []
        sigs = []
        for item in arr:
            sig = item.get("signature")
            if sig and sig not in checked_signatures:
                sigs.append(sig)
        sigs.reverse()
        return sigs
    except Exception as e:
        logging.warning("getSignaturesForAddress error: %s", e)
        return []


def get_tx_details(sig):
    try:
        r = rpc("getTransaction", [sig, {"encoding": "jsonParsed", "commitment": "confirmed"}])
        res = r.get('result')
        if not res:
            return None
        meta = res.get('meta', {})
        if meta.get('err'):
            return None
        txmsg = res['transaction']['message']
        account_keys = txmsg.get('accountKeys') or []
        keys = []
        for k in account_keys:
            keys.append(k.get('pubkey') if isinstance(k, dict) else k)
        pre = meta.get('preBalances')
        post = meta.get('postBalances')
        if pre is None or post is None:
            return None
        try:
            bot_index = keys.index(BOT_WALLET)
        except ValueError:
            return None
        delta = post[bot_index] - pre[bot_index]
        if delta <= 0:
            return None
        amount = delta / 1e9
        sender = None
        for i, (p, po) in enumerate(zip(pre, post)):
            if p - po >= delta - 1000:
                sender = keys[i]
                break
        if not sender:
            for inst in (txmsg.get('instructions') or []):
                if isinstance(inst, dict):
                    parsed = inst.get('parsed') or {}
                    info = parsed.get('info') or {}
                    if 'source' in info:
                        sender = info['source']; break
                    if 'from' in info:
                        sender = info['from']; break
        block_time = res.get('blockTime') or 0
        logging.info("TX %s -> from %s amount=%.9f SOL (lamports delta=%d) blockTime=%s", sig, sender, amount, delta, block_time)
        return {"from": sender, "amount": amount, "blockTime": block_time}
    except Exception as e:
        logging.warning("get_tx_details error for %s: %s", sig, e)
        return None

# -----------------------
# Payment Scanner
# -----------------------

def mark_paid_if_match(sender_wallet, amount_sol):
    assigned = False
    cur.execute(
        """SELECT match_id, p1, p2, wallet1, wallet2, stake, paid1, paid2
                   FROM matches
                   WHERE status='waiting'"""
    )
    rows = cur.fetchall()
    for mid, p1, p2, w1, w2, stake, paid1, paid2 in rows:
        updated = False
        if not w1 and sender_wallet and sender_wallet != w2:
            cur.execute("UPDATE matches SET wallet1=? WHERE match_id=?", (sender_wallet, mid))
            cur.execute("UPDATE users SET wallet=? WHERE user_id=?", (sender_wallet, p1))
            w1 = sender_wallet
            updated = True
        if not w2 and sender_wallet and sender_wallet != w1:
            cur.execute("UPDATE matches SET wallet2=? WHERE match_id=?", (sender_wallet, mid))
            cur.execute("UPDATE users SET wallet=? WHERE user_id=?", (sender_wallet, p2))
            w2 = sender_wallet
            updated = True
        if updated:
            db.commit()

        if sender_wallet == w1 and not paid1 and amount_sol + 1e-12 >= stake:
            cur.execute("UPDATE matches SET paid1=1 WHERE match_id=?", (mid,))
            db.commit()
            paid1 = 1
            try:
                bot.send_message(p1, f"✅ Payment received ({amount_sol:.9f} SOL). Waiting for opponent.")
            except Exception:
                pass
            assigned = True
        elif sender_wallet == w2 and not paid2 and amount_sol + 1e-12 >= stake:
            cur.execute("UPDATE matches SET paid2=1 WHERE match_id=?", (mid,))
            db.commit()
            paid2 = 1
            try:
                bot.send_message(p2, f"✅ Payment received ({amount_sol:.9f} SOL). Waiting for opponent.")
            except Exception:
                pass
            assigned = True

        if paid1 and paid2:
            for pid in (p1, p2):
                try:
                    bot.send_message(pid, "✅ Both players have paid. The match can start now!")
                    send_result_buttons(pid, mid)
                except Exception:
                    pass
            cur.execute("UPDATE matches SET status='playing' WHERE match_id=?", (mid,))
            db.commit()
    return assigned


def mark_paid_if_invest(sender_wallet, amount_sol, block_time):
    assigned = False
    cur.execute("SELECT id, user_id, amount, wallet, paid, created_at FROM investments WHERE paid=0 AND wallet=?", (sender_wallet,))
    rows = cur.fetchall()
    for inv_id, user_id, amount_req, wallet, paid, created_at in rows:
        if amount_sol + 1e-12 >= amount_req and (not block_time or block_time >= (created_at - 600)):
            cur.execute("UPDATE investments SET paid=1 WHERE id=?", (inv_id,))
            db.commit()
            try:
                bot.send_message(
                    user_id,
                    (
                        "🎉 <b>Investment confirmed!</b>\n\n"
                        f"Amount: <b>{amount_req:.4f} SOL</b>\n"
                        f"Wallet: <code>{wallet}</code>\n\n"
                        f"Welcome! Join the investor group: <a href='{INVESTOR_GROUP_LINK}'>Open Telegram</a>"
                    ),
                )
            except Exception:
                pass
            info = (
                "✅ INVESTMENT\n"
                f"User: @{get_username(user_id)}\n"
                f"Amount: {amount_req:.4f} SOL\n"
                f"Wallet: {wallet}\n"
                f"ID: {inv_id}"
            )
            for admin in (ADMIN_ID, ADMIN_ID_2):
                try:
                    bot.send_message(admin, info)
                except Exception:
                    pass
            assigned = True
    return assigned


def credit_general_deposit(sender_wallet, amount_sol):
    cur.execute("SELECT user_id FROM users WHERE wallet=?", (sender_wallet,))
    r = cur.fetchone()
    if r:
        uid = r[0]
        add_balance(uid, amount_sol)
        try:
            bot.send_message(uid, f"💰 Deposit received: <b>{amount_sol:.9f} SOL</b>")
        except Exception:
            pass
        logging.info("Credited deposit %.9f SOL to user %s (wallet %s)", amount_sol, uid, sender_wallet)


def payment_scanner():
    logging.info("🔎 Payment scanner started (watching %s)...", BOT_WALLET)
    while True:
        try:
            new_sigs = get_new_signatures_for_address(BOT_WALLET, limit=50)
            for sig in new_sigs:
                details = get_tx_details(sig)
                checked_signatures.add(sig)
                if not details:
                    logging.info("No usable tx details for %s", sig)
                    continue
                sender = details["from"]
                amount = details["amount"]
                block_time = details.get("blockTime", 0)
                if not sender or amount <= 0:
                    continue
                matched_match = mark_paid_if_match(sender, amount)
                matched_invest = mark_paid_if_invest(sender, amount, block_time)
                if not (matched_match or matched_invest):
                    credit_general_deposit(sender, amount)
        except Exception as e:
            logging.warning("Scanner loop error: %s", e)
        time.sleep(8)

# -----------------------
# One-off verification for investments
# -----------------------

def verify_invest_payment_once(inv_id):
    cur.execute("SELECT user_id, amount, wallet, paid, created_at FROM investments WHERE id=?", (inv_id,))
    row = cur.fetchone()
    if not row:
        return False
    user_id, amount_req, wallet, paid, created_at = row
    if paid:
        try:
            bot.send_message(
                user_id,
                (
                    "🎉 <b>Investment already confirmed</b>\n"
                    f"Amount: <b>{amount_req:.4f} SOL</b>\n"
                    f"Wallet: <code>{wallet}</code>\n"
                    f"Investor group: <a href='{INVESTOR_GROUP_LINK}'>Open Telegram</a>"
                ),
            )
        except Exception:
            pass
        return True
    try:
        res = rpc("getSignaturesForAddress", [BOT_WALLET, {"limit": 100}])
        arr = res.get('result') or []
        for item in arr:
            sig = item.get('signature')
            if not sig:
                continue
            btime = item.get('blockTime') or 0
            if created_at and btime and btime < (created_at - 600):
                continue
            details = get_tx_details(sig)
            if not details:
                continue
            if details.get('from') == wallet and details.get('amount', 0) + 1e-12 >= amount_req:
                cur.execute("UPDATE investments SET paid=1 WHERE id=?", (inv_id,))
                db.commit()
                try:
                    bot.send_message(
                        user_id,
                        (
                            "🎉 <b>Investment confirmed!</b>\n\n"
                            f"Amount: <b>{amount_req:.4f} SOL</b>\n"
                            f"Wallet: <code>{wallet}</code>\n\n"
                            f"Welcome! Join the investor group: <a href='{INVESTOR_GROUP_LINK}'>Open Telegram</a>"
                        ),
                    )
                except Exception:
                    pass
                info = (
                    "✅ INVESTMENT\n"
                    f"User: @{get_username(user_id)}\n"
                    f"Amount: {amount_req:.4f} SOL\n"
                    f"Wallet: {wallet}\n"
                    f"ID: {inv_id}"
                )
                for admin in (ADMIN_ID, ADMIN_ID_2):
                    try:
                        bot.send_message(admin, info)
                    except Exception:
                        pass
                return True
    except Exception as e:
        logging.warning("verify_invest_payment_once error: %s", e)
        return False
    return False

# -----------------------
# Minimal self-tests (run with SELF_TEST=1)
# -----------------------
class _DummyBot:
    def send_message(self, *args, **kwargs):
        return None
    def edit_message_text(self, *args, **kwargs):
        return None
    def answer_callback_query(self, *args, **kwargs):
        return None

def run_sanity_tests():
    """Run basic tests without hitting Telegram network."""
    global bot
    bot = _DummyBot()  # stub network calls

    # 1) get_user_info_text for unknown user
    temp_uid = 999000111
    cur.execute("DELETE FROM users WHERE user_id=?", (temp_uid,))
    db.commit()
    assert "User not found" in get_user_info_text(temp_uid)

    # 2) insert user and verify formatted string
    cur.execute(
        "INSERT OR REPLACE INTO users (user_id, username, wallet, balance) VALUES (?, ?, ?, ?)",
        (temp_uid, 'tester', None, 1.2345)
    )
    db.commit()
    s = get_user_info_text(temp_uid)
    assert "@tester" in s and "1.2345" in s and "No wallet saved" in s

    # 3) result resolution tests
    u1, u2 = 11110001, 11110002
    cur.execute("INSERT OR REPLACE INTO users (user_id, username, wallet, balance) VALUES (?, ?, ?, ?)", (u1, 'u1', None, 0.0))
    cur.execute("INSERT OR REPLACE INTO users (user_id, username, wallet, balance) VALUES (?, ?, ?, ?)", (u2, 'u2', None, 0.0))
    db.commit()

    # 3a) dispute when both WIN
    mid_a = 'm_a'
    cur.execute(
        """
        INSERT OR REPLACE INTO matches (match_id, p1, p2, game, stake, wallet1, wallet2, paid1, paid2, winner, status, p1_claim, p2_claim)
        VALUES (?, ?, ?, ?, ?, '', '', 1, 1, NULL, 'playing', 'win', 'win')
        """,
        (mid_a, u1, u2, 'FIFA', 0.5)
    )
    db.commit()
    process_result(mid_a)
    cur.execute("SELECT status, winner FROM matches WHERE match_id=?", (mid_a,))
    st, w = cur.fetchone()
    assert st == 'disputed' and w is None

    # 3b) winner flow (u1 win, u2 lose)
    mid_b = 'm_b'
    cur.execute(
        """
        INSERT OR REPLACE INTO matches (match_id, p1, p2, game, stake, wallet1, wallet2, paid1, paid2, winner, status, p1_claim, p2_claim)
        VALUES (?, ?, ?, ?, ?, '', '', 1, 1, NULL, 'playing', 'win', 'lose')
        """,
        (mid_b, u1, u2, 'FIFA', 0.5)
    )
    db.commit()
    bal_before = get_balance(u1)
    process_result(mid_b)
    cur.execute("SELECT status, winner FROM matches WHERE match_id=?", (mid_b,))
    st2, w2 = cur.fetchone()
    assert st2 == 'finished' and w2 == u1
    assert abs(get_balance(u1) - (bal_before + 1.0)) < 1e-9

    # 3c) both LOSE -> refund both
    mid_c = 'm_c'
    cur.execute(
        """
        INSERT OR REPLACE INTO matches (match_id, p1, p2, game, stake, wallet1, wallet2, paid1, paid2, winner, status, p1_claim, p2_claim)
        VALUES (?, ?, ?, ?, ?, '', '', 1, 1, NULL, 'playing', 'lose', 'lose')
        """,
        (mid_c, u1, u2, 'FIFA', 0.7)
    )
    db.commit()
    b1_before = get_balance(u1)
    b2_before = get_balance(u2)
    process_result(mid_c)
    assert abs(get_balance(u1) - (b1_before + 0.7)) < 1e-9
    assert abs(get_balance(u2) - (b2_before + 0.7)) < 1e-9

    print('SELF_TEST OK')

# -----------------------
# Main
# -----------------------
if __name__ == "__main__":
    if os.getenv('SELF_TEST') == '1':
        run_sanity_tests()
        sys.exit(0)
    logging.info("🤖 Versus Arena Bot starting...")
    threading.Thread(target=payment_scanner, daemon=True).start()
    bot.infinity_polling()

