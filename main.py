import os
import time
import re
import threading
import traceback
import json
import random
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ChallengeRequired, RateLimitError

from database import get_config, set_config, update_user_welcome, get_user_last_welcome, sqlite3, DB_NAME

app = FastAPI()
templates = Jinja2Templates(directory="templates")

SESSION_FILE = "ig_session.json"

class InstagramBot(threading.Thread):
    def __init__(self, proxy=""):
        super().__init__()
        self.daemon = True
        self.running = False
        self.cl = None
        self.proxy = proxy.strip()
        self.group_id = ""
        self.admins = []
        self.session_id = ""
        self.bad_target = None
        self.bad_word = None
        self.stop_spam = False
        self.processed_msgs = set()

    def stop(self):
        self.running = False

    def safe_send(self, text, thread_id, reply_to_id=None):
        try:
            time.sleep(random.uniform(1.5, 3.0))
            if reply_to_id:
                try:
                    self.cl.direct_send(text, thread_ids=[thread_id], reply_to_message=reply_to_id)
                except TypeError:
                    self.cl.direct_send(text, thread_ids=[thread_id], replied_to_message_id=reply_to_id)
            else:
                self.cl.direct_send(text, thread_ids=[thread_id])
        except Exception as e:
            print(f"[-] Message Send Failed: {e}")

    def keep_alive(self):
        while self.running:
            try:
                time.sleep(480) 
                if self.running and self.cl:
                    self.cl.get_timeline_feed()
                    print("[*] Keep-Alive Ping Sent")
            except Exception:
                pass

    def login_and_retry(self):
        while self.running:
            try:
                print("[*] Initializing Instagram Client (Anti-Ban Mode)...")
                self.cl = Client()
                
                # DEVICE SPOOFING
                self.cl.set_device({
                    "app_version": "269.0.0.18.75",
                    "android_version": 26,
                    "android_release": "8.0.0",
                    "dpi": "480dpi",
                    "resolution": "1080x1920",
                    "manufacturer": "OnePlus",
                    "device": "devitron",
                    "model": "6T Dev",
                    "cpu": "qcom",
                    "version_code": "314665256"
                })
                self.cl.set_user_agent("Instagram 269.0.0.18.75 Android (26/8.0.0; 480dpi; 1080x1920; OnePlus; 6T Dev; devitron; qcom; en_US; 314665256)")
                
                if self.proxy:
                    print(f"[*] Using Proxy: {self.proxy}")
                    self.cl.set_proxy(self.proxy)
                
                if os.path.exists(SESSION_FILE):
                    try:
                        self.cl.load_settings(SESSION_FILE)
                    except:
                        pass

                print("[*] Trying to login via session ID...")
                self.cl.login_by_sessionid(self.session_id)
                print(f"[+] Login Successful! Bot Username: @{self.cl.username}")
                self.cl.dump_settings(SESSION_FILE)
                set_config("is_running", True)
                return True
            except Exception as e:
                print(f"[-] Login Failed: {e}")
                if "login_required" in str(e).lower() or "invalid" in str(e).lower():
                    print("[!] Session ID is invalid or IP is blocked by Instagram.")
                    set_config("is_running", False)
                    self.running = False
                    return False
                else:
                    print("[*] Network/Proxy Error. Retrying in 60 seconds...")
                    time.sleep(60)
        return False

    def run(self):
        self.running = True
        self.group_id = get_config("group_id")
        self.admins = get_config("admins", [])
        self.session_id = get_config("session_id")
        
        if not self.login_and_retry():
            return

        threading.Thread(target=self.keep_alive, daemon=True).start()
        print("[*] Bot Engine Started. Monitoring Group...")

        while self.running:
            try:
                if not get_config("is_running", False):
                    self.running = False
                    break

                messages = self.cl.direct_messages(self.group_id, amount=10)
                
                for msg in reversed(messages):
                    if msg.id in self.processed_msgs:
                        continue
                    self.processed_msgs.add(msg.id)
                    if len(self.processed_msgs) > 100:
                        self.processed_msgs.pop()

                    if msg.user_id == self.cl.user_id:
                        continue 

                    try:
                        username = self.cl.user_info(msg.user_id).username
                    except Exception:
                        username = "Unknown"
                        
                    text = msg.text.strip() if msg.text else ""
                    user_id = str(msg.user_id)
                    
                    if f"@{self.cl.username}" in text:
                        text = text.replace(f"@{self.cl.username}", "").strip()

                    action_log = getattr(msg, 'action_log', None)
                    if msg.item_type == "action_log" and action_log and getattr(action_log, 'action_type', '') == "add_user":
                        users = getattr(action_log, 'users', [])
                        for added_user in users:
                            self.safe_send(f"welcome to our gc @{added_user.username}", self.group_id)
                        continue 

                    if username in self.admins:
                        if text == "/stop":
                            self.bad_target = None
                            self.bad_word = None
                            self.stop_spam = True
                            self.safe_send("Stopped all actions.", self.group_id, reply_to_id=msg.id)
                            continue

                        if text.startswith("/spam "):
                            spam_text = text[6:]
                            self.stop_spam = False
                            self.safe_send(f"Spamming 15 times...", self.group_id)
                            for _ in range(15):
                                if not self.running or self.stop_spam: break
                                self.safe_send(spam_text, self.group_id)
                            continue
                            
                        elif text.startswith("/song "):
                            song_name = text[6:]
                            self.safe_send(f"🎵 Searching for '{song_name}'...", self.group_id, reply_to_id=msg.id)
                            time.sleep(1)
                            self.safe_send(f"https://open.spotify.com/search/{song_name.replace(' ', '%20')}", self.group_id)
                            continue

                        elif text.startswith("/bad @"):
                            parts = text.split(" ")
                            if len(parts) >= 3:
                                target = parts[1].replace("@", "")
                                word = " ".join(parts[2:])
                                self.bad_target = target
                                self.bad_word = word
                                self.safe_send(f"Target set: @{target} -> '{word}'", self.group_id, reply_to_id=msg.id)
                            continue

                        elif text == "/menu":
                            menu_text = "🤖 BOT MENU 🤖\n/spam [msg]\n/song [name]\n/bad @user [word]\n/stop\n/total\n/menu"
                            self.safe_send(menu_text, self.group_id, reply_to_id=msg.id)
                            continue

                        elif text == "/total":
                            conn = sqlite3.connect(DB_NAME)
                            c = conn.cursor()
                            today = datetime.now().strftime("%Y-%m-%d")
                            c.execute("SELECT total_msgs, active_users, joined_users FROM stats WHERE date=?", (today,))
                            row = c.fetchone()
                            conn.close()
                            stats_text = f"📊 TODAY'S STATS 📊\nTotal Msgs: {row[0] if row else 0}\nActive Users: {len(json.loads(row[1])) if row else 0}\nJoined: {len(json.loads(row[2])) if row else 0}"
                            self.safe_send(stats_text, self.group_id, reply_to_id=msg.id)
                            continue

                    if self.bad_target and self.bad_target in text:
                        self.safe_send(f"@{self.bad_target} {self.bad_word}", self.group_id, reply_to_id=msg.id)
                        continue

                    if re.search(r'i\s*g\s*n\s*o\s*r\s*e', text, re.IGNORECASE):
                        self.safe_send("Are babu ignore ho gye koi nah mein hu na 💖", self.group_id, reply_to_id=msg.id)
                        continue

                    if re.search(r'https:\/\/ig\.me\/', text):
                        self.safe_send("PROMOTION KARNE WALE KE 12 B44P", self.group_id, reply_to_id=msg.id)
                        continue

                    last_welcome = get_user_last_welcome(user_id)
                    now = datetime.now()
                    if not last_welcome or (now - last_welcome).total_seconds() > 12 * 3600:
                        welcome_msg = f"Welcome back to our gc @{username} how are you? 🎈"
                        self.safe_send(welcome_msg, self.group_id, reply_to_id=msg.id)
                        update_user_welcome(user_id, username)

                time.sleep(random.uniform(3.0, 6.0)) 

            except LoginRequired:
                print("[!] Session expired during loop. Trying to relogin...")
                if not self.login_and_retry():
                    break
            except RateLimitError:
                print("[!] Rate limited... Sleep 120s")
                time.sleep(120)
            except ChallengeRequired:
                print("[!] Account challenged! Session invalid. Stopping bot.")
                self.running = False
                set_config("is_running", False)
            except Exception as e:
                print(f"[!] Loop Error: {e}")
                time.sleep(10)

        print("[!] Bot Engine Stopped.")

bot_instance = None

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    is_running = get_config("is_running", False)
    return templates.TemplateResponse(request=request, name="index.html", context={"running": is_running})

@app.post("/start")
async def start_bot(request: Request, session_id: str = Form(...), group_id: str = Form(...), admins: str = Form(...), proxy: str = Form("")):
    global bot_instance
    if get_config("is_running", False):
        return RedirectResponse(url="/", status_code=303)

    admin_list = [a.strip().replace("@", "") for a in admins.split(",") if a.strip()][:5]
    set_config("session_id", session_id.strip())
    set_config("group_id", group_id.strip())
    set_config("admins", admin_list)
    set_config("is_running", True)
    
    bot_instance = InstagramBot(proxy=proxy)
    bot_instance.start()
    return RedirectResponse(url="/", status_code=303)

@app.post("/stop")
async def stop_bot():
    global bot_instance
    set_config("is_running", False) 
    if bot_instance:
        bot_instance.stop()
    return RedirectResponse(url="/", status_code=303)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)