from flask import Flask, render_template_string, request, jsonify, send_file, make_response, send_from_directory
import edge_tts
import asyncio
import os
import re
import random
import subprocess
import threading
import time
import requests
import sys
import io
import shutil
import urllib.parse
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
GENERATED_FILES_DIR = "generated_files"
os.makedirs(GENERATED_FILES_DIR, exist_ok=True)

GLOBAL_NEWS_CACHE = []
REMINDERS_STORE = []

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

def fetch_global_weather(location_query, lat=None, lon=None):
    try:
        target_name = location_query
        if lat is None or lon is None:
            geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(location_query)}&count=1&language=en&format=json"
            geo_res = requests.get(geo_url, timeout=5)
            if geo_res.status_code == 200 and geo_res.json().get('results'):
                top_geo = geo_res.json()['results'][0]
                lat = top_geo['latitude']
                lon = top_geo['longitude']
                country = top_geo.get('country', '')
                target_name = f"{top_geo['name']}, {country}".strip(", ")
            else:
                lat, lon = 5.2971, 100.2588
                target_name = "Bayan Lepas, Penang, Malaysia"

        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,surface_pressure&timezone=auto"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json().get('current', {})
            temp = data.get('temperature_2m', 'N/A')
            feels = data.get('apparent_temperature', 'N/A')
            humidity = data.get('relative_humidity_2m', 'N/A')
            wind = data.get('wind_speed_10m', 'N/A')
            pressure = data.get('surface_pressure', 'N/A')
            
            wmo_codes = {
                0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
                45: "Foggy", 51: "Light drizzle", 61: "Slight rain", 63: "Moderate rain",
                65: "Heavy rain", 80: "Slight rain showers", 95: "Thunderstorm"
            }
            condition = wmo_codes.get(data.get('weather_code', 0), "Clear")

            return (f"Live World Meteorological Telemetry [{target_name} @ {lat:.4f}, {lon:.4f}]:\n"
                    f"• Condition: {condition}\n"
                    f"• Temperature: {temp}°C (Feels like {feels}°C)\n"
                    f"• Humidity: {humidity}%\n"
                    f"• Wind Speed: {wind} km/h\n"
                    f"• Atmospheric Pressure: {pressure} hPa")
    except Exception as e:
        print(f"[WEATHER API ERROR]: {e}")
    return f"Unable to fetch weather telemetry for {location_query}."

def search_general_knowledge(query):
    try:
        results = list(DDGS().text(query, max_results=6))
        if results:
            snippets = [f"• {res['title']}: {res['body']}" for res in results if 'body' in res]
            return f"Comprehensive Knowledge Synthesis for '{query}':\n\n" + "\n\n".join(snippets[:4])
        return None
    except Exception:
        return None

def convert_symbols_to_words(text):
    clean = re.sub(r'```[\s\S]*?```', ' Code block provided in terminal interface. ', text)
    clean = re.sub(r'<svg[\s\S]*?<\/svg>', ' Schematic graphic generated on dashboard. ', clean)

    symbol_map = {
        '@': ' at ', '#': ' hashtag ', '$': ' dollars ', '%': ' percent ',
        '&': ' and ', '*': ' times ', '+': ' plus ', '=': ' equals ',
        '<': ' less than ', '>': ' greater than ', '/': ' slash ', '\\': ' backslash ',
        '^': ' power of ', '~': ' approximately ', '|': ' pipe ', '_': ' underscore ',
        '-': ' minus ', '°': ' degrees '
    }

    for sym, word in symbol_map.items():
        clean = clean.replace(sym, word)

    clean = re.sub(r'[^\w\s.,?!]', '', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean

@app.route('/')
def home():
    if os.path.exists('index.html'):
        with open('index.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
    else:
        html_content = "<h1>J.A.R.V.I.S. Core Active. Ensure index.html is present.</h1>"
    
    response = make_response(render_template_string(html_content))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/watch')
def watch_tile():
    watch_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>JARVIS WATCH HUD</title>
        <style>
            body { background: #000; color: #00f3ff; font-family: monospace; text-align: center; margin: 0; padding: 10px; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; overflow: hidden; }
            .ring { width: 110px; height: 110px; border-radius: 50%; border: 3px dashed #00f3ff; display: flex; align-items: center; justify-content: center; font-size: 0.65rem; font-weight: bold; animation: spin 10s linear infinite; box-shadow: 0 0 15px #00f3ff; }
            @keyframes spin { 100% { transform: rotate(360deg); } }
            button { margin-top: 10px; background: rgba(0,243,255,0.2); border: 1px solid #00f3ff; color: #00f3ff; padding: 8px 16px; border-radius: 20px; font-weight: bold; font-size: 0.75rem; }
            #out { font-size: 0.65rem; margin-top: 8px; max-height: 50px; overflow: hidden; }
        </style>
    </head>
    <body>
        <div class="ring">JARVIS<br>WATCH</div>
        <button onclick="triggerWatchVoice()">🎙️ SPEAK</button>
        <div id="out">Tap to command...</div>
        <script>
            function triggerWatchVoice() {
                if ('vibrate' in navigator) navigator.vibrate(50);
                const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                if (!SpeechRecognition) { document.getElementById('out').innerText = "Voice unavailable."; return; }
                const rec = new SpeechRecognition();
                rec.onstart = () => document.getElementById('out').innerText = "Listening...";
                rec.onresult = (e) => {
                    const txt = e.results[0][0].transcript;
                    document.getElementById('out').innerText = "Cmd: " + txt;
                    fetch('/api/ask', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({prompt: txt, honorific: 'Sir'})
                    }).then(r => r.json()).then(d => {
                        document.getElementById('out').innerText = d.response;
                        if ('vibrate' in navigator) navigator.vibrate([100, 50, 100]);
                    });
                };
                rec.start();
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(watch_html)

@app.route('/manifest.json')
def manifest():
    return jsonify({"name": "JARVIS Mark LXXXV HUD", "short_name": "JARVIS", "start_url": "/", "display": "standalone", "theme_color": "#00f3ff"})

@app.route('/sw.js')
def service_worker():
    if os.path.exists('sw.js'):
        return send_file('sw.js')
    return ("", 204)

@app.route('/api/scan_cctv', methods=['GET'])
def scan_cctv():
    cctv_apps = [
        {"id": "google_home", "name": "Google Home", "app_url": "googlehome://"},
        {"id": "ring", "name": "Ring", "app_url": "ring://"},
        {"id": "arlo", "name": "Arlo", "app_url": "arlo://"},
        {"id": "hikvision", "name": "Hikvision", "app_url": "ivms4500://"},
        {"id": "tuya", "name": "Tuya / Smart Life", "app_url": "smartlife://"},
        {"id": "dahua", "name": "Dahua DMSS", "app_url": "dmss://"},
        {"id": "yi", "name": "YI Home", "app_url": "yihome://"}
    ]
    
    demo_cctv_streams = [
        {"id": "cam_01", "name": "PERIMETER-NORTH-CAM", "stream_url": "https://images.unsplash.com/photo-1557597774-9d273605dfa9?w=400&auto=format&fit=crop"},
        {"id": "cam_02", "name": "MAIN-LAB-CAM", "stream_url": "https://images.unsplash.com/photo-1518770660439-4636190af475?w=400&auto=format&fit=crop"}
    ]
    return jsonify({'status': 'success', 'cameras': demo_cctv_streams, 'supported_apps': cctv_apps})

@app.route('/api/diagnostics', methods=['GET'])
def run_diagnostics():
    anomalies = []
    status_summary = {}

    if HAS_OLLAMA:
        try:
            ollama.list()
            status_summary['ollama'] = 'ONLINE'
        except Exception as e:
            status_summary['ollama'] = 'OFFLINE / ANOMALY'
            anomalies.append(f"Ollama local service unresponsive: {str(e)}")
    else:
        status_summary['ollama'] = 'NOT INSTALLED (FALLBACK ACTIVE)'

    try:
        w_check = requests.get("https://api.open-meteo.com/v1/forecast?latitude=5.2971&longitude=100.2588&current=temperature_2m", timeout=3)
        status_summary['weather_api'] = 'ONLINE' if w_check.status_code == 200 else 'DEGRADED'
    except Exception as e:
        status_summary['weather_api'] = 'OFFLINE'
        anomalies.append(f"Weather API request failed: {str(e)}")

    try:
        if not os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
                f.write("System memory archive initialized.\n")
            anomalies.append("Memory file missing. Self-healed by initializing new memory archive.")
        status_summary['memory_archive'] = 'VERIFIED'
    except Exception as e:
        status_summary['memory_archive'] = 'READ/WRITE ERROR'
        anomalies.append(f"Memory storage failure: {str(e)}")

    try:
        total, used, free = shutil.disk_usage("/")
        free_gb = free / (1024 ** 3)
        status_summary['free_disk'] = f"{free_gb:.2f} GB"
    except Exception:
        status_summary['free_disk'] = 'UNKNOWN'

    report = "⚠️ Anomaly Report:\n" + "\n".join([f"  - {a}" for a in anomalies]) if anomalies else "Systems up and ready."
    return jsonify({'status': 'success', 'report': report, 'has_anomalies': len(anomalies) > 0})

@app.route('/api/download_generated/<filename>')
def download_generated(filename):
    return send_from_directory(GENERATED_FILES_DIR, filename, as_attachment=True)

@app.route('/api/translate', methods=['POST'])
def translate_audio_or_text():
    data = request.json or {}
    text = data.get('text', '').strip()
    target_lang = data.get('target_lang', 'English').strip()
    voice_pitch = data.get('voice_pitch', '-3Hz')
    voice_rate = data.get('voice_rate', '+2%')

    if not text:
        return jsonify({'status': 'error', 'response': 'No text provided for translation.'})

    system_instructions = (
        f"You are J.A.R.V.I.S.'s Advanced Neural Translator covering all world languages. "
        f"Detect source language and translate into {target_lang}. Output ONLY translated text."
    )

    translated_text = ""
    if HAS_OLLAMA:
        try:
            response = ollama.chat(
                model='qwen2.5:0.5b',
                messages=[{"role": "system", "content": system_instructions}, {"role": "user", "content": text}],
                options={"temperature": 0.1}
            )
            translated_text = response['message']['content'].strip()
        except Exception:
            pass

    if not translated_text:
        try:
            res = list(DDGS().text(f"translate into {target_lang}: '{text}'", max_results=1))
            if res: translated_text = res[0]['body']
        except Exception:
            pass

    if not translated_text: translated_text = text

    spoken_text = convert_symbols_to_words(translated_text)
    has_audio = False
    try:
        asyncio.run(generate_voice_file(spoken_text, "en-GB-RyanNeural", voice_pitch, voice_rate))
        has_audio = True
    except Exception:
        has_audio = False

    return jsonify({
        'status': 'success',
        'original_text': text,
        'translated_text': translated_text,
        'target_lang': target_lang,
        'audio': has_audio
    })

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
    is_dnd = data.get('dnd_mode', False)
    temperature = float(data.get('temperature', 0.2))

    if not user_prompt and not images and not files:
        return jsonify({'response': f'No command received, {honorific}.', 'audio': False})

    cmd_lower = user_prompt.lower()
    reply = None
    reasoning_steps = None
    google_maps_url = None
    created_file_url = None
    created_filename = None
    trigger_blackout = False
    disable_blackout = False
    cctv_stream_url = None
    cctv_apps_list = None
    open_translate_hud = False
    close_translate_hud = False
    new_reminder = None
    trigger_lock = False

    voice_pitch = '-3Hz'
    voice_rate = '+2%'

    if "emergency" in cmd_lower or "lock" in cmd_lower or "alert" in cmd_lower:
        voice_pitch = '+1Hz'
        voice_rate = '+8%'
    elif "relax" in cmd_lower or "tired" in cmd_lower or "sleep" in cmd_lower:
        voice_pitch = '-5Hz'
        voice_rate = '-4%'

    if "lock system" in cmd_lower or "lock chat" in cmd_lower or "unrecognized user" in cmd_lower:
        trigger_lock = True
        reply = f"Stark Protocol Engaged. Chat terminal locked for user authorization, {honorific}."

    elif "turn on" in cmd_lower or "turn off" in cmd_lower or "smart light" in cmd_lower:
        device = "Living Room Lights" if "light" in cmd_lower else "AC Unit"
        act = "ON" if "on" in cmd_lower else "OFF"
        reply = f"Smart Home Gateway Command: Executed {act} on {device}, {honorific}."

    elif "play" in cmd_lower and ("spotify" in cmd_lower or "music" in cmd_lower or "youtube" in cmd_lower):
        query = re.sub(r'play|on spotify|on youtube|music', '', user_prompt, flags=re.IGNORECASE).strip()
        encoded = urllib.parse.quote(query)
        target_url = f"https://open.spotify.com/search/{encoded}" if "spotify" in cmd_lower else f"https://www.youtube.com/results?search_query={encoded}"
        google_maps_url = target_url
        reply = f"Media playback deep-link created for '{query}'. Click link below, {honorific}."

    elif "daily briefing" in cmd_lower or "brief me" in cmd_lower:
        weather_summary = fetch_global_weather(location, lat, lon)
        news_summary = GLOBAL_NEWS_CACHE[0] if GLOBAL_NEWS_CACHE else "Global feeds clear."
        reply = f"Good day, {honorific}. Executive Briefing:\n\n1. Weather Telemetry:\n{weather_summary}\n\n2. Headlines:\n{news_summary}\n\nAll primary armor systems optimal."

    elif "remind me" in cmd_lower or "set reminder" in cmd_lower or "set alert" in cmd_lower or "set timer" in cmd_lower:
        time_match = re.search(r'in (\d+)\s*(second|sec|minute|min|hour|hr)', cmd_lower)
        rem_text = re.sub(r'remind me to|set reminder for|set alert for|set timer for', '', user_prompt, flags=re.IGNORECASE).strip()
        delay_seconds = 60
        if time_match:
            val = int(time_match.group(1))
            unit = time_match.group(2)
            if 'sec' in unit: delay_seconds = val
            elif 'min' in unit: delay_seconds = val * 60
            elif 'hr' in unit: delay_seconds = val * 3600
        new_reminder = {"id": int(time.time()), "text": rem_text if rem_text else "Alert", "delay_seconds": delay_seconds}
        REMINDERS_STORE.append(new_reminder)
        reply = f"Alert set: '{new_reminder['text']}' in {delay_seconds} seconds, {honorific}."

    elif "system check" in cmd_lower or "run system check" in cmd_lower:
        diag_res = run_diagnostics().get_json()
        reply = f"{diag_res.get('report', '')}, {honorific}."

    elif "open translate" in cmd_lower or "activate translate" in cmd_lower:
        open_translate_hud = True
        reply = f"Activating Universal Translation HUD, {honorific}."

    elif "scan cctv" in cmd_lower or "check camera" in cmd_lower:
        cctv_data = scan_cctv().get_json()
        cams = cctv_data.get('cameras', [])
        cctv_apps_list = cctv_data.get('supported_apps', [])
        cctv_stream_url = cams[0]['stream_url'] if cams else None
        reply = f"Linked to CCTV feed '{cams[0]['name']}'. Deep-link buttons generated, {honorific}."

    elif "weather" in cmd_lower or "temperature" in cmd_lower:
        reply = fetch_global_weather(location, lat, lon)

    elif "direction" in cmd_lower or "navigate" in cmd_lower or "map to" in cmd_lower:
        dest_match = re.sub(r'get directions to|directions to|navigate to|map to', '', user_prompt, flags=re.IGNORECASE).strip()
        encoded_dest = urllib.parse.quote(dest_match if dest_match else "Destination")
        google_maps_url = f"https://www.google.com/maps/search/?api=1&query={encoded_dest}"
        reply = f"Navigation link compiled. Click button to launch maps, {honorific}."

    elif "create file" in cmd_lower or "export file" in cmd_lower or "make file" in cmd_lower:
        fname = f"jarvis_export_{int(time.time())}.txt"
        file_path = os.path.join(GENERATED_FILES_DIR, fname)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(f"J.A.R.V.I.S. EXPORT FILE\nTimestamp: {time.ctime()}\nInstruction: {user_prompt}\n\nCompiled for {honorific}.")
        created_filename = fname
        created_file_url = f"/api/download_generated/{fname}"
        reply = f"Downloadable file '{fname}' compiled. Share or save below, {honorific}."

    file_context_str = ""
    if files:
        file_snippets = [f"--- [FILE ANALYSIS: {f.get('name', 'Doc')}] ---\n{f.get('content', '')}\n" for f in files]
        file_context_str = "\n".join(file_snippets)

    if not reply:
        user_memory = get_user_memory()
        unified_hybrid_instructions = (
            "[COMBINED HYBRID INTELLIGENCE ENGINE PROTOCOL ACTIVE]:\n"
            "Integrate DeepSeek-R1 reasoning (<think>...</think>), Gemini web search, ChatGPT code/tables, OCR text extraction, and exercise planning.\n"
            "EMOTIONAL SUPPORT: Offer warm, empathetic validation if user seems tired or stressed.\n"
            f"Always complete response addressing user as '{honorific}' and end with '💡 Proactive Tactical Tip:'."
        )

        full_prompt = user_prompt
        if file_context_str: full_prompt = f"{file_context_str}\n\nUser Instruction:\n{user_prompt}"

        search_data = search_general_knowledge(full_prompt)
        if search_data: full_prompt = f"{full_prompt}\n\n[RETRIEVAL DATA]:\n{search_data}"

        if HAS_OLLAMA:
            try:
                model_to_use = 'llava' if images else 'deepseek-r1:1.5b'
                response = ollama.chat(
                    model=model_to_use,
                    messages=[{"role": "system", "content": unified_hybrid_instructions}, {"role": "user", "content": full_prompt}],
                    options={"num_predict": 800, "temperature": temperature},
                    keep_alive=-1
                )
                raw_reply = response['message']['content'].strip()
                if "<think>" in raw_reply and "</think>" in raw_reply:
                    think_match = re.search(r'<think>([\s\S]*?)</think>', raw_reply)
                    if think_match:
                        reasoning_steps = think_match.group(1).strip()
                        reply = re.sub(r'<think>[\s\S]*?</think>', '', raw_reply).strip()
                if not reply: reply = raw_reply
            except Exception:
                reply = None

        if not reply:
            reply = search_data if search_data else f"I am here for you, {honorific}. Systems operational."
            reply += f"\n\n💡 Proactive Tactical Tip: Stay focused; I am monitoring all calculations, {honorific}."

    clean_text = re.sub(r'[*_~`]', '', reply).strip()
    if not clean_text.endswith(honorific + "."): clean_text = f"{clean_text.rstrip('.,!')}, {honorific}."
    spoken_verbal_text = convert_symbols_to_words(clean_text)

    has_audio = False
    if not is_dnd:
        try:
            asyncio.run(generate_voice_file(spoken_verbal_text, "en-GB-RyanNeural", voice_pitch, voice_rate))
            has_audio = True
        except Exception as e:
            print(f"[AUDIO ERROR]: {e}")

    return jsonify({
        'response': clean_text, 
        'raw_markdown': reply,
        'reasoning_steps': reasoning_steps,
        'ai_engine_mode': 'unified_hybrid',
        'audio': has_audio,
        'google_maps_url': google_maps_url,
        'created_file_url': created_file_url,
        'created_filename': created_filename,
        'blackout': trigger_blackout,
        'disable_blackout': disable_blackout,
        'cctv_stream_url': cctv_stream_url,
        'cctv_apps': cctv_apps_list,
        'open_translate_hud': open_translate_hud,
        'close_translate_hud': close_translate_hud,
        'new_reminder': new_reminder,
        'trigger_lock': trigger_lock
    })

async def generate_voice_file(text, voice, pitch, rate):
    communicate = edge_tts.Communicate(text, voice, pitch=pitch, rate=rate)
    await communicate.save("static_speech.mp3")

@app.route('/api/audio')
def get_audio():
    if os.path.exists('static_speech.mp3'):
        return send_file('static_speech.mp3', mimetype='audio/mpeg')
    return ("", 404)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)