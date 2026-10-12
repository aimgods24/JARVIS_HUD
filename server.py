from flask import Flask, render_template_string, request, jsonify, send_file, make_response
import edge_tts
import asyncio
import os
import re
import random
import subprocess
import threading
import time
from duckduckgo_search import DDGS

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
app.config['TEMPLATES_AUTO_RELOAD'] = True

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

def search_general_knowledge(query):
    """ChatGPT-grade search & synthesis engine"""
    try:
        results = list(DDGS().text(query, max_results=6))
        if results:
            snippets = [f"• {res['title']}: {res['body']}" for res in results if 'body' in res]
            detailed_response = f"I have conducted a comprehensive analysis on '{query}'. Here is the breakdown:\n\n" + "\n\n".join(snippets[:4])
            return detailed_response
        return None
    except Exception:
        return None

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
    with open('index.html', 'r', encoding='utf-8') as f:
        html_content = f.read()
    response = make_response(render_template_string(html_content))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

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
        except Exception:
            return jsonify({'status': 'error', 'news': ["Global news service temporarily offline."]})

@app.route('/api/ask', methods=['POST'])
def ask():
    data = request.json or {}
    user_prompt = data.get('prompt', '').strip()
    images = data.get('images', [])  # Base64 image payloads
    files = data.get('files', [])    # Document and text payloads
    honorific = data.get('honorific', 'Sir')
    location = data.get('location', 'Bayan Lepas, Penang, Malaysia')
    battery_info = data.get('battery', 'Battery Normal')
    mode_transport = data.get('transport_mode', 'car')
    is_dnd = data.get('dnd_mode', False)
    device_type = data.get('device_type', 'desktop')

    if not user_prompt and not images and not files:
        return jsonify({'response': f'No command or file payload received, {honorific}.', 'audio': False})

    cmd_lower = user_prompt.lower()
    reply = None
    media_action = None
    nav_destination = None
    ev_chargers = False
    seats_map = False
    c3po_nav_text = None
    is_shutdown = False
    trigger_blackout = False
    app_launch_intent = None
    activate_map = False

    # 1. Map Navigation Controls
    if "show map" in cmd_lower or "activate map" in cmd_lower or "open map" in cmd_lower:
        activate_map = True
        reply = f"Activating tactical GPS HUD map overlay now, {honorific}."
    elif "hide map" in cmd_lower or "close map" in cmd_lower:
        activate_map = False
        reply = f"Deactivating map overlay and returning to diagnostic view, {honorific}."
    elif "direction" in cmd_lower or "navigate" in cmd_lower or "route" in cmd_lower or "map to" in cmd_lower:
        activate_map = True
        dest_match = re.sub(r'get directions to|directions to|navigate to|map to|take me to', '', user_prompt, flags=re.IGNORECASE).strip()
        nav_destination = dest_match if dest_match else "Target Destination"
        ev_chargers = (mode_transport == 'ev')
        
        c3po_nav_text = f"Oh my! Computing optimal high-precision GPS route for {mode_transport.upper()} mode to {nav_destination}. " + \
                        ("Scanning for compatible EV charging stations along our journey, Master. " if ev_chargers else "") + \
                        f"Proceeding with turn-by-turn guidance now, Master!"
        reply = f"Full Google Maps GPS tracking active for {nav_destination}. C-3PO guidance initiated, {honorific}."

    # 2. System Utilities & News
    elif "news" in cmd_lower or "headlines" in cmd_lower or "world update" in cmd_lower:
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

    # 3. Media Commands
    elif "play" in cmd_lower and ("spotify" in cmd_lower or "song" in cmd_lower or "music" in cmd_lower):
        song = re.sub(r'play|on spotify|spotify|song|music', '', user_prompt, flags=re.IGNORECASE).strip()
        media_action = {"type": "spotify", "query": song}
        reply = f"Streaming '{song}' on Spotify, {honorific}."
    elif "play" in cmd_lower or "youtube" in cmd_lower:
        yt_query = re.sub(r'play|on youtube|youtube|video', '', user_prompt, flags=re.IGNORECASE).strip()
        media_action = {"type": "youtube", "query": yt_query}
        reply = f"Loading YouTube video for '{yt_query}', {honorific}."

    # 4. Search Utilities
    elif "lyrics" in cmd_lower or "shazam" in cmd_lower or "what song" in cmd_lower:
        reply = search_lyrics_or_music(user_prompt)
    elif "proton" in cmd_lower or "emas" in cmd_lower or "car hud" in cmd_lower:
        reply = f"Proton e.MAS 7 EV telemetry linked successfully. Battery at 88%, {honorific}."
    elif "weather" in cmd_lower or "forecast" in cmd_lower:
        reply = search_weather(location)
    elif "movie" in cmd_lower or "cinema" in cmd_lower or "theater" in cmd_lower:
        reply = search_nearby_cinemas(location)
        seats_map = True
    elif "flight" in cmd_lower or "airline" in cmd_lower or "terminal" in cmd_lower:
        flight_match = re.search(r'([a-zA-Z]{2,3}\s?\d{2,4})', user_prompt)
        reply = search_flight_details(flight_match.group(1)) if flight_match else f"Specify a flight number to track delays, {honorific}."

    # 5. Mobile Deep Links & Desktop Desktop OS Integration
    elif "open" in cmd_lower or "launch" in cmd_lower:
        target_app = cmd_lower.replace("open", "").replace("launch", "").strip()
        app_schemes = {
            "spotify": "spotify://",
            "youtube": "vnd.youtube://",
            "maps": "https://maps.google.com",
            "google maps": "comgooglemaps://",
            "chrome": "googlechrome://",
            "whatsapp": "whatsapp://",
            "instagram": "instagram://"
        }

        if device_type == "mobile":
            if target_app in app_schemes:
                app_launch_intent = app_schemes[target_app]
                reply = f"Opening {target_app} on mobile device, {honorific}."
            elif "youtube" in target_app:
                app_launch_intent = "vnd.youtube://"
                reply = f"Launching YouTube app, {honorific}."
            elif "map" in target_app:
                app_launch_intent = "https://maps.google.com"
                reply = f"Opening Google Maps, {honorific}."
            else:
                reply = f"Attempting to trigger mobile deep link for {target_app}, {honorific}."
        else:
            app_dict = {
                "chrome": "start chrome", "edge": "start msedge", "notepad": "notepad",
                "calculator": "calc", "cmd": "start cmd", "spotify": "start spotify"
            }
            if HAS_PYAUTOGUI:
                try:
                    if target_app.lower() in app_dict:
                        subprocess.Popen(app_dict[target_app.lower()], shell=True)
                    else:
                        pyautogui.press('win')
                        pyautogui.sleep(0.3)
                        pyautogui.write(target_app)
                        pyautogui.press('enter')
                except Exception:
                    pass
            reply = f"Launching {target_app} on host desktop, {honorific}."

    # 6. File Attachments Integration
    file_context_str = ""
    if files:
        file_snippets = []
        for f in files:
            file_name = f.get('name', 'Attachment')
            file_content = f.get('content', '')
            file_snippets.append(f"--- [ATTACHED FILE: {file_name}] ---\n{file_content}\n")
        file_context_str = "\n".join(file_snippets)

    # 7. ChatGPT-Grade Reasoning & Dynamic Blueprint Engine
    if not reply:
        user_memory = get_user_memory()
        system_instructions = (
            "You are J.A.R.V.I.S., an advanced AI created by Stark Industries. "
            "Provide comprehensive, structured, ChatGPT-level explanations with full technical accuracy. "
            "When the user asks you to design, draft, generate, or render a blueprint, schematic, design, or diagram, "
            "you MUST generate valid SVG vector graphics wrapped inside <svg>...</svg> tags directly in your text response. "
            "Style all SVG visual graphics with futuristic cyan line-art (#00f3ff, stroke-width 1.5, dark background elements). "
            f"Always finish your reply addressing the user strictly as {honorific}. "
            f"Device Telemetry: [{battery_info}]. Location: [{location}]. "
            f"\n[USER MEMORY ARCHIVE]:\n{user_memory}"
        )

        full_prompt = user_prompt
        if file_context_str:
            full_prompt = f"{file_context_str}\n\nUser Instruction:\n{user_prompt if user_prompt else 'Analyze the attached document and provide a complete breakdown.'}"

        if HAS_OLLAMA:
            try:
                model_to_use = 'moondream' if images else 'qwen2.5:0.5b'
                message_obj = {"role": "user", "content": full_prompt}
                if images:
                    message_obj["images"] = images

                response = ollama.chat(
                    model=model_to_use,
                    messages=[
                        {"role": "system", "content": system_instructions},
                        message_obj
                    ],
                    options={"num_predict": 600, "temperature": 0.2},
                    keep_alive=-1
                )
                reply = response['message']['content'].strip()
            except Exception:
                reply = None

        if not reply:
            ai_answer = search_general_knowledge(full_prompt)
            if ai_answer:
                reply = ai_answer
            else:
                reply = f"I have thoroughly analyzed your prompt regarding '{user_prompt if user_prompt else 'the attached payload'}'. All neural pathways report nominal execution status, {honorific}."

    # Prevent double honorific occurrences
    clean_text = re.sub(r'[*_~`]', '', reply).strip()
    pattern = rf'(?:,\s*)?\b(?:Sir|Ma\'am|Master)\b(?:\.|\s*)*$'
    clean_text = re.sub(pattern, '', clean_text, flags=re.IGNORECASE).strip()
    
    if not c3po_nav_text:
        clean_text = f"{clean_text.rstrip('.,!')}, {honorific}."

    has_audio = False
    if not is_dnd:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            if c3po_nav_text:
                loop.run_until_complete(generate_c3po_voice(c3po_nav_text))
            else:
                loop.run_until_complete(generate_jarvis_movie_voice(clean_text))
            loop.close()
            has_audio = True
        except Exception:
            has_audio = False

    return jsonify({
        'response': clean_text, 
        'audio': has_audio, 
        'c3po_text': c3po_nav_text,
        'media_action': media_action,
        'nav_destination': nav_destination,
        'ev_chargers': ev_chargers,
        'seats_map': seats_map,
        'is_shutdown': is_shutdown,
        'blackout': trigger_blackout,
        'app_intent': app_launch_intent,
        'device_type': device_type,
        'activate_map': activate_map
    })

async def generate_jarvis_movie_voice(text):
    communicate = edge_tts.Communicate(text, "en-GB-RyanNeural", pitch="-3Hz", rate="+2%")
    await communicate.save("static_speech.mp3")

async def generate_c3po_voice(text):
    communicate = edge_tts.Communicate(text, "en-GB-ThomasNeural", pitch="+4Hz", rate="+10%")
    await communicate.save("static_speech.mp3")

@app.route('/api/audio')
def get_audio():
    return send_file('static_speech.mp3', mimetype='audio/mpeg')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)