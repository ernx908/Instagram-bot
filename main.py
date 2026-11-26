import os
import time
import re
import threading
import traceback
import json
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ChallengeRequired, RateLimitError

# Database imports
from database import get_config, set_config, update_user_welcome, get_user_last_welcome, sqlite3, DB_NAME

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# ==========================================
# BOT ENGINE CLASS
# ==========================================
class InstagramBot(threading.Thread):
    def __init__(self):
        super().__init__()
        self.daemon = True
        self.running = False
        self.cl = None
        self.group_id = ""
        self.admins = []
        self.session_id = ""
        
        # Bad word system state
        self.bad_target = None
        self.bad_word = None

    def stop(self):
        self.running = False
        print("[!] Bot Stop Requested...")

    def safe_send(self, text, thread_id):
        """Safer message sending with auto-retry"""
        try:
            self.cl.direct_send(text, thread_ids=[thread_id])
            time.sleep(2.0) # Hard sleep to avoid spamming IG servers
        except Exception as e:
            print(f"[-] Message Send Failed: {e}")

    def run(self):
        self.running = True
        self.group_id = get_config("group_id")
        self.admins = get_config("admins", [])
        
        # Load credentials from DB
        self.session_id = get_config("session_id")
        
        print("[*] Initializing Instagram Client...")
        self.cl = Client()
        
        # Login Logic with Error Handling
        try:
            self.cl.login_by_sessionid(self.session_id)
            print("[+] Login Successful!")
            set_config("is_running", True)
        except Exception as e:
            print(f"[-] Login Failed (Invalid Session): {e}")
            set_config("is_running", False)
            self.running = False
            return

        last_check_time = datetime.now()
        print("[*] Bot Engine Started. Monitoring Group...")

        while self.running:
            try:
                # Check if user requested stop via Web UI
                if not get_config("is_running", False):
                    self.running = False
                    break

                # Fetch messages
                messages = self.cl.direct_messages(self.group_id, amount=15)
                
                for msg in reversed(messages):
                    # Skip messages sent before bot started (to prevent double replies)
                    msg_time = msg.timestamp
                    if msg_time < last_check_time - timedelta(minutes=1):
                        continue
                        
                    if msg.user_id == self.cl.user_id:
                        continue # Skip own messages

                    text = msg.text.strip() if msg.text else ""
                    username = msg.user.username
                    user_id = str(msg.user_id)
                    
                    # 1. NEW MEMBER JOIN HANDLER
                    if msg.item_type == "action_log" and msg.action_log and msg.action_log.action_type == "add_user":
                        for added_user in msg.action_log.users:
                            welcome = f"welcome to our gc @{added_user.username}"
                            self.safe_send(welcome, self.group_id)
                        continue 

                    # 2. ADMIN COMMANDS
                    if username in self.admins:
                        if text.startswith("/spam "):
                            spam_text = text[6:]
                            self.safe_send(f"Spamming 15 times...", self.group_id)
                            for _ in range(15):
                                if not self.running: break
                                self.safe_send(spam_text, self.group_id)
                            continue
                            
                        elif text.startswith("/song "):
                            song_name = text[6:]
                            self.safe_send(f"🎵 Searching for '{song_name}' on Spotify...", self.group_id)
                            time.sleep(1)
                            link = f"https://open.spotify.com/search/{song_name.replace(' ', '%20')}"
                            self.safe_send(f"Result: {link}", self.group_id)
                            continue

                        elif text.startswith("/bad @"):
                            parts = text.split(" ")
                            if len(parts) >= 3:
                                target = parts[1].replace("@", "")
                                word = " ".join(parts[2:])
                                self.bad_target = target
                                self.bad_word = word
                                self.safe_send(f"Target set: @{target} -> '{word}'", self.group_id)
                            continue

                        elif text == "/stop":
                            self.bad_target = None
                            self.bad_word = None
                            self.safe_send("Stopped bad word spam.", self.group_id)
                            continue

                        elif text == "/menu":
                            menu_text = (
                                "🤖 BOT MENU 🤖\n"
                                "/spam [msg]\n/song [name]\n"
                                "/bad @user [word]\n/stop\n"
                                "/total\n/menu"
                            )
                            self.safe_send(menu_text, self.group_id)
                            continue

                        elif text == "/total":
                            conn = sqlite3.connect(DB_NAME)
                            c = conn.cursor()
                            today = datetime.now().strftime("%Y-%m-%d")
                            c.execute("SELECT total_msgs, active_users, joined_users FROM stats WHERE date=?", (today,))
                            row = c.fetchone()
                            conn.close()
                            
                            if row:
                                stats_text = f"📊 TODAY'S STATS 📊\nTotal Msgs: {row[0]}\nActive Users: {len(json.loads(row[1]))}\nJoined: {len(json.loads(row[2]))}"
                            else:
                                stats_text = "📊 No stats recorded for today yet."
                            self.safe_send(stats_text, self.group_id)
                            continue

                    # 3. BAD WORD SYSTEM
                    if self.bad_target and self.bad_target in text:
                        self.safe_send(f"@{self.bad_target} {self.bad_word}", self.group_id)
                        continue

                    # 4. 12-HOUR WELCOME BACK SYSTEM
                    last_welcome = get_user_last_welcome(user_id)
                    now = datetime.now()
                    
                    if not last_welcome or (now - last_welcome).total_seconds() > 12 * 3600:
                        welcome_msg = f"Welcome back to our gc @{username} how are you? 🎈"
                        self.safe_send(welcome_msg, self.group_id)
                        update_user_welcome(user_id, username)

                # Sleep before checking again
                time.sleep(4)

            except RateLimitError:
                print("[!] Rate limited by Instagram. Sleeping for 60s...")
                time.sleep(60)
            except ChallengeRequired:
                print("[!] Account challenged! Session invalid. Stopping bot.")
                self.running = False
                set_config("is_running", False)
            except Exception as e:
                print(f"[!] Loop Error: {e}")
                time.sleep(5)

        print("[!] Bot Engine Stopped.")

# Global Instance
bot_instance = None

# ==========================================
# WEB ROUTES
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    is_running = get_config("is_running", False)
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "running": is_running
    })

@app.post("/start")
async def start_bot(request: Request, session_id: str = Form(...), group_id: str = Form(...), admins: str = Form(...)):
    global bot_instance
    
    if get_config("is_running", False):
        return RedirectResponse(url="/", status_code=303)

    # Parse admins (max 3)
    admin_list = [a.strip().replace("@", "") for a in admins.split(",") if a.strip()][:3]
    
    # Save to DB
    set_config("session_id", session_id.strip())
    set_config("group_id", group_id.strip())
    set_config("admins", admin_list)
    set_config("is_running", True)
    
    # Start Thread
    bot_instance = InstagramBot()
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