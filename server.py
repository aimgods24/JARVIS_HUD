vfrom flask import Flask, render_template_string, request, jsonify, send_file, make_response, send_from_directory
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
            results = list(DDGS().text("breaking world news headlines today", max_results=8))
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

            return (f"Live Meteorological Telemetry [{target_name} @ {lat:.4f}, {lon:.4f}]:\n"
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

def parse_contextual_intent(prompt):
    p = prompt.lower()
    if any(w in p for w in ["cancel cctv", "disconnect camera", "close camera", "stop feed", "turn off camera", "close cctv", "hide cctv", "stop cctv"]):
        return "CANCEL_CCTV"
    if any(w in p for w in ["connect to cctv", "scan cctv", "check camera", "show camera", "cctv feed", "front door camera", "security feed", "perimeter camera", "view feed"]):
        return "CCTV_SCAN"
    if any(w in p for w in ["open translate", "activate translate", "launch translate", "translate mode", "translator"]):
        return "OPEN_TRANSLATE"
    if any(w in p for w in ["dark", "cant see", "turn on lights", "brighten", "lights on", "lights off", "too cold", "too hot", "turn on ac"]):
        return "SMART_HOME"
    if any(w in p for w in ["good morning", "brief me", "schedule today", "whats happening", "daily update", "status report"]):
        return "DAILY_BRIEFING"
    if any(w in p for w in ["play music", "put on some tracks", "spotify", "youtube", "play video", "listen to"]):
        return "MEDIA_PLAYBACK"
    if any(w in p for w in ["lock up", "secure terminal", "intruder", "lock system", "unauthorized"]):
        return "SECURITY_LOCK"
    if any(w in p for w in ["health check", "diagnostics", "system state", "check hardware"]):
        return "SYS_DIAGNOSTICS"
        
    return "GENERAL"

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
        <link rel="manifest" href="/manifest.json">
        <title>JARVIS WATCH WIDGET</title>
        <style>
            body { background: #000; color: #00f3ff; font-family: -apple-system, sans-serif; text-align: center; margin: 0; padding: 6px; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; overflow: hidden; }
            .widget-ring { width: 120px; height: 120px; border-radius: 50%; border: 3px solid #00f3ff; display: flex; flex-direction: column; align-items: center; justify-content: center; font-size: 0.65rem; font-weight: bold; box-shadow: 0 0 15px #00f3ff; cursor: pointer; }
            .widget-ring:active { transform: scale(0.95); opacity: 0.8; }
            button { margin-top: 10px; background: rgba(0,243,255,0.2); border: 1px solid #00f3ff; color: #00f3ff; padding: 6px 14px; border-radius: 20px; font-weight: bold; font-size: 0.7rem; width: 100%; }
            #out { font-size: 0.65rem; margin-top: 6px; max-height: 45px; overflow: hidden; text-overflow: ellipsis; }
        </style>
    </head>
    <body>
        <div class="widget-ring" onclick="triggerWatchVoice()">
            <span>J.A.R.V.I.S.</span>
            <span style="font-size:0.5rem; opacity:0.8;">TAP TO SPEAK</span>
        </div>
        <div id="out">Widget Connected</div>
        <script>
            function triggerWatchVoice() {
                if ('vibrate' in navigator) navigator.vibrate(40);
                const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                if (!SpeechRecognition) { document.getElementById('out').innerText = "Mic Unavailable"; return; }
                const rec = new SpeechRecognition();
                rec.onstart = () => document.getElementById('out').innerText = "Listening...";
                rec.onresult = (e) => {
                    const txt = e.results[0][0].transcript;
                    document.getElementById('out').innerText = txt;
                    fetch('/api/ask', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({prompt: txt, honorific: 'Sir'})
                    }).then(r => r.json()).then(d => {
                        document.getElementById('out').innerText = d.response;
                        if ('vibrate' in navigator) navigator.vibrate([80, 40, 80]);
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
    return jsonify({
        "name": "JARVIS Mark LXXXV HUD",
        "short_name": "JARVIS",
        "start_url": "/watch",
        "display": "standalone",
        "background_color": "#000000",
        "theme_color": "#00f3ff",
        "icons": [{"src": "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=192&auto=format&fit=crop", "sizes": "192x192", "type": "image/png"}]
    })

@app.route('/sw.js')
def service_worker():
    return ("self.addEventListener('fetch', function(e) {});", 200, {'Content-Type': 'application/javascript'})

@app.route('/api/scan_cctv', methods=['POST', 'GET'])
def scan_cctv():
    data = request.json or {}
    custom_url = data.get('custom_stream_url', '').strip()
    
    universal_cctv_protocols = [
        {"id": "rtsp_generic", "name": "Universal RTSP / ONVIF IP Bridge", "protocol": "rtsp://", "status": "Active"},
        {"id": "webrtc_generic", "name": "WebRTC Low-Latency Stream", "protocol": "webrtc://", "status": "Active"},
        {"id": "hikvision", "name": "Hikvision / Dahua / Axis / Reolink", "app_url": "ivms4500://"},
        {"id": "google_nest", "name": "Google Nest / Home", "app_url": "googlehome://"},
        {"id": "ring", "name": "Ring / Blink / Wyze", "app_url": "ring://"},
        {"id": "tuya", "name": "Tuya / Smart Life / Arlo", "app_url": "smartlife://"}
    ]
    
    demo_cctv_streams = [
        {"id": "cam_01", "name": "PERIMETER-NORTH-CAM", "stream_url": custom_url if custom_url else "https://images.unsplash.com/photo-1557597774-9d273605dfa9?w=400&auto=format&fit=crop"},
        {"id": "cam_02", "name": "MAIN-LAB-CAM", "stream_url": "https://images.unsplash.com/photo-1518770660439-4636190af475?w=400&auto=format&fit=crop"}
    ]
    return jsonify({'status': 'success', 'cameras': demo_cctv_streams, 'supported_apps': universal_cctv_protocols})

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
        return jsonify({'status': 'error', 'response': 'No speech text provided for translation.'})

    system_instructions = (
        f"You are J.A.R.V.I.S.'s Universal Subtitle & Translation Engine. "
        f"Detect the source language and translate directly into {target_lang}. "
        f"Output strictly ONLY the translated text without extra conversational fluff."
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
    inferred_intent = parse_contextual_intent(user_prompt)
    reply = None
    reasoning_steps = None
    google_maps_url = None
    created_file_url = None
    created_filename = None
    cctv_stream_url = None
    cancel_cctv = False
    cctv_apps_list = None
    open_translate_hud = False
    new_reminder = None
    trigger_lock = False

    voice_pitch = '-3Hz'
    voice_rate = '+2%'

    if inferred_intent == "CANCEL_CCTV":
        cancel_cctv = True
        reply = f"CCTV feed disconnected. Reverting orb HUD interface to Arc Core mode, {honorific}."

    elif inferred_intent == "CCTV_SCAN":
        cctv_data = scan_cctv().get_json()
        cams = cctv_data.get('cameras', [])
        cctv_apps_list = cctv_data.get('supported_apps', [])
        cctv_stream_url = cams[0]['stream_url'] if cams else None
        reply = f"CCTV signal acquired. Live video feed projected directly into the core HUD orb, {honorific}."

    elif inferred_intent == "OPEN_TRANSLATE":
        open_translate_hud = True
        reply = f"Activating floating Universal Translation HUD window, {honorific}."

    elif inferred_intent == "SECURITY_LOCK":
        trigger_lock = True
        reply = f"Stark Security Protocol Engaged. Locking chat terminal, {honorific}."

    elif inferred_intent == "SMART_HOME":
        act = "OFF" if "off" in cmd_lower else "ON"
        device = "Living Room AC" if "ac" in cmd_lower or "cold" in cmd_lower or "hot" in cmd_lower else "Primary Lights"
        reply = f"Inferred intent detected: Configured {device} state to {act}, {honorific}."

    elif inferred_intent == "DAILY_BRIEFING":
        weather_summary = fetch_global_weather(location, lat, lon)
        news_summary = GLOBAL_NEWS_CACHE[0] if GLOBAL_NEWS_CACHE else "Global news feeds nominal."
        reply = f"Good day, {honorific}. Executive Briefing:\n\n1. Weather Telemetry:\n{weather_summary}\n\n2. Headlines:\n{news_summary}\n\nAll armor systems optimal."

    elif inferred_intent == "MEDIA_PLAYBACK":
        query = re.sub(r'play|put on|some tracks|music|video|listen to|spotify|youtube', '', user_prompt, flags=re.IGNORECASE).strip()
        encoded = urllib.parse.quote(query if query else "Ambient Tracks")
        target_url = f"https://open.spotify.com/search/{encoded}" if "spotify" in cmd_lower else f"https://www.youtube.com/results?search_query={encoded}"
        google_maps_url = target_url
        reply = f"Inferred media intent: Prepared playback for '{query if query else 'Ambient Tracks'}'. Click deep link below, {honorific}."

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
            reply = search_data if search_data else f"I am listening and monitoring, {honorific}. Systems operational."
            reply += f"\n\n💡 Proactive Tactical Tip: Stay focused; calculations running, {honorific}."

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
        'cctv_stream_url': cctv_stream_url,
        'cancel_cctv': cancel_cctv,
        'cctv_apps': cctv_apps_list,
        'open_translate_hud': open_translate_hud,
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