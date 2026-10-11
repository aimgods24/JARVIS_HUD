from flask import Flask, render_template_string, request, jsonify, send_file
import edge_tts
import asyncio
import os
import re
import random
import subprocess
import threading
import time
import base64
from duckduckgo_search import DDGS

# Cloud Compatibility Guard (Render)
try:
    import pyautogui
    HAS_PYAUTOGUI = True
except Exception:
    HAS_PYAUTOGUI = False

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
            results = list(DDGS().text("breaking world global news headlines today", max_results=5))
            if results:
                GLOBAL_NEWS_CACHE = [f"📰 [{res.get('title', 'News')}] - {res.get('body', '')}" for res in results]
        except Exception as e:
            print(f"[NEWS ENGINE NOTICE]: {str(e)}")
        time.sleep(3600)

news_thread = threading.Thread(target=fetch_latest_global_news, daemon=True)
news_thread.start()

def get_user_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            return ""
    return ""

def update_user_memory(new_info):
    try:
        with open(MEMORY_FILE, 'a', encoding='utf-8') as f:
            f.write(f"\n{new_info}")
    except Exception:
        pass

WELCOME_MESSAGES = [
    "Welcome back, {honorific}. All neural pathways and subroutines are online.",
    "Authentication confirmed. Good to see you again, {honorific}.",
    "Systems restored to maximum efficiency. How may I assist you today, {honorific}?"
]

def search_general_knowledge(query):
    """Fail-safe ChatGPT-style web answering fallback engine"""
    try:
        results = list(DDGS().text(query, max_results=3))
        if results:
            snippets = [res['body'] for res in results if 'body' in res]
            summary = " ".join(snippets[:2])
            return summary[:500] + "..." if len(summary) > 500 else summary
        return None
    except Exception as e:
        print(f"[SEARCH ENGINE NOTICE]: {str(e)}")
        return None

def generate_voice_b64(text, voice_char):
    """Generate TTS audio and return as Base64 data string to eliminate cloud file locks"""
    try:
        voice_map = {
            'jarvis': 'en-GB-RyanNeural',
            'friday': 'en-IE-EmilyNeural',
            'cyber': 'en-US-ChristopherNeural'
        }
        selected_voice = voice_map.get(voice_char, 'en-GB-RyanNeural')
        communicate = edge_tts.Communicate(text, selected_voice, pitch="-2Hz", rate="+5%")
        
        tmp_filename = f"speech_{random.randint(1000,9999)}.mp3"
        asyncio.run(communicate.save(tmp_filename))
        
        with open(tmp_filename, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode('utf-8')
            
        if os.path.exists(tmp_filename):
            os.remove(tmp_filename)
            
        return f"data:audio/mp3;base64,{b64_data}"
    except Exception as e:
        print(f"[TTS ENGINE ERROR]: {str(e)}")
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

@app.route('/api/get_news', methods=['GET'])
def get_news():
    if GLOBAL_NEWS_CACHE:
        return jsonify({'status': 'success', 'news': GLOBAL_NEWS_CACHE})
    else:
        return jsonify({'status': 'success', 'news': ["📰 Real-time news feed is updating in background."]})

@app.route('/api/ask', methods=['POST'])
def ask():
    try:
        data = request.json or {}
        user_prompt = data.get('prompt', '').strip()
        honorific = data.get('honorific', 'Sir')
        voice_char = data.get('voice_char', 'jarvis')
        location = data.get('location', 'Bayan Lepas, Penang, Malaysia')
        device_type = data.get('device_type', 'desktop')

        if not user_prompt:
            return jsonify({'response': f'No command received, {honorific}.', 'audio_b64': None})

        cmd_lower = user_prompt.lower()
        reply = None
        trigger_blackout = False
        app_launch_intent = None

        # 1. Global News
        if "news" in cmd_lower or "headlines" in cmd_lower:
            if GLOBAL_NEWS_CACHE:
                reply = f"Here are the latest global news headlines:\n\n" + "\n\n".join(GLOBAL_NEWS_CACHE[:4])
            else:
                reply = f"Fetching real-time global news feed now, {honorific}."

        # 2. Blackout Override
        elif "blackout" in cmd_lower or "black out" in cmd_lower:
            trigger_blackout = True
            reply = f"Engaging HUD blackout mode. Communication terminal active, {honorific}."

        # 3. Mobile / Desktop App Launching
        elif "open" in cmd_lower or "launch" in cmd_lower:
            target_app = cmd_lower.replace("open", "").replace("launch", "").strip()
            app_schemes = {
                "spotify": "spotify://",
                "youtube": "https://www.youtube.com",
                "maps": "https://maps.google.com",
                "chrome": "googlechrome://"
            }
            if device_type == "mobile" and target_app in app_schemes:
                app_launch_intent = app_schemes[target_app]
                reply = f"Opening {target_app} on mobile interface, {honorific}."
            else:
                reply = f"Initiating execution routine for {target_app}, {honorific}."

        # 4. Universal ChatGPT-Style AI Reasoning Core
        if not reply:
            if HAS_OLLAMA:
                try:
                    response = ollama.chat(
                        model='qwen2.5:0.5b',
                        messages=[{"role": "system", "content": f"You are J.A.R.V.I.S. Address user as {honorific}."}, {"role": "user", "content": user_prompt}],
                        options={"num_predict": 100}
                    )
                    reply = response['message']['content'].strip()
                except Exception:
                    reply = None

            if not reply:
                reply = search_general_knowledge(user_prompt)
                
            if not reply:
                reply = f"I have processed your query regarding '{user_prompt}'. All subroutines indicate nominal status, {honorific}."

        clean_text = re.sub(r'[*_~`]', '', reply).strip()
        if not clean_text.endswith(honorific):
            clean_text = f"{clean_text}, {honorific}."

        audio_b64 = generate_voice_b64(clean_text, voice_char)

        return jsonify({
            'response': clean_text,
            'audio_b64': audio_b64,
            'blackout': trigger_blackout,
            'app_intent': app_launch_intent
        })

    except Exception as main_err:
        print(f"[MAIN API EXCEPTION]: {str(main_err)}")
        return jsonify({'response': f"System exception logged: {str(main_err)}", 'audio_b64': None}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)