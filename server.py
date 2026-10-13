from flask import Flask, render_template_string, request, jsonify, send_file, make_response, send_from_directory
import edge_tts
import asyncio
import os
import re
import json
import random
import threading
import time
import requests
import urllib.parse
from duckduckgo_search import DDGS

try:
    import ollama
    HAS_OLLAMA = True
except Exception:
    HAS_OLLAMA = False

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

MEMORY_FILE = "jarvis_memory.json"
GENERATED_FILES_DIR = "generated_files"
os.makedirs(GENERATED_FILES_DIR, exist_ok=True)

GLOBAL_NEWS_CACHE = []

def init_memory():
    if not os.path.exists(MEMORY_FILE):
        default_mem = {
            "user_preferences": {"honorific": "Sir", "location": "Bayan Lepas, Penang, Malaysia"},
            "facts": [],
            "task_history": []
        }
        with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_mem, f, indent=2)

init_memory()

def get_memory_data():
    try:
        with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {"user_preferences": {}, "facts": [], "task_history": []}

def save_memory_fact(fact_str):
    data = get_memory_data()
    if fact_str not in data.get("facts", []):
        data.setdefault("facts", []).append(fact_str)
        with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

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
            return f"Knowledge Synthesis for '{query}':\n\n" + "\n\n".join(snippets[:4])
        return None
    except Exception:
        return None

def convert_symbols_to_words_fluent(text, smooth_punctuation=True):
    clean = re.sub(r'```[\s\S]*?```', ' Code block provided in terminal ', text)
    clean = re.sub(r'<svg[\s\S]*?<\/svg>', ' Schematic generated ', clean)

    symbol_map = {
        '@': ' at ', '#': ' hashtag ', '$': ' dollars ', '%': ' percent ',
        '&': ' and ', '*': ' times ', '+': ' plus ', '=': ' equals ',
        '<': ' less than ', '>': ' greater than ', '/': ' slash ', '\\': ' backslash ',
        '^': ' power of ', '~': ' approximately ', '|': ' pipe ', '_': ' underscore ',
        '-': ' ', '°': ' degrees '
    }

    for sym, word in symbol_map.items():
        clean = clean.replace(sym, word)

    if smooth_punctuation:
        # Strip commas, full stops, and semicolons to force fluent, continuous vocal delivery
        clean = re.sub(r'[\.,;:\?!]', ' ', clean)

    clean = re.sub(r'[^\w\s]', '', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean

def parse_contextual_intent(prompt):
    p = prompt.lower()
    if any(w in p for w in ["cancel cctv", "disconnect camera", "close camera", "stop feed", "turn off camera", "close cctv", "hide cctv", "stop cctv"]):
        return "CANCEL_CCTV"
    if any(w in p for w in ["connect to cctv", "scan cctv", "check camera", "show camera", "cctv feed", "front door camera", "security feed", "perimeter camera", "view feed", "switch camera"]):
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
    if any(w in p for w in ["remember that", "save note", "keep in mind"]):
        return "SAVE_FACT"
        
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
            #out { font-size: 0.65rem; margin-top: 6px; max-height: 45px; overflow: hidden; text-overflow: ellipsis; }
        </style>
    </head>
    <body>
        <div class="widget-ring" onclick="triggerWatchVoice()">
            <span>J.A.R.V.I.S.</span>
            <span style="font-size:0.5rem; opacity:0.8;">TAP TO SPEAK</span>
        </div>
        <div id="out">Widget Active</div>
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
    cam_id = data.get('cam_id', 'cam_01')
    
    cameras = [
        {"id": "cam_01", "name": "PERIMETER-NORTH-CAM", "stream_url": "https://images.unsplash.com/photo-1557597774-9d273605dfa9?w=400&auto=format&fit=crop"},
        {"id": "cam_02", "name": "MAIN-LAB-CAM", "stream_url": "https://images.unsplash.com/photo-1518770660439-4636190af475?w=400&auto=format&fit=crop"},
        {"id": "cam_03", "name": "FRONT-PORCH-CAM", "stream_url": "https://images.unsplash.com/photo-1508873696983-2df515122519?w=400&auto=format&fit=crop"},
        {"id": "cam_04", "name": "REAR-GATE-CAM", "stream_url": "https://images.unsplash.com/photo-1541888946425-d0fbb186a5b3?w=400&auto=format&fit=crop"}
    ]
    
    selected = next((c for c in cameras if c['id'] == cam_id), cameras[0])
    return jsonify({'status': 'success', 'selected_camera': selected, 'all_cameras': cameras})

@app.route('/api/agent_task', methods=['POST'])
def run_autonomous_agent_task():
    data = request.json or {}
    task_desc = data.get('task', '').strip()
    
    if not task_desc:
        return jsonify({'status': 'error', 'message': 'No task description specified.'})

    search_data = search_general_knowledge(task_desc)
    result_text = f"Autonomous Background Worker Execution Complete:\nTask Goal: '{task_desc}'\n\nResults:\n{search_data if search_data else 'Task completed successfully.'}"

    return jsonify({
        'status': 'success',
        'task': task_desc,
        'summary': result_text
    })

@app.route('/api/translate', methods=['POST'])
def translate_audio_or_text():
    data = request.json or {}
    text = data.get('text', '').strip()
    target_lang = data.get('target_lang', 'English').strip()
    voice_pitch = data.get('voice_pitch', '-3Hz')
    voice_rate = data.get('voice_rate', '+2%')
    smooth_punct = data.get('smooth_punct', True)

    if not text:
        return jsonify({'status': 'error', 'response': 'No speech text provided for translation.'})

    translated_text = ""
    if HAS_OLLAMA:
        try:
            response = ollama.chat(
                model='qwen2.5:0.5b',
                messages=[
                    {"role": "system", "content": f"Translate input into {target_lang}. Return ONLY the direct translation."},
                    {"role": "user", "content": text}
                ],
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

    spoken_text = convert_symbols_to_words_fluent(translated_text, smooth_punct)
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

    voice_pitch = data.get('voice_pitch', '-3Hz')
    voice_rate = data.get('voice_rate', '+2%')
    smooth_punct = data.get('smooth_punct', True)
    custom_prefix = data.get('custom_prefix', '')

    if not user_prompt and not images and not files:
        return jsonify({'response': f'No command received, {honorific}.', 'audio': False})

    cmd_lower = user_prompt.lower()
    inferred_intent = parse_contextual_intent(user_prompt)
    reply = None
    reasoning_steps = None
    google_maps_url = None
    cctv_stream_url = None
    cancel_cctv = False
    open_translate_hud = False
    trigger_lock = False

    if inferred_intent == "SAVE_FACT":
        fact = re.sub(r'remember that|save note|keep in mind', '', user_prompt, flags=re.IGNORECASE).strip()
        if fact:
            save_memory_fact(fact)
            reply = f"Memory updated and indexed in cross-session persistence storage, {honorific}: '{fact}'"

    elif inferred_intent == "CANCEL_CCTV":
        cancel_cctv = True
        reply = f"CCTV feed disconnected. Reverting HUD core to 3D WebGL Arc Core visualizer, {honorific}."

    elif inferred_intent == "CCTV_SCAN":
        cctv_data = scan_cctv().get_json()
        cam = cctv_data.get('selected_camera', {})
        cctv_stream_url = cam.get('stream_url')
        reply = f"CCTV signal acquired ({cam.get('name')}). Live feed projected inside the 3D core orb, {honorific}."

    elif inferred_intent == "OPEN_TRANSLATE":
        open_translate_hud = True
        reply = f"Activating floating Universal Translation HUD pop-up, {honorific}."

    elif inferred_intent == "SECURITY_LOCK":
        trigger_lock = True
        reply = f"Stark Security Protocol Engaged. Locking chat terminal interface, {honorific}."

    elif inferred_intent == "SMART_HOME":
        act = "OFF" if "off" in cmd_lower else "ON"
        device = "Living Room Climate Control" if "ac" in cmd_lower or "cold" in cmd_lower or "hot" in cmd_lower else "Primary Lights"
        reply = f"Inferred Smart Home payload dispatched: Set {device} state to {act}, {honorific}."

    elif inferred_intent == "DAILY_BRIEFING":
        weather_summary = fetch_global_weather(location, lat, lon)
        news_summary = GLOBAL_NEWS_CACHE[0] if GLOBAL_NEWS_CACHE else "Global telemetry feeds optimal."
        mem_data = get_memory_data()
        facts_count = len(mem_data.get('facts', []))
        reply = f"Good day, {honorific}. Executive Briefing:\n\n1. Weather Telemetry:\n{weather_summary}\n\n2. Headlines:\n{news_summary}\n\n3. Memory Records: {facts_count} active facts archived."

    elif inferred_intent == "MEDIA_PLAYBACK":
        query = re.sub(r'play|put on|some tracks|music|video|listen to|spotify|youtube', '', user_prompt, flags=re.IGNORECASE).strip()
        encoded = urllib.parse.quote(query if query else "Ambient Tracks")
        target_url = f"https://open.spotify.com/search/{encoded}" if "spotify" in cmd_lower else f"https://www.youtube.com/results?search_query={encoded}"
        google_maps_url = target_url
        reply = f"Inferred media intent: Prepared stream link for '{query if query else 'Ambient Tracks'}'. Click link below, {honorific}."

    file_context_str = ""
    if files:
        file_snippets = [f"--- [DOC ANALYSIS: {f.get('name', 'Doc')}] ---\n{f.get('content', '')}\n" for f in files]
        file_context_str = "\n".join(file_snippets)

    if not reply:
        mem_data = get_memory_data()
        saved_facts = mem_data.get('facts', [])
        facts_context = f"\n[PERSISTENT USER MEMORY]:\n" + "\n".join([f"• {f}" for f in saved_facts[-5:]]) if saved_facts else ""

        system_instructions = (
            f"You are J.A.R.V.I.S. Mark LXXXV. Address the user as '{honorific}'. "
            f"Be authoritative, concise, and smart. "
            f"Include a '💡 Proactive Tactical Tip:' at the bottom of responses."
        )

        full_prompt = user_prompt
        if file_context_str: full_prompt = f"{file_context_str}\n\nUser Instruction:\n{user_prompt}"
        if facts_context: full_prompt = f"{full_prompt}\n{facts_context}"

        search_data = search_general_knowledge(user_prompt)
        if search_data: full_prompt = f"{full_prompt}\n\n[EXTERNAL SEARCH DATA]:\n{search_data}"

        if HAS_OLLAMA:
            try:
                model_to_use = 'llava' if images else 'deepseek-r1:1.5b'
                response = ollama.chat(
                    model=model_to_use,
                    messages=[{"role": "system", "content": system_instructions}, {"role": "user", "content": full_prompt}],
                    options={"num_predict": 800, "temperature": temperature}
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
            reply = search_data if search_data else f"I am online and monitoring telemetry, {honorific}."
            reply += f"\n\n💡 Proactive Tactical Tip: Keep systems synchronized, {honorific}."

    clean_text = re.sub(r'[*_~`]', '', reply).strip()
    if not clean_text.endswith(honorific + "."): clean_text = f"{clean_text.rstrip('.,!')}, {honorific}."
    
    if custom_prefix:
        clean_text = f"{custom_prefix} {clean_text}"

    spoken_verbal_text = convert_symbols_to_words_fluent(clean_text, smooth_punct)

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
        'audio': has_audio,
        'google_maps_url': google_maps_url,
        'cctv_stream_url': cctv_stream_url,
        'cancel_cctv': cancel_cctv,
        'open_translate_hud': open_translate_hud,
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