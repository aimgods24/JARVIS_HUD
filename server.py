from flask import Flask, render_template_string, request, jsonify, send_file
import edge_tts
import asyncio
import os
import re
import random
import subprocess
import threading
import time
from duckduckgo_search import DDGS

# Desktop Automation fallbacks for local running
try:
    import pyautogui
    HAS_PYAUTOGUI = True
except Exception:
    HAS_PYAUTOGUI = False

# Local Ollama fallback
try:
    import ollama
    HAS_OLLAMA = True
except Exception:
    HAS_OLLAMA = False

app = Flask(__name__)

with open('index.html', 'r', encoding='utf-8') as f:
    HTML_TEMPLATE = f.read()

MEMORY_FILE = "jarvis_memory.txt"
GLOBAL_NEWS_CACHE = []

def fetch_latest_global_news():
    global GLOBAL_NEWS_CACHE
    while True:
        try:
            results = list(DDGS().text("breaking world global news headlines today", max_results=8))
            if results:
                GLOBAL_NEWS_CACHE = [f"📰 [{res['title']}] - {res['body']}" for res in results]
        except Exception as e:
            print(f"[NEWS ENGINE ERROR]: {str(e)}")
        time.sleep(3600)

news_thread = threading.Thread(target=fetch_latest_global_news, daemon=True)
news_thread.start()

def get_user_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
            return f.read()
    return ""

def update_user_memory(new_info):
    with open(MEMORY_FILE, 'a', encoding='utf-8') as f:
        f.write(f"\n{new_info}")

WELCOME_MESSAGES = [
    "Welcome back, {honorific}. All neural pathways and subroutines are online.",
    "Authentication confirmed. Good to see you again, {honorific}.",
    "Systems restored to maximum efficiency. How may I assist you today, {honorific}?"
]

def search_general_knowledge(query):
    try:
        results = list(DDGS().text(query, max_results=3))
        if results:
            snippets = [res['body'] for res in results if 'body' in res]
            summary = " ".join(snippets[:2])
            return summary[:400] + "..." if len(summary) > 400 else summary
        return None
    except Exception:
        return None

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/manifest.json')
def manifest():
    return send_file('manifest.json')

@app.route('/sw.js')
def service_worker():
    return send_file('sw.js')

@app.route('/api/ask', methods=['POST'])
def ask():
    data = request.json or {}
    user_prompt = data.get('prompt', '').strip()
    images = data.get('images', [])
    honorific = data.get('honorific', 'Sir')
    voice_char = data.get('voice_char', 'jarvis')
    location = data.get('location', 'Bayan Lepas, Penang, Malaysia')
    battery_info = data.get('battery', 'Battery Normal')
    is_dnd = data.get('dnd_mode', False)

    if not user_prompt and not images:
        return jsonify({'response': f'No command received, {honorific}.', 'audio': False})

    cmd_lower = user_prompt.lower()
    reply = None
    media_action = None
    nav_destination = None
    c3po_nav_text = None
    app_launch_intent = None

    # 1. App Launching Engine (Mobile Deep Links & Desktop Subprocess)
    if "open" in cmd_lower or "launch" in cmd_lower:
        target_app = cmd_lower.replace("open", "").replace("launch", "").strip()
        
        # Scheme mapping for Mobile browsers (Android / iOS URIs)
        app_schemes = {
            "spotify": "spotify://",
            "youtube": "https://www.youtube.com",
            "maps": "https://maps.google.com",
            "google maps": "https://maps.google.com",
            "chrome": "googlechrome://",
            "whatsapp": "whatsapp://"
        }
        
        if target_app in app_schemes:
            app_launch_intent = app_schemes[target_app]
            reply = f"Opening {target_app} on your device, {honorific}."
            
            # Desktop subprocess fallback if running on PC
            if HAS_PYAUTOGUI:
                try:
                    subprocess.Popen(f"start {target_app}", shell=True)
                except Exception:
                    pass

    # 2. Navigation & Dynamic Routing
    elif "navigate" in cmd_lower or "direction" in cmd_lower or "map to" in cmd_lower:
        dest_match = re.sub(r'get directions to|directions to|navigate to|map to|take me to', '', user_prompt, flags=re.IGNORECASE).strip()
        nav_destination = dest_match if dest_match else "Target Destination"
        c3po_nav_text = f"Oh my! Computing high-precision GPS route to {nav_destination}, Master!"
        reply = f"Tracking live coordinates. Navigating to {nav_destination}, {honorific}."

    # 3. Global News
    elif "news" in cmd_lower or "headlines" in cmd_lower:
        if GLOBAL_NEWS_CACHE:
            reply = f"Latest global news headlines:\n\n" + "\n\n".join(GLOBAL_NEWS_CACHE[:4])

    # 4. Universal ChatGPT-Style General Q&A Fallback
    if not reply:
        if HAS_OLLAMA:
            try:
                model_to_use = 'moondream' if images else 'qwen2.5:0.5b'
                response = ollama.chat(
                    model=model_to_use,
                    messages=[{"role": "system", "content": f"You are J.A.R.V.I.S. Address user as {honorific}."}, {"role": "user", "content": user_prompt}],
                    options={"num_predict": 100}
                )
                reply = response['message']['content'].strip()
            except Exception:
                reply = None

        if not reply:
            reply = search_general_knowledge(user_prompt) or f"Command processed, {honorific}."

    clean_text = re.sub(r'[*_~`]', '', reply)
    if not clean_text.endswith(honorific) and not c3po_nav_text:
        clean_text += f", {honorific}."

    has_audio = False
    if not is_dnd:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(generate_voice(clean_text, voice_char))
            loop.close()
            has_audio = True
        except Exception:
            has_audio = False

    return jsonify({
        'response': reply,
        'audio': has_audio,
        'app_intent': app_launch_intent,
        'nav_destination': nav_destination,
        'c3po_text': c3po_nav_text
    })

async def generate_voice(text, voice_char):
    communicate = edge_tts.Communicate(text, 'en-GB-RyanNeural', pitch="-2Hz", rate="+5%")
    await communicate.save("static_speech.mp3")

@app.route('/api/audio')
def get_audio():
    return send_file('static_speech.mp3', mimetype='audio/mpeg')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)