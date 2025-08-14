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
INVESTOR_GROUP_LINK = 'https://t.me/+dW-n4_Yw7_Q1OTFi'
HELP_CONTACT = '@nadjad_crpt,@NkryptoN'

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

# ======================
# DB Setup + Migration
# ======================
db = sqlite3.connect("gamebot.db", check_same_thread=False)
cur = db.cursor()

# Tabellen (falls komplett neu)
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
    -- 'status' wird ggf. unten via Migration ergänzt
)''')

# NEW: Investments (whitelist)
cur.execute('''CREATE TABLE IF NOT EXISTS investments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount REAL,
    wallet TEXT,
    paid INTEGER DEFAULT 0,
    created_at INTEGER
)''')

db.commit()

def column_exists(table, col):
    c = db.cursor()
    c.execute(f"PRAGMA table_info({table})")
    return any(row[1] == col for row in c.fetchall())

def ensure_schema():
    c = db.cursor()
    # matches.status nachrüsten, wenn fehlt
    if not column_exists('matches', 'status'):
        c.execute("ALTER TABLE matches ADD COLUMN status TEXT DEFAULT 'waiting'")
        db.commit()
        c.execute("UPDATE matches SET status='waiting' WHERE status IS NULL")
        db.commit()
    # (weitere Migrationen könnten hier ergänzt werden)

ensure_schema()

# ======================
# Bot State
# ======================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

states = {}
checked_signatures = set()
games = ['FIFA', 'Fortnite', 'Call of Duty', 'Mario Kart']

# -----------------------
# Helferfunktionen (DB)
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
        # NEW: Whitelist + Help
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

def handle_result_button(uid, mid):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🏆 I won", callback_data=f"win_{mid}"))
    bot.send_message(uid, "❓ Report result:", reply_markup=markup)

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
        user_info = get_user_info_text(uid)
        bot.edit_message_text(user_info + "🎮 Select a game:", call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif data.startswith("game_"):
        game = data[5:]
        states[uid] = {'step': 'opponent', 'game': game}
        user_info = get_user_info_text(uid)
        bot.edit_message_text(user_info + "👤 Opponent username (without @):", call.message.chat.id, call.message.message_id)

    elif data == "balance":
        bal = get_balance(uid)
        user_info = get_user_info_text(uid)
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🏠 Back to Menu", callback_data="back_to_menu"))
        bot.edit_message_text(user_info + f"💰 Your balance: <b>{bal:.4f} SOL</b>",
                              call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif data == "deposit":
        cur.execute("SELECT wallet FROM users WHERE user_id=?", (uid,))
        r = cur.fetchone()
        wallet = r[0] if r and r[0] else None
        user_info = get_user_info_text(uid)
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🏠 Back to Menu", callback_data="back_to_menu"))
        if not wallet:
            states[uid] = {'step': 'deposit_wallet'}
            bot.edit_message_text(user_info + "🔑 Please send your wallet address for deposits:",
                                  call.message.chat.id, call.message.message_id, reply_markup=markup)
        else:
            bot.edit_message_text(user_info + f"📥 Send SOL to:\n<code>{BOT_WALLET}</code>",
                                  call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif data == "withdraw":
        states[uid] = {'step': 'withdraw'}
        user_info = get_user_info_text(uid)
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("❌ Cancel", callback_data="back_to_menu"))
        bot.edit_message_text(user_info + "💸 Enter amount to withdraw:",
                              call.message.chat.id, call.message.message_id, reply_markup=markup)

    # NEW: Whitelist flow entry
    elif data == "whitelist":
        user_info = get_user_info_text(uid)
        text = (
            user_info +
            "<b>🟢 Versus Arena – Whitelist Access</b>\n\n"
            "Get early access to buy the Versus Arena token before public launch.\n"
            "• Minimum investment: <b>1 SOL</b>\n"
            "• Investing now gives an approximate entry at a $20–25K market cap.\n"
            "• Your funds support launch & liquidity.\n"
            "• After payment is detected on-chain, you will be marked as <b>invested</b> and invited to the investor group.\n\n"
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
        bot.edit_message_text(user_info + "💵 Enter the amount to invest in SOL (min 1 SOL):",
                              call.message.chat.id, call.message.message_id, reply_markup=markup)

    # NEW: Help / Questions
    elif data == "help":
        user_info = get_user_info_text(uid)
        text = (
            user_info +
            "<b>🆘 Help / Questions</b>\n\n"
            f"If you need help or have any questions, please contact {HELP_CONTACT}.\n"
            "We are happy to assist you."
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

    elif data.startswith("win_"):
        mid = data.split("_", 1)[1]
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
        bot.send_message(uid, "📨 The admin has been informed. Please send any evidence if necessary.")
        mid = data.split("_", 1)[1]
        cur.execute("SELECT p1, p2, game, stake FROM matches WHERE match_id=?", (mid,))
        match_info = cur.fetchone()
        if match_info:
            p1, p2, game, stake = match_info
            dispute_msg = (f"🚨 DISPUTE REPORTED 🚨\n"
                           f"Match ID: {mid}\n"
                           f"Player 1: @{get_username(p1)}\n"
                           f"Player 2: @{get_username(p2)}\n"
                           f"Game: {game}\n"
                           f"Stake: {stake} SOL\n"
                           f"Disputed by: @{get_username(uid)}")
            for admin in (ADMIN_ID, ADMIN_ID_2):
                try:
                    bot.send_message(admin, dispute_msg)
                except Exception:
                    pass

    # NEW: Verify investment payment button
    elif data.startswith("invest_check_"):
        inv_id = int(data.split("_", 2)[2])
        if verify_invest_payment_once(inv_id):
            try:
                # Success message sent inside verification, but reply anyway
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

        cur.execute("""
            INSERT INTO matches (match_id, p1, p2, game, stake, wallet1, wallet2, paid1, paid2, winner, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, NULL, 'waiting')
        """, (mid, uid, opp, state['game'], state['stake'], wallet, ''))
        db.commit()

        if pay_with_balance:
            cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (state['stake'], uid))
            cur.execute("UPDATE matches SET paid1=1 WHERE match_id=?", (mid,))
            db.commit()
            bot.send_message(uid, f"✅ You paid with your balance. The match will start once your opponent pays.")
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
            bot.send_message(uid, f"✅ You paid with your balance. Checking if both players have paid...")

            cur.execute("SELECT p1, p2, paid1, paid2 FROM matches WHERE match_id=?", (mid,))
            p1, p2, paid1, paid2 = cur.fetchone()
            if paid1 and paid2:
                for pid in (p1, p2):
                    bot.send_message(pid, "✅ Both players have paid. The match can start now!")
                    handle_result_button(pid, mid)
                cur.execute("UPDATE matches SET status='playing' WHERE match_id=?", (mid,))
                db.commit()

        elif answer in ('no', 'n'):
            bot.send_message(uid, f"✅ Please send {stake} SOL to:\n<code>{BOT_WALLET}</code>")
        else:
            bot.send_message(uid, "❌ Please reply with 'yes' or 'no'.")
            return
        states.pop(uid)

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

            withdrawal_msg = f"💸 WITHDRAWAL REQUEST\nUser: @{get_username(uid)}\nAmount: {amount:.4f} SOL\nUser ID: {uid}"
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
        bot.send_message(uid, user_info + f"✅ Wallet saved.\nNow send SOL to:\n<code>{BOT_WALLET}</code>")
        states.pop(uid)

    # NEW: Investment flow states
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
            bot.send_message(uid, user_info + "🔑 Please provide the Solana wallet you'll use to send the investment:", reply_markup=markup)
        except:
            bot.send_message(uid, "❌ Invalid amount. Please enter a valid number.")

    elif state['step'] == 'invest_wallet':
        wallet = msg.text.strip()
        if len(wallet) < 20:
            bot.send_message(uid, "❌ Invalid wallet address. Please provide a valid Solana wallet address.")
            return
        amount = state['amount']
        # Save user wallet for convenience
        cur.execute("UPDATE users SET wallet=? WHERE user_id=?", (wallet, uid))
        # Create investment record
        created_at = int(time.time())
        cur.execute("INSERT INTO investments (user_id, amount, wallet, created_at) VALUES (?, ?, ?, ?)", (uid, amount, wallet, created_at))
        inv_id = cur.lastrowid
        db.commit()

        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("✅ I've paid – check now", callback_data=f"invest_check_{inv_id}"),
            InlineKeyboardButton("🏠 Back to Menu", callback_data="back_to_menu")
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
    """Holt neue Signaturen für BOT_WALLET. Vermeidet Duplikate via checked_signatures."""
    try:
        res = rpc("getSignaturesForAddress", [address, {"limit": limit}])
        arr = res.get("result") or []
        sigs = []
        for item in arr:
            sig = item.get("signature")
            if sig and sig not in checked_signatures:
                sigs.append(sig)
        sigs.reverse()  # älteste zuerst verarbeiten
        return sigs
    except Exception as e:
        logging.warning("getSignaturesForAddress error: %s", e)
        return []


def get_tx_details(sig):
    """
    Ermittelt tatsächliche SOL-Zunahme auf BOT_WALLET.
    Liefert {'from': sender_pubkey, 'amount': sol_amount, 'blockTime': block_time} oder None.
    """
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

        # Sender heuristisch finden (größte Abnahme ~ delta)
        sender = None
        for i, (p, po) in enumerate(zip(pre, post)):
            if p - po >= delta - 1000:
                sender = keys[i]
                break

        # Fallback: parsed instructions
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
# Payment Scanner Thread
# -----------------------

def mark_paid_if_match(sender_wallet, amount_sol):
    """
    Markiert Zahlung in offenen Matches und verschickt ggf. Start/Result-Buttons.
    Gibt True zurück, wenn Zahlung einem Match zugeordnet wurde.
    """
    assigned = False

    cur.execute("""SELECT match_id, p1, p2, wallet1, wallet2, stake, paid1, paid2
                   FROM matches
                   WHERE status='waiting'""")
    rows = cur.fetchall()

    for mid, p1, p2, w1, w2, stake, paid1, paid2 in rows:
        updated = False
        # Auto-assign Wallets, falls leer
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

        # Flags setzen, wenn Betrag >= Stake
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

        # Beide bezahlt?
        if paid1 and paid2:
            for pid in (p1, p2):
                try:
                    bot.send_message(pid, "✅ Both players have paid. The match can start now!")
                    handle_result_button(pid, mid)
                except Exception:
                    pass
            cur.execute("UPDATE matches SET status='playing' WHERE match_id=?", (mid,))
            db.commit()

    return assigned


def mark_paid_if_invest(sender_wallet, amount_sol, block_time):
    """Markiert Zahlung als Investment, wenn Wallet/Amount passt."""
    assigned = False
    cur.execute("SELECT id, user_id, amount, wallet, paid, created_at FROM investments WHERE paid=0 AND wallet=?", (sender_wallet,))
    rows = cur.fetchall()
    for inv_id, user_id, amount_req, wallet, paid, created_at in rows:
        # Betrag reicht & TX ist nicht deutlich vor Start erstellt
        if amount_sol + 1e-12 >= amount_req and (not block_time or block_time >= (created_at - 600)):
            cur.execute("UPDATE investments SET paid=1 WHERE id=?", (inv_id,))
            db.commit()
            try:
                bot.send_message(user_id, (
                    "🎉 <b>Investment confirmed!</b>\n\n"
                    f"Amount: <b>{amount_req:.4f} SOL</b>\n"
                    f"Wallet: <code>{wallet}</code>\n\n"
                    f"Welcome! Join the investor group: <a href='{INVESTOR_GROUP_LINK}'>Open Telegram</a>"
                ))
            except Exception:
                pass
            # Notify admins
            info = f"✅ INVESTMENT\nUser: @{get_username(user_id)}\nAmount: {amount_req:.4f} SOL\nWallet: {wallet}\nID: {inv_id}"
            for admin in (ADMIN_ID, ADMIN_ID_2):
                try:
                    bot.send_message(admin, info)
                except Exception:
                    pass
            assigned = True
    return assigned


def credit_general_deposit(sender_wallet, amount_sol):
    """Einzahlung außerhalb eines Matches -> direkt auf User-Balance gutschreiben."""
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

                # 1) Erst versuchen, Zahlung einem offenen Match zuzuordnen
                matched_match = mark_paid_if_match(sender, amount)

                # 2) Dann versuchen, Investment zuzuordnen
                matched_invest = mark_paid_if_invest(sender, amount, block_time)

                # 3) Falls kein Match/Investment betroffen -> allgemeine Einzahlung
                if not (matched_match or matched_invest):
                    credit_general_deposit(sender, amount)

        except Exception as e:
            logging.warning("Scanner loop error: %s", e)

        time.sleep(8)

# -----------------------
# One-off verification for investments (on button press)
# -----------------------

def verify_invest_payment_once(inv_id):
    cur.execute("SELECT user_id, amount, wallet, paid, created_at FROM investments WHERE id=?", (inv_id,))
    row = cur.fetchone()
    if not row:
        return False
    user_id, amount_req, wallet, paid, created_at = row
    if paid:
        # Already marked
        try:
            bot.send_message(user_id, (
                "🎉 <b>Investment already confirmed</b>\n"
                f"Amount: <b>{amount_req:.4f} SOL</b>\n"
                f"Wallet: <code>{wallet}</code>\n"
                f"Investor group: <a href='{INVESTOR_GROUP_LINK}'>Open Telegram</a>"
            ))
        except Exception:
            pass
        return True

    # Pull recent signatures and try to match
    try:
        res = rpc("getSignaturesForAddress", [BOT_WALLET, {"limit": 100}])
        arr = res.get('result') or []
        for item in arr:
            sig = item.get('signature')
            if not sig:
                continue
            # Optional: time filter
            btime = item.get('blockTime') or 0
            if created_at and btime and btime < (created_at - 600):
                continue
            details = get_tx_details(sig)
            if not details:
                continue
            if details.get('from') == wallet and details.get('amount', 0) + 1e-12 >= amount_req:
                # mark paid
                cur.execute("UPDATE investments SET paid=1 WHERE id=?", (inv_id,))
                db.commit()
                try:
                    bot.send_message(user_id, (
                        "🎉 <b>Investment confirmed!</b>\n\n"
                        f"Amount: <b>{amount_req:.4f} SOL</b>\n"
                        f"Wallet: <code>{wallet}</code>\n\n"
                        f"Welcome! Join the investor group: <a href='{INVESTOR_GROUP_LINK}'>Open Telegram</a>"
                    ))
                except Exception:
                    pass
                # notify admins
                info = f"✅ INVESTMENT\nUser: @{get_username(user_id)}\nAmount: {amount_req:.4f} SOL\nWallet: {wallet}\nID: {inv_id}"
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
# Main
# -----------------------
if __name__ == "__main__":
    logging.info("🤖 Versus Arena Bot starting...")
    threading.Thread(target=payment_scanner, daemon=True).start()
    bot.infinity_polling()
