"""
⚡ RAGEBITE VPS BACKEND - Flask API + Maintenance
"""

import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests

# ============================================================
# CONFIG
# ============================================================
DD_BOT_TOKEN = "8650600804:AAFw-AuiLMtbUUHIbqwdPzVeOG8s11yfdA8"
OWNER_ID = 6321758394

API_SECRET = "RAGEBITE_SECRET_2026_CHANGE_ME"
API_PORT = 5000

APP_IDS = [
    "com.ragebite.app",
]
SLOTS_PER_APP = 4

DB_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ragebite.db')

STATUS_ACTIVE = "ACTIVE"
STATUS_EXPIRED = "EXPIRED"
STATUS_DELETED = "DELETED"
STATUS_DISABLED = "DISABLED"

rate_limit_store = {}
db_write_lock = threading.RLock()


def get_conn():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
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

    c.execute('''CREATE TABLE IF NOT EXISTS slots (
        slot_id INTEGER,
        app_id TEXT,
        device_id TEXT,
        key TEXT,
        package_name TEXT,
        ip TEXT,
        port TEXT,
        time_sec INTEGER,
        start_time TEXT,
        end_time TEXT,
        is_active INTEGER DEFAULT 0,
        PRIMARY KEY (app_id, slot_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('maintenance', 'off')")

    for app_id in APP_IDS:
        for i in range(1, SLOTS_PER_APP + 1):
            c.execute('INSERT OR IGNORE INTO slots (app_id, slot_id, is_active) VALUES (?, ?, 0)', (app_id, i))

    conn.commit()
    conn.close()
    print(f"✅ Database ready: {DB_NAME}")


def get_maintenance():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key='maintenance'")
    row = c.fetchone()
    conn.close()
    return row[0] if row else "off"


def verify_key_with_device(key, device_id):
    with db_write_lock:
        conn = get_conn()
        try:
            c = conn.cursor()
            c.execute('SELECT expiry, status, device_id FROM keys WHERE key = ?', (key,))
            row = c.fetchone()
            if not row:
                return None, "NOT_FOUND", False
            expiry_str, status, existing_device = row
            if status == STATUS_DELETED:
                return None, "DELETED", False
            if status == STATUS_DISABLED:
                return None, "DISABLED", False
            expiry = datetime.strptime(expiry_str, '%Y-%m-%d %H:%M:%S')
            if expiry < datetime.now():
                c.execute('UPDATE keys SET status = ? WHERE key = ?', (STATUS_EXPIRED, key))
                conn.commit()
                return None, "EXPIRED", False
            if existing_device is None:
                c.execute('UPDATE keys SET device_id = ? WHERE key = ?', (device_id, key))
                conn.commit()
                print(f"🔗 Device bound: {key[:15]}...")
                return int(expiry.timestamp() * 1000), "VALID", True
            elif existing_device == device_id:
                return int(expiry.timestamp() * 1000), "VALID", True
            else:
                return None, "DEVICE_MISMATCH", False
        finally:
            conn.close()


def is_device_authorized(device_id):
    with db_write_lock:
        conn = get_conn()
        try:
            c = conn.cursor()
            c.execute('''SELECT key, expiry, status FROM keys 
                         WHERE device_id = ? ORDER BY created_at DESC LIMIT 1''', (device_id,))
            row = c.fetchone()
            if not row:
                return False, None, "NO_KEY"
            key, expiry_str, status = row
            if status == STATUS_DELETED:
                return False, key, "DELETED"
            if status == STATUS_DISABLED:
                return False, key, "DISABLED"
            expiry = datetime.strptime(expiry_str, '%Y-%m-%d %H:%M:%S')
            if expiry < datetime.now():
                c.execute('UPDATE keys SET status = ? WHERE key = ?', (STATUS_EXPIRED, key))
                conn.commit()
                return False, key, "EXPIRED"
            return True, key, "VALID"
        finally:
            conn.close()


def allot_slot(app_id, device_id, key, package_name, ip, port, time_sec):
    with db_write_lock:
        conn = get_conn()
        try:
            c = conn.cursor()
            c.execute('SELECT slot_count FROM keys WHERE key = ?', (key,))
            row = c.fetchone()
            key_slot_count = row[0] if row else 4
            c.execute('SELECT COUNT(*) FROM slots WHERE key = ? AND is_active = 1', (key,))
            used_slots = c.fetchone()[0]
            if used_slots >= key_slot_count:
                return None, "KEY_SLOTS_FULL"
            c.execute('SELECT slot_id FROM slots WHERE app_id=? AND device_id=? AND is_active=1', (app_id, device_id))
            if c.fetchone():
                return None, "ALREADY_ACTIVE"
            c.execute('''SELECT slot_id FROM slots 
                         WHERE app_id=? AND is_active=0 AND slot_id <= ? 
                         ORDER BY slot_id ASC LIMIT 1''', (app_id, SLOTS_PER_APP))
            slot_row = c.fetchone()
            if slot_row is None:
                return None, "ALL_SLOTS_FULL"
            slot_id = slot_row[0]
            start = datetime.now()
            end = start + timedelta(seconds=time_sec)
            c.execute('''UPDATE slots SET device_id=?, key=?, package_name=?, 
                         ip=?, port=?, time_sec=?, start_time=?, end_time=?, is_active=1 
                         WHERE app_id=? AND slot_id=?''',
                      (device_id, key, package_name, ip, port, time_sec,
                       start.strftime('%Y-%m-%d %H:%M:%S'),
                       end.strftime('%Y-%m-%d %H:%M:%S'),
                       app_id, slot_id))
            conn.commit()
            return slot_id, "OK"
        finally:
            conn.close()


def release_slot(app_id, slot_id):
    with db_write_lock:
        conn = get_conn()
        try:
            c = conn.cursor()
            c.execute('''UPDATE slots SET device_id=NULL, key=NULL, package_name=NULL,
                         ip=NULL, port=NULL, time_sec=NULL, start_time=NULL,
                         end_time=NULL, is_active=0 WHERE app_id=? AND slot_id=?''',
                      (app_id, slot_id))
            conn.commit()
        finally:
            conn.close()


def get_app_slots(app_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute('SELECT * FROM slots WHERE app_id=? ORDER BY slot_id', (app_id,))
        return c.fetchall()
    finally:
        conn.close()


def get_expired_slots():
    conn = get_conn()
    try:
        c = conn.cursor()
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute('SELECT app_id, slot_id FROM slots WHERE is_active=1 AND end_time <= ?', (now_str,))
        return c.fetchall()
    finally:
        conn.close()


def check_rate_limit(identifier, max_requests=15, window=60):
    now_ts = time.time()
    if identifier not in rate_limit_store:
        rate_limit_store[identifier] = []
    rate_limit_store[identifier] = [t for t in rate_limit_store[identifier] if now_ts - t < window]
    if len(rate_limit_store[identifier]) >= max_requests:
        return False
    rate_limit_store[identifier].append(now_ts)
    return True


def notify_owner_dd(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{DD_BOT_TOKEN}/sendMessage",
            json={"chat_id": OWNER_ID, "text": text},
            timeout=5)
    except Exception as e:
        print(f"DM error: {e}")


app = Flask(__name__)
CORS(app)


def check_auth():
    return request.headers.get('X-API-KEY') == API_SECRET


@app.route('/api/health', methods=['GET'])
def api_health():
    return jsonify({"status": "OK", "apps": APP_IDS, "slots_per_app": SLOTS_PER_APP})


@app.route('/api/verify', methods=['POST'])
def api_verify():
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json or {}
    key = data.get('key', '').upper().strip()
    device_id = data.get('device_id', '').strip()

    if not device_id:
        return jsonify({"status": "INVALID", "reason": "NoDeviceID"})
    if not key:
        return jsonify({"status": "INVALID", "reason": "NoKey"})

    expiry, status, _ = verify_key_with_device(key, device_id)
    if status == "VALID":
        return jsonify({"status": "VALID", "expiry": expiry})
    return jsonify({"status": "INVALID", "reason": status})


@app.route('/api/slots/status/<app_id>', methods=['GET'])
def api_slots_status(app_id):
    if app_id not in APP_IDS:
        return jsonify({"error": "Unknown app_id", "valid_apps": APP_IDS}), 404

    rows = get_app_slots(app_id)
    slots = []
    for r in rows:
        if r[10]:
            try:
                rem = int((datetime.strptime(r[9], '%Y-%m-%d %H:%M:%S') - datetime.now()).total_seconds())
            except:
                rem = 0
            slots.append({"slot": r[0], "status": "BUSY", "remaining": max(0, rem)})
        else:
            slots.append({"slot": r[0], "status": "FREE", "remaining": 0})

    active = sum(1 for s in slots if s["status"] == "BUSY")
    return jsonify({"app_id": app_id, "slots": slots, "active": active, "max": SLOTS_PER_APP})


@app.route('/api/slots/status', methods=['GET'])
def api_all_slots():
    result = {}
    for app_id in APP_IDS:
        rows = get_app_slots(app_id)
        slots = []
        for r in rows:
            if r[10]:
                try:
                    rem = int((datetime.strptime(r[9], '%Y-%m-%d %H:%M:%S') - datetime.now()).total_seconds())
                except:
                    rem = 0
                slots.append({"slot": r[0], "status": "BUSY", "remaining": max(0, rem)})
            else:
                slots.append({"slot": r[0], "status": "FREE", "remaining": 0})
        active = sum(1 for s in slots if s["status"] == "BUSY")
        result[app_id] = {"slots": slots, "active": active, "max": SLOTS_PER_APP}
    return jsonify(result)


@app.route('/api/dd', methods=['POST'])
def api_dd():
    if not check_auth():
        return jsonify({"status": "ERROR", "reason": "Unauthorized"}), 401

    # ✅ MAINTENANCE CHECK
    if get_maintenance() == "on":
        return jsonify({
            "status": "ERROR",
            "reason": "MAINTENANCE",
            "message": "Bot maintenance pe hai. Thodi der baad try karo."
        })

    client_ip = request.remote_addr
    if not check_rate_limit(client_ip, max_requests=15, window=60):
        return jsonify({"status": "ERROR", "reason": "RateLimit"})

    data = request.json or {}
    device_id = data.get('device_id', '').strip()
    key = data.get('key', '').upper().strip()
    ip = data.get('ip', '').strip()
    port = str(data.get('port', '')).strip()
    time_sec = int(data.get('time', 0))
    pkg = data.get('package', APP_IDS[0])

    if not device_id:
        return jsonify({"status": "ERROR", "reason": "NoDeviceID"})
    if not key:
        return jsonify({"status": "ERROR", "reason": "NoKey"})
    if not ip or not port:
        return jsonify({"status": "ERROR", "reason": "MissingIPPort"})
    if time_sec < 10 or time_sec > 300:
        return jsonify({"status": "ERROR", "reason": "InvalidTime"})

    if pkg not in APP_IDS:
        return jsonify({"status": "ERROR", "reason": "UnknownApp", "valid": APP_IDS})

    expiry, status, _ = verify_key_with_device(key, device_id)
    if status != "VALID":
        return jsonify({"status": "ERROR", "reason": status})

    authorized, user_key, reason = is_device_authorized(device_id)
    if not authorized:
        return jsonify({"status": "ERROR", "reason": reason})

    slot_id, slot_status = allot_slot(pkg, device_id, key, pkg, ip, port, time_sec)

    if slot_status == "ALREADY_ACTIVE":
        return jsonify({"status": "ERROR", "reason": "AlreadyActive",
                        "message": "Aapka ek attack already chal raha hai"})

    if slot_status == "KEY_SLOTS_FULL":
        return jsonify({"status": "ERROR", "reason": "KeySlotsFull",
                        "message": "Aapki key ke saare slots busy hain"})

    if slot_id is None:
        return jsonify({"status": "ERROR", "reason": "SlotsFull",
                        "message": f"App {pkg} ke saare slots busy hain"})

    notify_owner_dd(f"/bgmi {ip} {port} {time_sec} {pkg}")
    print(f"📤 DM sent: /bgmi {ip} {port} {time_sec} {pkg}")

    end = datetime.now() + timedelta(seconds=time_sec)
    return jsonify({
        "status": "SLOT_ALLOTTED",
        "app_id": pkg,
        "slot": slot_id,
        "ip": ip,
        "port": port,
        "time": time_sec,
        "end_time": end.strftime('%H:%M:%S')
    })


def auto_release_loop():
    while True:
        try:
            for app_id, slot_id in get_expired_slots():
                release_slot(app_id, slot_id)
                print(f"✅ Released {app_id} slot #{slot_id}")
        except Exception as e:
            print(f"Auto-release: {e}")
        time.sleep(5)


def main():
    init_db()

    print("=" * 60)
    print("🛡️ RAGEBITE VPS BACKEND")
    print("=" * 60)
    print(f"📱 Apps: {len(APP_IDS)}")
    for app_id in APP_IDS:
        print(f"   • {app_id} — {SLOTS_PER_APP} slots")
    print(f"📊 Total Slots: {len(APP_IDS) * SLOTS_PER_APP}")
    print(f"🌐 API Port: {API_PORT}")
    print(f"🔧 Maintenance: {get_maintenance().upper()}")
    print("=" * 60)
    print("✅ Server running...")
    print("=" * 60)

    threading.Thread(target=auto_release_loop, daemon=True).start()

    app.run(host='0.0.0.0', port=API_PORT, debug=False, use_reloader=False, threaded=True)


if __name__ == '__main__':
    main()
