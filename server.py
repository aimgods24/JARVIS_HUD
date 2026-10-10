from flask import Flask, render_template_string, request, jsonify, send_file
import edge_tts
import asyncio
import os
import re
import base64
import random
import subprocess
import threading
import time
from duckduckgo_search import DDGS

# Safely handle PyAutoGUI on headless cloud servers like Render
try:
    import pyautogui
    HAS_PYAUTOGUI = True
except Exception:
    HAS_PYAUTOGUI = False

# Safely handle Ollama on cloud environments without local Ollama daemon
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
                print(f"[NEWS ENGINE] News updated ({len(GLOBAL_NEWS_CACHE)} stories).")
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
    "Systems restored to maximum efficiency. How may I assist you today, {honorific}?",
    "Welcome back, {honorific}. Proton e.MAS 7 and device links are ready.",
    "Security check cleared. Standing by for your instructions, {honorific}."
]

def search_lyrics_or_music(query):
    try:
        results = list(DDGS().text(f"{query} song lyrics music", max_results=3))
        return "\n".join([f"🎵 {res['title']}\n{res['body']}" for res in results]) if results else "No music info found."
    except Exception as e:
        return f"Search error: {str(e)}"

def search_flight_details(flight_num):
    try:
        results = list(DDGS().text(f"flight status schedule departure arrival delay {flight_num}", max_results=3))
        return "\n".join([f"✈️ {res['title']}\n{res['body']}" for res in results]) if results else f"No radar info for flight {flight_num}."
    except Exception as e:
        return f"Flight error: {str(e)}"

def search_weather(location_str):
    try:
        results = list(DDGS().text(f"current weather forecast in {location_str}", max_results=2))
        return "\n".join([f"🌤️ {res['title']}\n{res['body']}" for res in results]) if results else "Weather data unavailable."
    except Exception as e:
        return f"Weather error: {str(e)}"

def search_nearby_cinemas(location_str):
    try:
        results = list(DDGS().text(f"cinemas movie theaters near {location_str} showtimes", max_results=3))
        return "\n".join([f"🎬 {res['title']}\n{res['body']}" for res in results]) if results else "No nearby cinemas found."
    except Exception as e:
        return f"Cinema error: {str(e)}"

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/manifest.json')
def manifest():
    return send_file('manifest.json')

@app.route('/sw.js')
def service_worker():
    return send_file('sw.js')

@app.route('/api/request_2fa', methods=['POST'])
def request_2fa():
    otp_code = str(random.randint(100000, 999999))
    return jsonify({'status': 'sent', 'demo_code': otp_code})

@app.route('/api/get_news', methods=['GET'])
def get_news():
    if GLOBAL_NEWS_CACHE:
        return jsonify({'status': 'success', 'news': GLOBAL_NEWS_CACHE})
    else:
        try:
            results = list(DDGS().text("breaking world global news headlines today", max_results=5))
            news = [f"📰 [{res['title']}] - {res['body']}" for res in results]
            return jsonify({'status': 'success', 'news': news})
        except Exception as e:
            return jsonify({'status': 'error', 'news': ["Global news service temporarily offline."]})

@app.route('/api/save_interests', methods=['POST'])
def save_interests():
    data = request.json or {}
    interests = data.get('interests', '')
    if interests:
        update_user_memory(f"User Saved Preferences/Interests: {interests}")
        return jsonify({'status': 'saved', 'message': 'Interests recorded in memory.'})
    return jsonify({'status': 'error'})

@app.route('/api/ask', methods=['POST'])
def ask():
    data = request.json or {}
    user_prompt = data.get('prompt', '').strip()
    images = data.get('images', [])
    honorific = data.get('honorific', 'Sir')
    voice_char = data.get('voice_char', 'jarvis')
    location = data.get('location', 'Bayan Lepas, Penang, Malaysia')
    battery_info = data.get('battery', 'Battery Normal')
    permissions = data.get('permissions', {})
    mode_transport = data.get('transport_mode', 'car')
    is_dnd = data.get('dnd_mode', False)

    if not user_prompt and not images:
        return jsonify({'response': f'No command received, {honorific}.', 'audio': False})

    cmd_lower = user_prompt.lower()
    reply = None
    media_action = None
    nav_destination = None
    ev_chargers = False
    seats_map = False
    c3po_nav_text = None
    is_shutdown = False
    trigger_blackout = False

    if "news" in cmd_lower or "headlines" in cmd_lower or "world update" in cmd_lower:
        if GLOBAL_NEWS_CACHE:
            news_summary = "\n\n".join(GLOBAL_NEWS_CACHE[:4])
            reply = f"Here are the latest global news headlines:\n\n{news_summary}"
        else:
            reply = f"Fetching real-time global news feed now, {honorific}."

    elif "blackout" in cmd_lower or "black out" in cmd_lower:
        trigger_blackout = True
        reply = f"Engaging HUD blackout mode. Communication terminal active, {honorific}."
    elif "shut down" in cmd_lower or "shutdown" in cmd_lower:
        is_shutdown = True
        reply = f"Initiating system shutdown. Entering standby mode, {honorific}."

    elif "direction" in cmd_lower or "navigate" in cmd_lower or "route" in cmd_lower or "map to" in cmd_lower:
        dest_match = re.sub(r'get directions to|directions to|navigate to|map to|take me to', '', user_prompt, flags=re.IGNORECASE).strip()
        nav_destination = dest_match if dest_match else "Target Destination"
        ev_chargers = (mode_transport == 'ev')
        
        c3po_nav_text = f"Oh my! Computing optimal route for {mode_transport.upper()} mode to {nav_destination}. " + \
                        ("Scanning for compatible EV charging stations along our journey, Master. " if ev_chargers else "") + \
                        f"Proceeding with turn-by-turn guidance now, Master!"
        reply = f"Full Google Maps navigation active for {nav_destination}. C-3PO guidance initiated, {honorific}."

    elif "play" in cmd_lower and ("spotify" in cmd_lower or "song" in cmd_lower or "music" in cmd_lower):
        song = re.sub(r'play|on spotify|spotify|song|music', '', user_prompt, flags=re.IGNORECASE).strip()
        media_action = {"type": "spotify", "query": song}
        reply = f"Streaming '{song}' on Spotify, {honorific}."
    elif "play" in cmd_lower or "youtube" in cmd_lower:
        yt_query = re.sub(r'play|on youtube|youtube|video', '', user_prompt, flags=re.IGNORECASE).strip()
        media_action = {"type": "youtube", "query": yt_query}
        reply = f"Loading YouTube video for '{yt_query}', {honorific}."

    elif "lyrics" in cmd_lower or "shazam" in cmd_lower or "what song" in cmd_lower:
        reply = search_lyrics_or_music(user_prompt)

    elif "proton" in cmd_lower or "emas" in cmd_lower or "car hud" in cmd_lower:
        if permissions.get('app_sync'):
            reply = f"Proton e.MAS 7 EV telemetry linked successfully. Vehicle battery and navigation HUD synced, {honorific}."
        else:
            reply = f"Proton e.MAS 7 HUD link requires app permission approval in settings, {honorific}."

    elif "weather" in cmd_lower or "forecast" in cmd_lower:
        reply = search_weather(location)
    elif "movie" in cmd_lower or "cinema" in cmd_lower or "theater" in cmd_lower:
        reply = search_nearby_cinemas(location)
        seats_map = True
    elif "flight" in cmd_lower or "airline" in cmd_lower or "terminal" in cmd_lower:
        flight_match = re.search(r'([a-zA-Z]{2,3}\s?\d{2,4})', user_prompt)
        reply = search_flight_details(flight_match.group(1)) if flight_match else f"Specify a flight number to track delays and terminals, {honorific}."

    elif "take screenshot" in cmd_lower:
        if HAS_PYAUTOGUI:
            pyautogui.screenshot('jarvis_screenshot.png')
            reply = f"Screenshot stored to host filesystem, {honorific}."
        else:
            reply = f"Screenshot module is reserved for local desktop mode, {honorific}."
    elif "click" in cmd_lower:
        if HAS_PYAUTOGUI:
            pyautogui.click()
            reply = f"Screen action performed, {honorific}."
        else:
            reply = f"Screen mouse control is reserved for local desktop mode, {honorific}."
    elif "open" in cmd_lower:
        app_name = cmd_lower.replace("open", "").strip()
        app_dict = {
            "chrome": "start chrome", "edge": "start msedge", "notepad": "notepad",
            "calculator": "calc", "cmd": "start cmd", "spotify": "start spotify"
        }
        try:
            if app_name.lower() in app_dict and HAS_PYAUTOGUI:
                subprocess.Popen(app_dict[app_name.lower()], shell=True)
                reply = f"Launching {app_name} on host PC, {honorific}."
            elif HAS_PYAUTOGUI:
                pyautogui.press('win')
                pyautogui.sleep(0.3)
                pyautogui.write(app_name)
                pyautogui.press('enter')
                reply = f"Opening {app_name} on host PC, {honorific}."
            else:
                reply = f"Desktop application launches are available when running locally on your PC, {honorific}."
        except Exception as e:
            reply = f"Unable to open {app_name}: {str(e)}"

    if not reply:
        user_memory = get_user_memory()
        system_instructions = (
            "You are J.A.R.V.I.S., a hyper-intelligent AI assistant. "
            f"Always finish your reply addressing the user strictly as {honorific}. "
            f"Device Telemetry: [{battery_info}]. Location: [{location}]. "
            "Help with any homework problem, code debugging, or image analysis thoroughly. "
            f"\n[USER MEMORY ARCHIVE]:\n{user_memory}"
        )

        model_to_use = 'moondream' if images else 'qwen2.5:0.5b'
        if HAS_OLLAMA:
            try:
                message_obj = {"role": "user", "content": user_prompt}
                if images:
                    message_obj["images"] = images

                response = ollama.chat(
                    model=model_to_use,
                    messages=[
                        {"role": "system", "content": system_instructions},
                        message_obj
                    ],
                    options={"num_predict": 80, "temperature": 0.2},
                    keep_alive=-1
                )
                reply = response['message']['content'].strip()
            except Exception as e:
                reply = f"Online cloud core operational. Direct command processed, {honorific}."
        else:
            reply = f"Cloud terminal online and fully active. Standing by for instructions, {honorific}."

    clean_text = re.sub(r'[*_~`]', '', reply)
    if not clean_text.endswith(honorific) and not c3po_nav_text:
        clean_text += f", {honorific}."

    has_audio = False
    if not is_dnd:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            if c3po_nav_text:
                loop.run_until_complete(generate_c3po_voice(c3po_nav_text))
            else:
                loop.run_until_complete(generate_voice(clean_text, voice_char))
            loop.close()
            has_audio = True
        except Exception:
            has_audio = False

    random_welcome = random.choice(WELCOME_MESSAGES).format(honorific=honorific)

    return jsonify({
        'response': reply, 
        'audio': has_audio, 
        'c3po_text': c3po_nav_text,
        'media_action': media_action,
        'nav_destination': nav_destination,
        'ev_chargers': ev_chargers,
        'seats_map': seats_map,
        'welcome_msg': random_welcome,
        'is_shutdown': is_shutdown,
        'blackout': trigger_blackout
    })

async def generate_voice(text, voice_char):
    voice_map = {
        'jarvis': 'en-GB-RyanNeural',
        'friday': 'en-IE-EmilyNeural',
        'cyber': 'en-US-ChristopherNeural'
    }
    selected_voice = voice_map.get(voice_char, 'en-GB-RyanNeural')
    communicate = edge_tts.Communicate(text, selected_voice, pitch="-2Hz", rate="+5%")
    await communicate.save("static_speech.mp3")

async def generate_c3po_voice(text):
    communicate = edge_tts.Communicate(text, "en-GB-ThomasNeural", pitch="+4Hz", rate="+10%")
    await communicate.save("static_speech.mp3")

@app.route('/api/audio')
def get_audio():
    return send_file('static_speech.mp3', mimetype='audio/mpeg')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)