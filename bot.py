import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import time
import threading
import requests
import sqlite3

BOT_TOKEN = 'HIER_DEIN_BOT_TOKEN'
BOT_WALLET = 'DEINE_SOLANA_WALLET_ADRESSE'
RPC_URL = 'https://api.mainnet-beta.solana.com'
ADMIN_ID = 123456789  # Ersetze mit echter Telegram-ID

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

# SQLite
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

# Hilfsfunktionen für DB
def save_user(uid, username, wallet='', balance=0.0):
    cursor.execute('INSERT OR REPLACE INTO users (user_id, username, wallet, balance) VALUES (?, ?, ?, ?)',
                   (uid, username, wallet, balance))
    conn.commit()

def update_balance(uid, balance):
    cursor.execute('UPDATE users SET balance = ? WHERE user_id = ?', (balance, uid))
    conn.commit()

def update_wallet(uid, wallet):
    cursor.execute('UPDATE users SET wallet = ? WHERE user_id = ?', (wallet, uid))
    conn.commit()

def save_match(match_id, match):
    cursor.execute('''
    INSERT OR REPLACE INTO matches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        match_id,
        match['p1'], match['p2'], match['game'], match['stake'],
        match['wallets'].get(match['p1'], ''),
        match['wallets'].get(match['p2'], ''),
        int(match['paid'].get(match['p1'], False)),
        int(match['paid'].get(match['p2'], False)),
        match['results'].get(match['p1'], ''),
        match['results'].get(match['p2'], '')
    ))
    conn.commit()

def delete_match(match_id):
    cursor.execute('DELETE FROM matches WHERE match_id = ?', (match_id,))
    conn.commit()

def load_users():
    cursor.execute('SELECT * FROM users')
    return {row[0]: {'username': row[1], 'wallet': row[2], 'balance': row[3]} for row in cursor.fetchall()}

def load_matches():
    cursor.execute('SELECT * FROM matches')
    matches = {}
    for row in cursor.fetchall():
        match_id = row[0]
        matches[match_id] = {
            'p1': row[1], 'p2': row[2], 'game': row[3], 'stake': row[4],
            'wallets': {row[1]: row[5], row[2]: row[6]},
            'paid': {row[1]: bool(row[7]), row[2]: bool(row[8])},
            'results': {row[1]: row[9], row[2]: row[10]}
        }
    return matches

users = load_users()
matches = load_matches()
states = {}
games = ['FIFA', 'Fortnite', 'Call of Duty', 'Mario Kart']
checked_signatures = set()

def main_menu(user_id):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎮 Match starten", callback_data="start_match"),
        InlineKeyboardButton("💰 Guthaben anzeigen", callback_data="balance")
    )
    markup.add(
        InlineKeyboardButton("📤 Auszahlung", callback_data="withdraw"),
        InlineKeyboardButton("ℹ️ Hilfe", callback_data="help")
    )
    bot.send_message(user_id, "🏠 <b>Hauptmenü</b>\n\nWähle eine Option:", reply_markup=markup)

@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id
    username = msg.from_user.username or f'user{uid}'
    if uid not in users:
        users[uid] = {'username': username, 'wallet': '', 'balance': 0.0}
        save_user(uid, username)
    main_menu(uid)

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    uid = call.from_user.id
    data = call.data
    if data == "start_match":
        markup = InlineKeyboardMarkup()
        for game in games:
            markup.add(InlineKeyboardButton(game, callback_data=f"game_{game}"))
        bot.edit_message_text("🎮 Wähle ein Spiel:", uid, call.message.message_id, reply_markup=markup)

    elif data.startswith("game_"):
        game = data[5:]
        states[uid] = {'step': 'opponent', 'game': game}
        bot.send_message(uid, "👤 Gegner-Telegram-Username (ohne @) eingeben:")

    elif data == "balance":
        bal = users[uid]['balance']
        bot.send_message(uid, f"💼 Dein Guthaben: <b>{bal:.4f} SOL</b>")

    elif data == "withdraw":
        states[uid] = {'step': 'withdraw'}
        bot.send_message(uid, "💸 Betrag zur Auszahlung in SOL?")

    elif data == "help":
        bot.send_message(uid, "ℹ️ Hilfe:\n\n- Match starten\n- Einsatz senden\n- Ergebnis eingeben\n- Guthaben auszahlen")

@bot.message_handler(func=lambda m: m.from_user.id in states)
def handle_state(msg):
    uid = msg.from_user.id
    state = states[uid]
    if state['step'] == 'opponent':
        name = msg.text.strip().lstrip('@')
        opponent = next((u for u in users if users[u]['username'] == name), None)
        if not opponent:
            bot.send_message(uid, "❌ Gegner nicht gefunden.")
            states.pop(uid)
            return
        state['opponent_id'] = opponent
        state['step'] = 'stake'
        bot.send_message(uid, "💵 Einsatz in SOL:")

    elif state['step'] == 'stake':
        try:
            stake = float(msg.text)
            state['stake'] = stake
            state['step'] = 'wallet'
            bot.send_message(uid, "🔑 Deine Solana-Wallet (Absender):")
        except:
            bot.send_message(uid, "❌ Ungültiger Betrag.")

    elif state['step'] == 'wallet':
        match_id = str(int(time.time()))
        p2 = state['opponent_id']
        matches[match_id] = {
            'p1': uid, 'p2': p2, 'game': state['game'], 'stake': state['stake'],
            'wallets': {uid: msg.text.strip(), p2: ''},
            'paid': {uid: False, p2: False},
            'results': {}
        }
        save_match(match_id, matches[match_id])
        states[p2] = {'step': 'wallet_join', 'match_id': match_id}
        bot.send_message(p2, f"🎮 Match-Einladung von @{users[uid]['username']} in {state['game']}.\nEinsatz: {state['stake']} SOL.\nBitte sende deine Wallet:")
        bot.send_message(uid, f"✅ Match erstellt. Sende {state['stake']} SOL an:\n<code>{BOT_WALLET}</code>")
        states.pop(uid)

    elif state['step'] == 'wallet_join':
        match_id = state['match_id']
        matches[match_id]['wallets'][uid] = msg.text.strip()
        save_match(match_id, matches[match_id])
        bot.send_message(uid, f"✅ Wallet gespeichert. Bitte sende {matches[match_id]['stake']} SOL an:\n<code>{BOT_WALLET}</code>")
        states.pop(uid)

    elif state['step'] == 'withdraw':
        try:
            amount = float(msg.text)
            if amount > users[uid]['balance']:
                bot.send_message(uid, "❌ Nicht genug Guthaben.")
                return
            users[uid]['balance'] -= amount
            update_balance(uid, users[uid]['balance'])
            bot.send_message(uid, "✅ Auszahlung in Bearbeitung (1–2 Std).")
            bot.send_message(ADMIN_ID, f"📤 Auszahlung von @{users[uid]['username']} – {amount} SOL.")
            states.pop(uid)
        except:
            bot.send_message(uid, "❌ Ungültiger Betrag.")

@bot.message_handler(commands=['ergebnis'])
def cmd_result(msg):
    uid = msg.from_user.id
    match_id = next((m for m in matches if uid in matches[m]['results'] and not matches[m]['results'][uid]), None)
    if not match_id:
        bot.send_message(uid, "❌ Kein aktives Match.")
        return
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("🏆 Gewonnen", callback_data=f"res_win_{match_id}"),
        InlineKeyboardButton("❌ Verloren", callback_data=f"res_lose_{match_id}"),
        InlineKeyboardButton("🤝 Unentschieden", callback_data=f"res_draw_{match_id}")
    )
    bot.send_message(uid, "❓ Ergebnis wählen:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("res_"))
def result_handler(call):
    uid = call.from_user.id
    _, res, match_id = call.data.split("_")
    match = matches.get(match_id)
    if not match:
        bot.answer_callback_query(call.id, "❌ Match nicht gefunden.", show_alert=True)
        return
    match['results'][uid] = res
    if uid == match['p1']:
        cursor.execute('UPDATE matches SET result1 = ? WHERE match_id = ?', (res, match_id))
    elif uid == match['p2']:
        cursor.execute('UPDATE matches SET result2 = ? WHERE match_id = ?', (res, match_id))
    conn.commit()
    bot.send_message(uid, f"✅ Ergebnis gespeichert: {res}")
    if match['results'].get(match['p1']) and match['results'].get(match['p2']):
        r1 = match['results'][match['p1']]
        r2 = match['results'][match['p2']]
        msg = ""
        if r1 == r2 == "draw":
            users[match['p1']]['balance'] += match['stake']
            users[match['p2']]['balance'] += match['stake']
            update_balance(match['p1'], users[match['p1']]['balance'])
            update_balance(match['p2'], users[match['p2']]['balance'])
            msg = "🤝 Unentschieden! Einsatz zurück."
        elif r1 == "win" and r2 == "lose":
            users[match['p1']]['balance'] += match['stake'] * 2
            update_balance(match['p1'], users[match['p1']]['balance'])
            msg = f"🏆 @{users[match['p1']]['username']} hat gewonnen!"
        elif r2 == "win" and r1 == "lose":
            users[match['p2']]['balance'] += match['stake'] * 2
            update_balance(match['p2'], users[match['p2']]['balance'])
            msg = f"🏆 @{users[match['p2']]['username']} hat gewonnen!"
        else:
            msg = "⚠️ Streitfall! Admin wird benachrichtigt."
            bot.send_message(ADMIN_ID, f"🚨 Streitfall im Match {match_id}")
        bot.send_message(match['p1'], msg)
        bot.send_message(match['p2'], msg)
        delete_match(match_id)
        matches.pop(match_id, None)

bot.infinity_polling()

