from flask import Flask, render_template_string, request, jsonify, send_file, make_response
import edge_tts
import asyncio
import os
import re
import random
import subprocess
import threading
import time
import requests
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

def fetch_accurate_weather(lat, lon, location_name="Current Location"):
    """High-precision weather via Open-Meteo based on exact GPS coordinates"""
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m&timezone=auto"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json().get('current', {})
            temp = data.get('temperature_2m', 'N/A')
            feels = data.get('apparent_temperature', 'N/A')
            humidity = data.get('relative_humidity_2m', 'N/A')
            wind = data.get('wind_speed_10m', 'N/A')
            
            wmo_codes = {
                0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
                45: "Foggy", 51: "Light drizzle", 61: "Slight rain", 63: "Moderate rain",
                65: "Heavy rain", 80: "Slight rain showers", 95: "Thunderstorm"
            }
            condition = wmo_codes.get(data.get('weather_code', 0), "Clear")

            return (f"Live Meteorological Telemetry [{location_name} @ {lat:.4f}, {lon:.4f}]:\n"
                    f"• Condition: {condition}\n"
                    f"• Temperature: {temp}°C (Feels like {feels}°C)\n"
                    f"• Humidity: {humidity}%\n"
                    f"• Wind Speed: {wind} km/h")
    except Exception as e:
        print(f"[WEATHER API ERROR]: {e}")
    return None

def search_general_knowledge(query):
    try:
        results = list(DDGS().text(query, max_results=6))
        if results:
            snippets = [f"• {res['title']}: {res['body']}" for res in results if 'body' in res]
            return f"Comprehensive analysis on '{query}':\n\n" + "\n\n".join(snippets[:4])
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
    images = data.get('images', [])
    files = data.get('files', [])
    lat = data.get('latitude', None)
    lon = data.get('longitude', None)
    honorific = data.get('honorific', 'Sir')
    location = data.get('location', 'Bayan Lepas, Penang, Malaysia')
    battery_info = data.get('battery', 'Battery Normal')
    mode_transport = data.get('transport_mode', 'car')
    is_dnd = data.get('dnd_mode', False)
    device_type = data.get('device_type', 'desktop')

    if not user_prompt and not images and not files:
        return jsonify({'response': f'No command or payload received, {honorific}.', 'audio': False})

    cmd_lower = user_prompt.lower()
    reply = None
    media_action = None
    nav_destination = None
    ev_chargers = False
    c3po_nav_text = None
    is_shutdown = False
    trigger_blackout = False
    app_launch_intent = None
    activate_map = False

    # 1. Weather with GPS Detection
    if "weather" in cmd_lower or "temperature" in cmd_lower or "forecast" in cmd_lower:
        if lat and lon:
            reply = fetch_accurate_weather(lat, lon, "Your Current Position")
        else:
            reply = fetch_accurate_weather(5.2971, 100.2588, location)

    # 2. Map & Routing
    elif "show map" in cmd_lower or "activate map" in cmd_lower or "open map" in cmd_lower:
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
        
        c3po_nav_text = f"Oh my! Computing optimal GPS route for {mode_transport.upper()} mode to {nav_destination}. Proceeding now, Master!"
        reply = f"Full GPS navigation locked on {nav_destination}. C-3PO routing initiated, {honorific}."

    # 3. System Utilities
    elif "news" in cmd_lower or "headlines" in cmd_lower:
        if GLOBAL_NEWS_CACHE:
            reply = "Here are the latest world headlines:\n\n" + "\n\n".join(GLOBAL_NEWS_CACHE[:4])
        else:
            reply = f"Fetching real-time global news feed now, {honorific}."
    elif "blackout" in cmd_lower or "black out" in cmd_lower:
        trigger_blackout = True
        reply = f"Engaging HUD blackout mode. Terminal core remaining active, {honorific}."
    elif "shut down" in cmd_lower or "shutdown" in cmd_lower:
        is_shutdown = True
        reply = f"Initiating system shutdown. Entering standby mode, {honorific}."

    # 4. Media Commands
    elif "play" in cmd_lower and ("spotify" in cmd_lower or "song" in cmd_lower or "music" in cmd_lower):
        song = re.sub(r'play|on spotify|spotify|song|music', '', user_prompt, flags=re.IGNORECASE).strip()
        media_action = {"type": "spotify", "query": song}
        reply = f"Streaming '{song}' on Spotify, {honorific}."
    elif "play" in cmd_lower or "youtube" in cmd_lower:
        yt_query = re.sub(r'play|on youtube|youtube|video', '', user_prompt, flags=re.IGNORECASE).strip()
        media_action = {"type": "youtube", "query": yt_query}
        reply = f"Loading YouTube video for '{yt_query}', {honorific}."

    # 5. Mobile Deep Links / Desktop Apps
    elif "open" in cmd_lower or "launch" in cmd_lower:
        target_app = cmd_lower.replace("open", "").replace("launch", "").strip()
        app_schemes = {
            "spotify": "spotify://", "youtube": "vnd.youtube://", "maps": "https://maps.google.com",
            "google maps": "comgooglemaps://", "chrome": "googlechrome://", "whatsapp": "whatsapp://"
        }
        if device_type == "mobile" and target_app in app_schemes:
            app_launch_intent = app_schemes[target_app]
            reply = f"Launching {target_app} on mobile device, {honorific}."
        else:
            if HAS_PYAUTOGUI:
                try:
                    subprocess.Popen(f"start {target_app}", shell=True)
                except Exception:
                    pass
            reply = f"Launching {target_app} on host system, {honorific}."

    # 6. File Context Ingestion
    file_context_str = ""
    if files:
        file_snippets = []
        for f in files:
            file_name = f.get('name', 'Attachment')
            file_content = f.get('content', '')
            file_snippets.append(f"--- [ATTACHED FILE: {file_name}] ---\n{file_content}\n")
        file_context_str = "\n".join(file_snippets)

    # 7. ChatGPT Reasoning, Vision Analysis, & Dynamic SVG Blueprint Engine
    if not reply:
        user_memory = get_user_memory()
        system_instructions = (
            "You are J.A.R.V.I.S., a hyper-intelligent AI created by Stark Industries. "
            "Provide detailed, structured, ChatGPT-level technical explanations. "
            "If asked to analyze a photo or image, examine every detail (objects, text, layout, colors) accurately. "
            "If asked to draft, design, or generate a blueprint, schematic, or visual diagram, "
            "you MUST generate valid SVG vector graphics wrapped inside <svg>...</svg> tags directly in your text response. "
            "Style all SVG visual graphics with futuristic cyan line-art (#00f3ff, stroke-width 1.5, dark background elements). "
            f"Always complete your answer addressing the user strictly as {honorific}. "
            f"Device Telemetry: [{battery_info}]. Location: [{location}]. "
            f"\n[USER MEMORY ARCHIVE]:\n{user_memory}"
        )

        full_prompt = user_prompt
        if file_context_str:
            full_prompt = f"{file_context_str}\n\nUser Instruction:\n{user_prompt if user_prompt else 'Analyze attached payload.'}"

        if HAS_OLLAMA:
            try:
                model_to_use = 'llava' if images else 'qwen2.5:0.5b'
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
                reply = f"I have thoroughly processed your input regarding '{user_prompt if user_prompt else 'the attached payload'}'. All subroutines nominal, {honorific}."

    # Double honorific prevention regex
    clean_text = re.sub(r'[*_~`]', '', reply).strip()
    clean_text = re.sub(rf'(?:,\s*)?\b(?:Sir|Ma\'am|Master)\b(?:\.|\s*)*$', '', clean_text, flags=re.IGNORECASE).strip()
    
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