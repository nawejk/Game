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

# SQLite Setup
conn = sqlite3.connect('bot_database.db', check_same_thread=False)
cursor = conn.cursor()

# Tabellen erstellen
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

# DB-Funktionen Users
def save_user(user_id, username, wallet='', balance=0.0):
    cursor.execute('''
    INSERT OR REPLACE INTO users (user_id, username, wallet, balance) VALUES (?, ?, ?, ?)
    ''', (user_id, username, wallet, balance))
    conn.commit()

def load_user(user_id):
    cursor.execute('SELECT user_id, username, wallet, balance FROM users WHERE user_id = ?', (user_id,))
    return cursor.fetchone()

def update_balance(user_id, amount):
    cursor.execute('UPDATE users SET balance = ? WHERE user_id = ?', (amount, user_id))
    conn.commit()

def update_wallet(user_id, wallet):
    cursor.execute('UPDATE users SET wallet = ? WHERE user_id = ?', (wallet, user_id))
    conn.commit()

def load_all_users():
    cursor.execute('SELECT user_id, username, wallet, balance FROM users')
    return cursor.fetchall()

# DB-Funktionen Matches
def save_match(match_id, match):
    cursor.execute('''
    INSERT OR REPLACE INTO matches (match_id, p1, p2, game, stake, wallet1, wallet2, paid1, paid2, result1, result2)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        match_id,
        match['p1'],
        match['p2'],
        match['game'],
        match['stake'],
        match['wallets'].get(match['p1'], ''),
        match['wallets'].get(match['p2'], ''),
        int(match['paid'].get(match['p1'], False)),
        int(match['paid'].get(match['p2'], False)),
        match['results'].get(match['p1'], ''),
        match['results'].get(match['p2'], ''),
    ))
    conn.commit()

def load_all_matches():
    cursor.execute('SELECT * FROM matches')
    rows = cursor.fetchall()
    matches = {}
    for row in rows:
        match_id = row[0]
        matches[match_id] = {
            'p1': row[1],
            'p2': row[2],
            'game': row[3],
            'stake': row[4],
            'wallets': {row[1]: row[5], row[2]: row[6]},
            'paid': {row[1]: bool(row[7]), row[2]: bool(row[8])},
            'results': {row[1]: row[9], row[2]: row[10]},
        }
    return matches

def delete_match(match_id):
    cursor.execute('DELETE FROM matches WHERE match_id = ?', (match_id,))
    conn.commit()

# States werden im RAM gespeichert
states = {}

# Lade Nutzer und Matches beim Start
users = {}
for u in load_all_users():
    users[u[0]] = {'username': u[1], 'wallet': u[2], 'balance': u[3]}

matches = load_all_matches()

games = ['FIFA', 'Fortnite', 'Call of Duty', 'Mario Kart']

def main_menu(user_id):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🎮 Match starten", callback_data="start_match"))
    markup.add(InlineKeyboardButton("💰 Guthaben", callback_data="balance"))
    markup.add(InlineKeyboardButton("📤 Auszahlung", callback_data="withdraw"))
    bot.send_message(user_id, "🏠 Hauptmenü", reply_markup=markup)

@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id
    username = msg.from_user.username or f'user{uid}'
    if uid not in users:
        users[uid] = {'username': username, 'wallet': '', 'balance': 0.0}
        save_user(uid, username)
    main_menu(uid)

@bot.callback_query_handler(func=lambda call: True)
def menu_handler(call):
    uid = call.from_user.id
    data = call.data

    if data == "start_match":
        markup = InlineKeyboardMarkup()
        for game in games:
            markup.add(InlineKeyboardButton(game, callback_data=f"game_{game}"))
        bot.edit_message_text("🎮 Wähle ein Spiel:", uid, call.message.message_id, reply_markup=markup)

    elif data.startswith("game_"):
        game = data[5:]
        states[uid] = {'step': 'opponent', 'game': game}
        bot.send_message(uid, "👤 Gib den Telegram-Username deines Gegners ein (ohne @):")

    elif data == "balance":
        bal = users[uid]['balance']
        bot.answer_callback_query(call.id)
        bot.send_message(uid, f"💼 Dein Guthaben: <b>{bal:.4f} SOL</b>", parse_mode="HTML")

    elif data == "withdraw":
        bot.send_message(uid, "💸 Wie viel möchtest du auszahlen?")
        states[uid] = {'step': 'withdraw'}

@bot.message_handler(func=lambda m: m.from_user.id in states)
def state_handler(msg):
    uid = msg.from_user.id
    state = states[uid]

    if state['step'] == 'opponent':
        opponent_name = msg.text.strip().lstrip('@')
        opponent_id = None
        for u_id, u_data in users.items():
            if u_data['username'] == opponent_name:
                opponent_id = u_id
                break
        if not opponent_id:
            bot.send_message(uid, "❌ Gegner nicht gefunden. Beide müssen zuerst /start eingeben.")
            states.pop(uid)
            return
        state['opponent_id'] = opponent_id
        state['step'] = 'stake'
        bot.send_message(uid, "💵 Gib den Einsatz in SOL ein:")

    elif state['step'] == 'stake':
        try:
            stake = float(msg.text.strip())
            state['stake'] = stake
            state['step'] = 'wallet'
            bot.send_message(uid, "🔑 Gib deine Solana-Wallet-Adresse ein (Absender-Adresse):")
        except:
            bot.send_message(uid, "❌ Ungültiger Betrag. Bitte erneut eingeben.")

    elif state['step'] == 'wallet':
        wallet = msg.text.strip()
        match_id = str(int(time.time()))
        p1 = uid
        p2 = state['opponent_id']
        game = state['game']
        stake = state['stake']
        matches[match_id] = {
            'p1': p1, 'p2': p2, 'game': game, 'stake': stake,
            'wallets': {p1: wallet, p2: ''},
            'paid': {p1: False, p2: False},
            'results': {}
        }
        save_match(match_id, matches[match_id])
        states[p2] = {'step': 'wallet_join', 'match_id': match_id}
        bot.send_message(p2, f"👋 @{users[p1]['username']} hat dich zu einem Match in <b>{game}</b> eingeladen.\n💵 Einsatz: {stake} SOL\n\nBitte sende deine Wallet-Adresse (Absender):", parse_mode="HTML")
        bot.send_message(p1, f"✅ Match erstellt. Bitte sende <b>{stake} SOL</b> an:\n<code>{BOT_WALLET}</code>", parse_mode="HTML")
        states.pop(uid)