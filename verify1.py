#!/usr/bin/env python3
"""
🔑 RAGEBITE KEY BOT (@KEY_SWARGBOT)
Multi-App Key Generator + Maintenance Control
"""

import telebot
import datetime
import os
import sqlite3
import random
import string
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# ==================== CONFIG ====================
BOT_TOKEN = "8823908635:AAHO373_iqEcipIOdhACahEO-3O-ZipA21g"
OWNER_ID = "6321758394"

DB_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ragebite.db')

APP_IDS = [
    "com.ragebite.app",
]
SLOTS_PER_APP = 4
PORT = int(os.environ.get("PORT", "8080"))

STATUS_ACTIVE = "ACTIVE"
STATUS_DELETED = "DELETED"
STATUS_DISABLED = "DISABLED"


def get_conn():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS keys (
        key TEXT PRIMARY KEY,
        device_id TEXT,
        expiry TEXT,
        status TEXT DEFAULT 'ACTIVE',
        slot_count INTEGER DEFAULT 4,
        app_id TEXT,
        created_at TEXT,
        generated_by TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('maintenance', 'off')")

    conn.commit()
    conn.close()


def get_maintenance():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key='maintenance'")
    row = c.fetchone()
    conn.close()
    return row[0] if row else "off"


def set_maintenance(value):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('maintenance', ?)", (value,))
    conn.commit()
    conn.close()


def generate_key(days, app_id, slot_count=4):
    key = "LTN-1M-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    expiry = (datetime.datetime.now() + datetime.timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')

    conn = get_conn()
    c = conn.cursor()
    c.execute('''INSERT INTO keys (key, device_id, expiry, status, slot_count, app_id, created_at, generated_by)
                 VALUES (?, NULL, ?, ?, ?, ?, ?, ?)''',
              (key, expiry, STATUS_ACTIVE, slot_count, app_id,
               datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
               str(OWNER_ID)))
    conn.commit()
    conn.close()
    return key, expiry


bot = telebot.TeleBot(BOT_TOKEN)


def is_owner(uid):
    return str(uid) == OWNER_ID


@bot.message_handler(commands=['start'])
def cmd_start(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "🚫 Only Owner")
        return

    apps_list = "\n".join([f"• `{a}`" for a in APP_IDS])
    maint = get_maintenance()
    maint_status = "🔴 ON" if maint == "on" else "🟢 OFF"

    bot.reply_to(message, f"""🔑 **RAGEBITE KEY BOT**

🔧 Maintenance: {maint_status}

📱 **Available Apps:**
{apps_list}

**Commands:**
`/genkey <days> <app_id> [slots]` — Generate key
`/listkeys [app_id]` — List keys
`/delkey <key>` — Delete
`/diskey <key>` — Disable
`/enkey <key>` — Enable
`/keyinfo <key>` — Info
`/resetbind <key>` — Reset device
`/cleankeys` — Clean expired
`/maintenance on|off` — Maintenance mode

**Example:**
`/genkey 30 com.ragebite.app 4`
""", parse_mode='Markdown')


@bot.message_handler(commands=['maintenance'])
def cmd_maintenance(message):
    if not is_owner(message.from_user.id):
        return

    command = message.text.split()

    if len(command) < 2:
        maint = get_maintenance()
        status = "🔴 ON" if maint == "on" else "🟢 OFF"

        bot.reply_to(message, f"""🔧 **MAINTENANCE STATUS**

Current: {status}

**Commands:**
`/maintenance on` — Block all APKs
`/maintenance off` — Resume all APKs

⚠️ When ON: Saare APKs block ho jaayenge
""", parse_mode='Markdown')
        return

    action = command[1].lower()

    if action == "on":
        set_maintenance("on")
        bot.reply_to(message, """🔧 **MAINTENANCE MODE: ON**

⚠️ Saare APKs ab **block** hain
📌 Koi bhi attack nahi lagega
📌 New keys bhi kaam nahi karengi

Use `/maintenance off` to resume.""", parse_mode='Markdown')

    elif action == "off":
        set_maintenance("off")
        bot.reply_to(message, """✅ **MAINTENANCE MODE: OFF**

📌 Saare APKs wapas active
📌 Attacks chalenge normally
""", parse_mode='Markdown')

    else:
        bot.reply_to(message, "❌ Usage: `/maintenance on` or `/maintenance off`", parse_mode='Markdown')


@bot.message_handler(commands=['genkey'])
def cmd_genkey(message):
    if not is_owner(message.from_user.id):
        return

    command = message.text.split()
    if len(command) < 3:
        apps_list = "\n".join([f"• `{a}`" for a in APP_IDS])
        bot.reply_to(message, f"""❌ Usage: `/genkey <days> <app_id> [slots]`

📱 **Apps:**
{apps_list}

**Example:**
`/genkey 30 com.ragebite.app 4`
""", parse_mode='Markdown')
        return

    try:
        days = int(command[1])
    except ValueError:
        bot.reply_to(message, "❌ Invalid days")
        return

    app_id = command[2]

    if app_id not in APP_IDS:
        bot.reply_to(message, f"❌ Unknown app_id. Available: {', '.join(APP_IDS)}")
        return

    try:
        slots = int(command[3]) if len(command) > 3 else 4
    except ValueError:
        slots = 4

    if days < 1 or days > 3650:
        bot.reply_to(message, "❌ Days 1-3650")
        return

    if slots < 1 or slots > 4:
        slots = 4

    key, expiry = generate_key(days, app_id, slots)

    bot.reply_to(message, f"""✅ **Key Generated**

🔑 Key: `{key}`
📱 App: `{app_id}`
📅 Expiry: {expiry}
⏱ Days: {days}
🎯 Slots: {slots}

**User ko ye key de do is app ke liye.**""", parse_mode='Markdown')


@bot.message_handler(commands=['listkeys'])
def cmd_listkeys(message):
    if not is_owner(message.from_user.id):
        return

    command = message.text.split()
    filter_app = command[1] if len(command) > 1 else None

    conn = get_conn()
    c = conn.cursor()

    if filter_app:
        c.execute('SELECT key, status, expiry, app_id FROM keys WHERE app_id = ? ORDER BY created_at DESC LIMIT 20', (filter_app,))
    else:
        c.execute('SELECT key, status, expiry, app_id FROM keys ORDER BY created_at DESC LIMIT 20')

    rows = c.fetchall()
    conn.close()

    if not rows:
        bot.reply_to(message, "ℹ️ No keys")
        return

    response = "🔑 **KEYS**\n\n"
    for k in rows:
        response += f"`{k[0]}`\n  {k[1]} | {k[2]} | `{k[3]}`\n\n"

    bot.reply_to(message, response, parse_mode='Markdown')


@bot.message_handler(commands=['delkey'])
def cmd_delkey(message):
    if not is_owner(message.from_user.id):
        return

    command = message.text.split()
    if len(command) != 2:
        bot.reply_to(message, "❌ Usage: `/delkey <key>`", parse_mode='Markdown')
        return

    key = command[1].upper()

    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE keys SET status = ? WHERE key = ?', (STATUS_DELETED, key))
    conn.commit()
    conn.close()

    bot.reply_to(message, f"✅ Key `{key}` deleted", parse_mode='Markdown')


@bot.message_handler(commands=['diskey'])
def cmd_diskey(message):
    if not is_owner(message.from_user.id):
        return

    command = message.text.split()
    if len(command) != 2:
        bot.reply_to(message, "❌ Usage: `/diskey <key>`", parse_mode='Markdown')
        return

    key = command[1].upper()

    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE keys SET status = ? WHERE key = ?', (STATUS_DISABLED, key))
    conn.commit()
    conn.close()

    bot.reply_to(message, f"⛔ Key `{key}` disabled", parse_mode='Markdown')


@bot.message_handler(commands=['enkey'])
def cmd_enkey(message):
    if not is_owner(message.from_user.id):
        return

    command = message.text.split()
    if len(command) != 2:
        bot.reply_to(message, "❌ Usage: `/enkey <key>`", parse_mode='Markdown')
        return

    key = command[1].upper()

    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE keys SET status = ? WHERE key = ?', (STATUS_ACTIVE, key))
    conn.commit()
    conn.close()

    bot.reply_to(message, f"✅ Key `{key}` enabled", parse_mode='Markdown')


@bot.message_handler(commands=['keyinfo'])
def cmd_keyinfo(message):
    if not is_owner(message.from_user.id):
        return

    command = message.text.split()
    if len(command) != 2:
        bot.reply_to(message, "❌ Usage: `/keyinfo <key>`", parse_mode='Markdown')
        return

    key = command[1].upper()

    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM keys WHERE key = ?', (key,))
    row = c.fetchone()
    conn.close()

    if not row:
        bot.reply_to(message, "❌ Not found")
        return

    bot.reply_to(message, f"""🔑 **KEY INFO**

Key: `{row[0]}`
Device: `{row[1] or 'Not bound'}`
Expiry: {row[2]}
Status: {row[3]}
Slots: {row[4]}
App: `{row[5]}`
""", parse_mode='Markdown')


@bot.message_handler(commands=['resetbind'])
def cmd_resetbind(message):
    if not is_owner(message.from_user.id):
        return

    command = message.text.split()
    if len(command) != 2:
        bot.reply_to(message, "❌ Usage: `/resetbind <key>`", parse_mode='Markdown')
        return

    key = command[1].upper()

    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE keys SET device_id = NULL WHERE key = ?', (key,))
    conn.commit()
    conn.close()

    bot.reply_to(message, f"🔄 Device reset for `{key}`", parse_mode='Markdown')


@bot.message_handler(commands=['cleankeys'])
def cmd_cleankeys(message):
    if not is_owner(message.from_user.id):
        return

    conn = get_conn()
    c = conn.cursor()
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute('SELECT COUNT(*) FROM keys WHERE expiry < ? AND status = ?', (now_str, STATUS_ACTIVE))
    count = c.fetchone()[0]
    c.execute('DELETE FROM keys WHERE expiry < ? AND status = ?', (now_str, STATUS_ACTIVE))
    conn.commit()
    conn.close()

    bot.reply_to(message, f"🧹 Cleaned {count} expired keys")


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Key Bot running!")

    def log_message(self, format, *args):
        pass


def start_health():
    try:
        server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
        server.serve_forever()
    except:
        pass


def main():
    init_db()
    threading.Thread(target=start_health, daemon=True).start()

    print("=" * 60)
    print("🔑 RAGEBITE KEY BOT (@KEY_SWARGBOT)")
    print("=" * 60)
    print(f"👑 Owner: {OWNER_ID}")
    print(f"📱 Apps: {len(APP_IDS)}")
    for a in APP_IDS:
        print(f"   • {a}")
    print(f"🔧 Maintenance: {get_maintenance().upper()}")
    print("=" * 60)
    print("✅ Key Bot running...")
    print("=" * 60)

    while True:
        try:
            bot.polling(non_stop=True, interval=1, timeout=10, long_polling_timeout=10)
        except Exception as e:
            print(f"⚠️ Error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
