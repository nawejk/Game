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

conn = sqlite3.connect('bot_database.db', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    wallet TEXT,
    balance REAL
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS matches (
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
)
''')
conn.commit()

users = {}
matches = {}
states = {}
games = ['FIFA', 'Fortnite', 'Call of Duty', 'Mario Kart']
checked_signatures = set()

def save_user(uid, username, wallet='', balance=0.0):
    cursor.execute('INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?)', (uid, username, wallet, balance))
    conn.commit()

def update_balance(uid, balance):
    cursor.execute('UPDATE users SET balance = ? WHERE user_id = ?', (balance, uid))
    conn.commit()

def get_balance(uid):
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (uid,))
    row = cursor.fetchone()
    return row[0] if row else 0.0

def save_match(mid, match):
    cursor.execute('''
    INSERT OR REPLACE INTO matches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        mid,
        match['p1'], match['p2'], match['game'], match['stake'],
        match['wallets'].get(match['p1'], ''),
        match['wallets'].get(match['p2'], ''),
        int(match['paid'].get(match['p1'], False)),
        int(match['paid'].get(match['p2'], False)),
        match['results'].get(match['p1'], ''),
        match['results'].get(match['p2'], '')
    ))
    conn.commit()

def delete_match(mid):
    cursor.execute('DELETE FROM matches WHERE match_id = ?', (mid,))
    conn.commit()

def main_menu(uid):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎮 Match starten", callback_data="start_match"),
        InlineKeyboardButton("💰 Guthaben", callback_data="balance"),
        InlineKeyboardButton("📤 Auszahlung", callback_data="withdraw")
    )
    bot.send_message(uid, "🏠 Hauptmenü", reply_markup=markup)

@bot.message_handler(commands=['start'])
def cmd_start(msg):
    uid = msg.from_user.id
    username = msg.from_user.username or f"user{uid}"
    users[uid] = {'username': username}
    save_user(uid, username)
    main_menu(uid)

@bot.callback_query_handler(func=lambda c: True)
def cb_handler(call):
    uid = call.from_user.id
    data = call.data

    if data == "start_match":
        markup = InlineKeyboardMarkup()
        for game in games:
            markup.add(InlineKeyboardButton(game, callback_data=f"game_{game}"))
        bot.edit_message_text("🎮 Spiel auswählen:", uid, call.message.message_id, reply_markup=markup)

    elif data.startswith("game_"):
        states[uid] = {'step': 'opponent', 'game': data[5:]}
        bot.send_message(uid, "👤 Username des Gegners (ohne @):")

    elif data == "balance":
        bal = get_balance(uid)
        bot.send_message(uid, f"💰 Dein Guthaben: <b>{bal:.4f} SOL</b>")

    elif data == "withdraw":
        states[uid] = {'step': 'withdraw'}
        bot.send_message(uid, "💸 Betrag zur Auszahlung (SOL):")

@bot.message_handler(func=lambda m: m.from_user.id in states)
def state_handler(msg):
    uid = msg.from_user.id
    state = states[uid]

    if state['step'] == 'opponent':
        opponent_name = msg.text.strip().lstrip('@')
        opponent_id = next((i for i, u in users.items() if u['username'] == opponent_name), None)
        if not opponent_id:
            bot.send_message(uid, "❌ Gegner nicht gefunden.")
            states.pop(uid)
            return
        state['opponent_id'] = opponent_id
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
        mid = str(int(time.time()))
        p2 = state['opponent_id']
        matches[mid] = {
            'p1': uid, 'p2': p2, 'game': state['game'], 'stake': state['stake'],
            'wallets': {uid: msg.text.strip(), p2: ''},
            'paid': {uid: False, p2: False},
            'results': {}
        }
        save_match(mid, matches[mid])
        states[p2] = {'step': 'wallet_join', 'match_id': mid}
        bot.send_message(p2, f"👋 Match-Einladung von @{users[uid]['username']} in {state['game']}!\nEinsatz: {state['stake']} SOL\n\nBitte sende deine Wallet:")
        bot.send_message(uid, f"✅ Sende <b>{state['stake']} SOL</b> an:\n<code>{BOT_WALLET}</code>")
        states.pop(uid)

    elif state['step'] == 'wallet_join':
        mid = state['match_id']
        matches[mid]['wallets'][uid] = msg.text.strip()
        save_match(mid, matches[mid])
        stake = matches[mid]['stake']
        bot.send_message(uid, f"✅ Sende <b>{stake} SOL</b> an:\n<code>{BOT_WALLET}</code>")
        states.pop(uid)

    elif state['step'] == 'withdraw':
        try:
            amount = float(msg.text.strip())
            balance = get_balance(uid)
            if amount > balance:
                bot.send_message(uid, "❌ Nicht genug Guthaben.")
                return
            new_balance = balance - amount
            update_balance(uid, new_balance)
            bot.send_message(uid, "✅ Deine Auszahlung wird bearbeitet (1–2 Stunden).")
            bot.send_message(ADMIN_ID, f"📤 @{users[uid]['username']} will {amount} SOL auszahlen.")
            states.pop(uid)
        except:
            bot.send_message(uid, "❌ Ungültiger Betrag.")

@bot.message_handler(commands=['ergebnis'])
def ergebnis_handler(msg):
    uid = msg.from_user.id
    match_id = next((m for m in matches if uid in matches[m]['wallets'] and all(matches[m]['paid'].values())), None)
    if not match_id:
        bot.send_message(uid, "❌ Kein bezahltes Match gefunden.")
        return
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("🏆 Gewonnen", callback_data=f"res_win_{match_id}"),
        InlineKeyboardButton("❌ Verloren", callback_data=f"res_lose_{match_id}"),
        InlineKeyboardButton("🤝 Unentschieden", callback_data=f"res_draw_{match_id}")
    )
    bot.send_message(uid, "Was ist dein Ergebnis?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("res_"))
def result_handler(call):
    uid = call.from_user.id
    _, res, mid = call.data.split("_")
    match = matches.get(mid)
    if not match:
        bot.send_message(uid, "❌ Match nicht gefunden.")
        return
    match['results'][uid] = res
    if len(match['results']) == 2:
        r1 = match['results'][match['p1']]
        r2 = match['results'][match['p2']]
        if r1 == r2 == "draw":
            for p in [match['p1'], match['p2']]:
                balance = get_balance(p)
                update_balance(p, balance + match['stake'])
            msg = "🤝 Unentschieden! Einsatz zurück."
        elif r1 == "win" and r2 == "lose":
            winner = match['p1']
            update_balance(winner, get_balance(winner) + match['stake'] * 2)
            msg = f"🏆 @{users[winner]['username']} hat gewonnen!"
        elif r2 == "win" and r1 == "lose":
            winner = match['p2']
            update_balance(winner, get_balance(winner) + match['stake'] * 2)
            msg = f"🏆 @{users[winner]['username']} hat gewonnen!"
        else:
            msg = "⚠️ Streitfall – Admin wurde benachrichtigt."
            bot.send_message(ADMIN_ID, f"🚨 Streitfall zwischen @{users[match['p1']]['username']} und @{users[match['p2']]['username']}")
        for p in [match['p1'], match['p2']]:
            bot.send_message(p, msg)
        delete_match(mid)
        matches.pop(mid, None)
    else:
        bot.send_message(uid, "✅ Dein Ergebnis wurde gespeichert.")

def check_payments():
    while True:
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [BOT_WALLET, {"limit": 25}]
            }
            r = requests.post(RPC_URL, json=payload).json()
            for tx in r.get("result", []):
                sig = tx["signature"]
                if sig in checked_signatures:
                    continue
                checked_signatures.add(sig)
                tx_data = get_tx_details(sig)
                if not tx_data:
                    continue
                sender, amount = tx_data['from'], tx_data['amount']
                for mid, match in matches.items():
                    for uid, w in match['wallets'].items():
                        if w == sender and not match['paid'][uid] and amount >= match['stake']:
                            match['paid'][uid] = True
                            save_match(mid, match)
                            bot.send_message(uid, f"✅ Zahlung über {amount:.4f} SOL erkannt.")
                            if all(match['paid'].values()):
                                bot.send_message(match['p1'], "✅ Beide Spieler haben gezahlt. Bitte /ergebnis senden.")
                                bot.send_message(match['p2'], "✅ Beide Spieler haben gezahlt. Bitte /ergebnis senden.")
        except Exception as e:
            print("Fehler bei Zahlungserkennung:", e)
        time.sleep(30)

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
                return {"from": info['source'], "amount": lamports / 1e9}
    except:
        return None

# Hintergrund-Thread starten
threading.Thread(target=check_payments, daemon=True).start()
print("🤖 Bot läuft...")
bot.infinity_polling()