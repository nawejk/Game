import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import time
import threading
import requests

BOT_TOKEN = '8447925570:AAG5LsRoHfs3UXTJSgRa2PMjcrR291iDqfo'
BOT_WALLET = 'CKZEpwiVqAHLiSbdc8Ebf8xaQ2fofgPCNmzi4cV32M1s'
RPC_URL = 'https://api.mainnet-beta.solana.com'
ADMIN_ID = 7919108078

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

users = {}
matches = {}
states = {}
checked_signatures = set()
games = ['FIFA', 'Fortnite', 'Call of Duty', 'Mario Kart']

def main_menu(user_id):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🎮 Match starten", callback_data="start_match"))
    markup.add(InlineKeyboardButton("💰 Guthaben", callback_data="balance"))
    markup.add(InlineKeyboardButton("📤 Auszahlung", callback_data="withdraw"))
    bot.send_message(user_id, "🏠 Hauptmenü", reply_markup=markup)

@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id
    users.setdefault(uid, {'username': msg.from_user.username or f'user{uid}', 'wallet': '', 'balance': 0.0})
    main_menu(uid)

@bot.callback_query_handler(func=lambda call: True)
def menu_handler(call):
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
        bot.send_message(uid, "👤 Gib den Telegram-Username deines Gegners ein (ohne @):")

    elif data == "balance":
        bal = users[uid]['balance']
        bot.answer_callback_query(call.id)
        bot.send_message(uid, f"💼 Dein Guthaben: <b>{bal:.4f} SOL</b>", parse_mode="HTML")

    elif data == "withdraw":
        bot.send_message(uid, "💸 Wie viel möchtest du auszahlen?")
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
            bot.send_message(uid, "❌ Gegner nicht gefunden. Beide müssen zuerst /start eingeben.")
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
            bot.send_message(uid, "❌ Ungültiger Betrag. Bitte erneut eingeben.")

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
        states[p2] = {'step': 'wallet_join', 'match_id': match_id}
        bot.send_message(p2, f"👋 @{users[p1]['username']} hat dich zu einem Match in <b>{game}</b> eingeladen.\n💵 Einsatz: {stake} SOL\n\nBitte sende deine Wallet-Adresse (Absender):", parse_mode="HTML")
        bot.send_message(p1, f"✅ Match erstellt. Bitte sende <b>{stake} SOL</b> an:\n<code>{BOT_WALLET}</code>", parse_mode="HTML")
        states.pop(uid)

    elif state['step'] == 'wallet_join':
        match_id = state['match_id']
        matches[match_id]['wallets'][uid] = msg.text.strip()
        stake = matches[match_id]['stake']
        bot.send_message(uid, f"✅ Wallet gespeichert. Bitte sende <b>{stake} SOL</b> an:\n<code>{BOT_WALLET}</code>", parse_mode="HTML")
        states.pop(uid)

    elif state['step'] == 'withdraw':
        try:
            amount = float(msg.text.strip())
            if amount > users[uid]['balance']:
                bot.send_message(uid, "❌ Du hast nicht genug Guthaben.")
                return
            users[uid]['balance'] -= amount
            bot.send_message(uid, "✅ Deine Auszahlung wird bearbeitet (1–2 Stunden).")
            bot.send_message(ADMIN_ID, f"📤 @{users[uid]['username']} möchte {amount} SOL auszahlen.")
            states.pop(uid)
        except:
            bot.send_message(uid, "❌ Ungültiger Betrag.")

@bot.message_handler(commands=['ergebnis'])
def cmd_result(msg):
    uid = msg.from_user.id
    match_id = None
    for mid, m in matches.items():
        if uid in m['paid'] and all(m['paid'].values()):
            match_id = mid
            break
    if not match_id:
        bot.send_message(uid, "❌ Kein aktives Match mit vollständiger Zahlung gefunden.")
        return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🏆 Gewonnen", callback_data=f"res_win_{match_id}"))
    markup.add(InlineKeyboardButton("❌ Verloren", callback_data=f"res_lose_{match_id}"))
    markup.add(InlineKeyboardButton("🤝 Unentschieden", callback_data=f"res_draw_{match_id}"))
    bot.send_message(uid, "❓ Was ist dein Ergebnis?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("res_"))
def result_handler(call):
    uid = call.from_user.id
    _, res, match_id = call.data.split("_")
    match = matches.get(match_id)
    if not match:
        bot.send_message(uid, "❌ Match nicht gefunden.")
        return
    match['results'][uid] = res
    bot.send_message(uid, f"✅ Dein Ergebnis wurde gespeichert: {res}")
    if len(match['results']) == 2:
        r1 = match['results'][match['p1']]
        r2 = match['results'][match['p2']]
        if r1 == r2 == "draw":
            users[match['p1']]['balance'] += match['stake']
            users[match['p2']]['balance'] += match['stake']
            msg = "🤝 Unentschieden! Einsatz zurück."
        elif r1 == "win" and r2 == "lose":
            users[match['p1']]['balance'] += match['stake'] * 2
            msg = f"🏆 @{users[match['p1']]['username']} hat gewonnen!"
        elif r2 == "win" and r1 == "lose":
            users[match['p2']]['balance'] += match['stake'] * 2
            msg = f"🏆 @{users[match['p2']]['username']} hat gewonnen!"
        else:
            msg = "⚠️ Streitfall! Admin wird informiert."
            bot.send_message(ADMIN_ID, f"🚨 Streitfall im Match {match_id} zwischen @{users[match['p1']]['username']} und @{users[match['p2']]['username']}.")
        bot.send_message(match['p1'], msg)
        bot.send_message(match['p2'], msg)
        del matches[match_id]

def check_payments():
    while True:
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [BOT_WALLET, {"limit": 25}]
            }
            res = requests.post(RPC_URL, json=payload).json()
            for tx in res.get("result", []):
                sig = tx['signature']
                if sig in checked_signatures:
                    continue
                checked_signatures.add(sig)
                tx_data = get_tx_details(sig)
                if not tx_data:
                    continue
                sender, amount = tx_data['from'], tx_data['amount']
                for m_id, m in matches.items():
                    for uid, w in m['wallets'].items():
                        if w == sender and not m['paid'][uid] and amount >= m['stake']:
                            m['paid'][uid] = True
                            bot.send_message(uid, f"✅ Zahlung über {amount} SOL erkannt.")
                            if all(m['paid'].values()):
                                bot.send_message(m['p1'], "✅ Beide Spieler haben gezahlt. Bitte /ergebnis senden.")
                                bot.send_message(m['p2'], "✅ Beide Spieler haben gezahlt. Bitte /ergebnis senden.")
        except Exception as e:
            print("Fehler beim Prüfen der Zahlung:", e)
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
                sol = lamports / 1e9
                return {"from": info['source'], "amount": sol}
    except:
        return None

# Start des Hintergrund-Threads
threading.Thread(target=check_payments, daemon=True).start()
print("🤖 Bot läuft...")
bot.infinity_polling()