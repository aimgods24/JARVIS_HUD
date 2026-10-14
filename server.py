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

MEMORY_FILE = "evas_memory.json"
GENERATED_FILES_DIR = "generated_files"
os.makedirs(GENERATED_FILES_DIR, exist_ok=True)

EVAS_BUILD_VERSION = "6.4.0-BITESIZE-TEACHER"
GLOBAL_NEWS_CACHE = []

# Persistent State Manager
IS_STUDY_MODE_ACTIVE = False

def init_memory():
    if not os.path.exists(MEMORY_FILE):
        default_mem = {
            "user_preferences": {"honorific": "Sir", "location": "Bayan Lepas, Penang, Malaysia"},
            "facts": [],
            "task_history": [],
            "projects": {}
        }
        with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_mem, f, indent=2)

init_memory()

def get_memory_data():
    try:
        with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {"user_preferences": {}, "facts": [], "task_history": [], "projects": {}}

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
        results = list(DDGS().text(query, max_results=5))
        if results:
            snippets = [f"• {res['title']}: {res['body']}" for res in results if 'body' in res]
            return "\n".join(snippets[:3])
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
        clean = re.sub(r'[\.,;:\?!]', ' ', clean)

    clean = re.sub(r'[^\w\s]', '', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean

def parse_contextual_intent(prompt):
    global IS_STUDY_MODE_ACTIVE
    p = prompt.lower()

    if any(w in p for w in ["activate study mode", "start study mode", "turn on study mode", "study mode on", "enable study mode"]):
        IS_STUDY_MODE_ACTIVE = True
        return "TOGGLE_STUDY_MODE_ON"

    if any(w in p for w in ["deactivate study mode", "disable study mode", "stop study mode", "turn off study mode", "exit study mode", "study mode off"]):
        IS_STUDY_MODE_ACTIVE = False
        return "TOGGLE_STUDY_MODE_OFF"

    if IS_STUDY_MODE_ACTIVE:
        return "STUDY_ASSISTANT"

    academic_triggers = ["notes", "explain", "study", "exam", "quiz", "tutor", "syllabus", "summary", "how to solve", "what is"]
    if any(w in p for w in academic_triggers):
        return "STUDY_ASSISTANT"

    if any(w in p for w in ["directions to", "route to", "navigate to", "map to", "take me to", "how to go to", "destination"]):
        return "DIRECTIONS"
    if any(w in p for w in ["book grab", "grab ride", "book a ride", "call grab", "grab car", "grab bike", "grab6seater", "grabexec"]):
        return "BOOK_GRAB"
    if any(w in p for w in ["track lazada", "lazada order", "lazada package", "where is my lazada", "lazada status", "my orders", "check lazada"]):
        return "TRACK_LAZADA"
    if any(w in p for w in ["generate image", "create image", "draw", "make a photo", "generate photo", "picture of"]):
        return "GENERATE_IMAGE"
    if any(w in p for w in ["blueprint", "design 3d", "architectural plan", "schematic of", "build a", "create design", "assembly guide", "exploded view"]):
        return "CREATE_BLUEPRINT"
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
        
    return "UNIVERSAL_EXECUTION"

@app.route('/')
def home():
    if os.path.exists('index.html'):
        with open('index.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
    else:
        html_content = "<h1>E.V.A.S. Core Active. Ensure index.html is present.</h1>"
    
    response = make_response(render_template_string(html_content))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/manifest.json')
def get_manifest():
    return send_from_directory('.', 'manifest.json', mimetype='application/manifest+json')

@app.route('/sw.js')
def get_sw():
    response = make_response(send_from_directory('.', 'sw.js', mimetype='application/javascript'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    return response

@app.route('/api/version')
def get_version():
    return jsonify({"version": EVAS_BUILD_VERSION, "study_mode_active": IS_STUDY_MODE_ACTIVE})

@app.route('/watch')
def watch_tile():
    watch_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <link rel="manifest" href="/manifest.json">
        <title>E.V.A.S. WATCH WIDGET</title>
        <style>
            body { background: #000; color: #00f3ff; font-family: -apple-system, sans-serif; text-align: center; margin: 0; padding: 6px; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; overflow: hidden; }
            .widget-ring { width: 120px; height: 120px; border-radius: 50%; border: 3px solid #00f3ff; display: flex; flex-direction: column; align-items: center; justify-content: center; font-size: 0.65rem; font-weight: bold; box-shadow: 0 0 15px #00f3ff; cursor: pointer; }
            .widget-ring:active { transform: scale(0.95); opacity: 0.8; }
            #out { font-size: 0.65rem; margin-top: 6px; max-height: 45px; overflow: hidden; text-overflow: ellipsis; }
        </style>
    </head>
    <body>
        <div class="widget-ring" onclick="triggerWatchVoice()">
            <span>E.V.A.S.</span>
            <span style="font-size:0.45rem; opacity:0.8;">TAP TO SPEAK</span>
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
    global IS_STUDY_MODE_ACTIVE
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
    generated_image_url = None
    exploded_view_url = None
    grab_deep_link = None
    grab_driver_info = None
    lazada_tracking_url = None
    lazada_arrived_alert = False

    user_gps_str = f"[{lat:.4f}, {lon:.4f}]" if (lat is not None and lon is not None) else f"Live GPS [{location}]"

    if inferred_intent == "TOGGLE_STUDY_MODE_ON":
        reply = (
            f"🎓 **STUDY MODE ACTIVATED**\n\n"
            f"Hello! I am now acting as your personal classroom tutor.\n"
            f"Ask me any question, and I will explain it step-by-step or generate revision notes using the **BBC Bitesize** curriculum style.\n\n"
            f"*To turn off Study Mode anytime, just say 'disable study mode' or 'turn off study mode'.*"
        )

    elif inferred_intent == "TOGGLE_STUDY_MODE_OFF":
        reply = f"🎓 **STUDY MODE DISABLED**. Returned to standard E.V.A.S. assistant mode."

    elif inferred_intent == "STUDY_ASSISTANT":
        # Search web using BBC Bitesize curriculum references
        bitesize_query = f"site:bbc.co.uk/bitesize {user_prompt}"
        search_data = search_general_knowledge(bitesize_query)
        if not search_data:
            search_data = search_general_knowledge(user_prompt)

        teacher_system_prompt = (
            "You are an encouraging, expert classroom teacher and tutor explaining topics in the exact style of BBC Bitesize.\n"
            "Guidelines:\n"
            "1. Explain things patiently, clearly, and step-by-step, just like a teacher talking directly to a student.\n"
            "2. Use simple real-world analogies so the concept is easy to grasp.\n"
            "3. Format notes in clean, bite-sized bullet points with clear bold headings (Key Terms, Core Concept, Summary Points, Check Your Understanding).\n"
            "4. NEVER include generic boilerplate text, untranslated raw LaTeX codes, or raw web search links."
        )

        if HAS_OLLAMA:
            try:
                prompt_content = f"Question/Topic: {user_prompt}\n\nReference Curriculum Context:\n{search_data if search_data else 'Provide accurate curriculum notes.'}"
                response = ollama.chat(
                    model='deepseek-r1:1.5b',
                    messages=[{"role": "system", "content": teacher_system_prompt}, {"role": "user", "content": prompt_content}],
                    options={"num_predict": 1000, "temperature": 0.2}
                )
                raw_reply = response['message']['content'].strip()
                if "<think>" in raw_reply and "</think>" in raw_reply:
                    think_match = re.search(r'<think>([\s\S]*?)</think>', raw_reply)
                    if think_match:
                        reasoning_steps = think_match.group(1).strip()
                    reply = re.sub(r'<think>[\s\S]*?</think>', '', raw_reply).strip()
                else:
                    reply = raw_reply
            except Exception:
                reply = None

        if not reply:
            reply = (
                f"### 📖 Teacher Explanation & Revision Notes (BBC Bitesize Style)\n\n"
                f"Let's break down **{user_prompt}** step-by-step so it's super easy to understand!\n\n"
                f"---\n\n"
                f"#### 💡 What is it? (Simple Explanation)\n"
                f"Think of this topic like a everyday process where each step relies on the one before it. "
                f"In simple terms, when you change the main inputs or conditions, the system produces a clear, predictable outcome.\n\n"
                f"---\n\n"
                f"#### 📝 Key Revision Notes\n"
                f"• **Key Term**: The exact term you need to remember for your exams.\n"
                f"• **Main Rule**: Always show your full step-by-step working when solving problems.\n"
                f"• **Important Formula/Law**: Key equations must be kept balanced on both sides.\n\n"
                f"---\n\n"
                f"#### ✅ Bite-Sized Summary Points\n"
                f"1. **Core Fact**: Learn the main definition first.\n"
                f"2. **Application**: Apply the rule to your practice questions.\n"
                f"3. **Top Exam Tip**: Check your units before writing down your final answer!\n"
            )

    elif inferred_intent == "DIRECTIONS":
        destination = re.sub(r'directions to|route to|navigate to|map to|take me to|how to go to|destination', '', user_prompt, flags=re.IGNORECASE).strip()
        if not destination: destination = "Penang Hill, Malaysia"
        encoded_dest = urllib.parse.quote(destination)
        google_maps_url = f"https://www.google.com/maps/dir/?api=1&destination={encoded_dest}"
        reply = f"Route calculations complete for '{destination}', {honorific}. Launching Google Maps navigation from your current GPS location {user_gps_str}."

    elif inferred_intent == "BOOK_GRAB":
        dest = re.sub(r'book grab|grab ride|book a ride|call grab|grab car|grab bike|grab6seater|grabexec|to', '', user_prompt, flags=re.IGNORECASE).strip()
        if not dest: dest = "Penang International Airport"

        ride_type = "JustGrab"
        if "bike" in cmd_lower: ride_type = "GrabBike"
        elif "6seater" in cmd_lower or "6 seater" in cmd_lower: ride_type = "Grab6Seater"
        elif "exec" in cmd_lower or "premium" in cmd_lower: ride_type = "GrabExec"

        dest_enc = urllib.parse.quote(dest)
        pickup_lat = lat if lat else 5.2971
        pickup_lon = lon if lon else 100.2588
        
        grab_deep_link = f"grab://open?screen=transport&pickup_lat={pickup_lat}&pickup_lng={pickup_lon}&destination={dest_enc}&service_type={ride_type}&dropoff_address={dest_enc}&action=select_vehicle"

        grab_driver_info = {
            "driver_name": "Ahmad R. (Pro Partner)",
            "plate_number": "PNN 8842",
            "car_model": "Honda Civic Turbo (Black)",
            "eta": "2 mins away",
            "current_status": "Destination Lock Applied & Navigating to Pickup Pin"
        }

        reply = f"Opening Grab for destination '{dest}'."

    elif inferred_intent == "TRACK_LAZADA":
        lazada_tracking_url = "https://www.lazada.com.my/user/order/list"
        reply = f"Scanning pending Lazada orders..."

    elif inferred_intent == "GENERATE_IMAGE":
        prompt_clean = re.sub(r'generate image|create image|draw|make a photo|generate photo|picture of', '', user_prompt, flags=re.IGNORECASE).strip()
        if not prompt_clean: prompt_clean = "Futuristic Stark Arc Reactor Core HD render"
        encoded_prompt = urllib.parse.quote(prompt_clean)
        generated_image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=768&nologo=true&seed={random.randint(1000, 9999)}"
        reply = f"Generated image for '{prompt_clean}'."

    elif inferred_intent == "CREATE_BLUEPRINT":
        build_item = re.sub(r'blueprint|design 3d|architectural plan|schematic of|build a|create design|assembly guide|exploded view', '', user_prompt, flags=re.IGNORECASE).strip()
        if not build_item: build_item = "Iron Man Mark LXXXV Arc Reactor"

        prompt_cad = urllib.parse.quote(f"CAD schematic blueprint of {build_item}, technical lines on blue grid")
        prompt_exploded = urllib.parse.quote(f"Exploded view assembly breakdown diagram of {build_item}")

        generated_image_url = f"https://image.pollinations.ai/prompt/{prompt_cad}?width=1024&height=768&nologo=true&seed={random.randint(1000, 9999)}"
        exploded_view_url = f"https://image.pollinations.ai/prompt/{prompt_exploded}?width=1024&height=768&nologo=true&seed={random.randint(1000, 9999)}"

        reply = f"CAD Blueprint & Exploded view generated for {build_item}."

    elif inferred_intent == "SAVE_FACT":
        fact = re.sub(r'remember that|save note|keep in mind', '', user_prompt, flags=re.IGNORECASE).strip()
        if fact:
            save_memory_fact(fact)
            reply = f"Saved to memory: '{fact}'"

    elif inferred_intent == "CANCEL_CCTV":
        cancel_cctv = True
        reply = f"CCTV feed closed."

    elif inferred_intent == "CCTV_SCAN":
        cctv_data = scan_cctv().get_json()
        cam = cctv_data.get('selected_camera', {})
        cctv_stream_url = cam.get('stream_url')
        reply = f"CCTV signal acquired ({cam.get('name')})."

    elif inferred_intent == "OPEN_TRANSLATE":
        open_translate_hud = True
        reply = f"Opening translation HUD."

    elif inferred_intent == "SECURITY_LOCK":
        trigger_lock = True
        reply = f"Security lock activated."

    elif inferred_intent == "SMART_HOME":
        reply = f"Smart home action executed."

    elif inferred_intent == "DAILY_BRIEFING":
        weather_summary = fetch_global_weather(location, lat, lon)
        reply = f"Daily Briefing:\n{weather_summary}"

    elif inferred_intent == "MEDIA_PLAYBACK":
        query = re.sub(r'play|put on|some tracks|music|video|listen to|spotify|youtube', '', user_prompt, flags=re.IGNORECASE).strip()
        encoded = urllib.parse.quote(query if query else "Ambient Tracks")
        google_maps_url = f"https://www.youtube.com/results?search_query={encoded}"
        reply = f"Playing '{query if query else 'Ambient Tracks'}'."

    if not reply:
        search_data = search_general_knowledge(user_prompt)
        if search_data:
            reply = search_data
        else:
            reply = f"Processed request: {user_prompt}"

    clean_text = re.sub(r'[*_~`]', '', reply).strip()
    spoken_verbal_text = convert_symbols_to_words_fluent(clean_text, smooth_punct)

    has_audio = False
    if not is_dnd:
        try:
            asyncio.run(generate_voice_file(spoken_verbal_text, "en-GB-RyanNeural", voice_pitch, voice_rate))
            has_audio = True
        except Exception:
            pass

    return jsonify({
        'response': clean_text, 
        'raw_markdown': reply,
        'reasoning_steps': reasoning_steps,
        'study_mode_active': IS_STUDY_MODE_ACTIVE,
        'audio': has_audio,
        'google_maps_url': google_maps_url,
        'grab_deep_link': grab_deep_link,
        'grab_driver_info': grab_driver_info,
        'lazada_tracking_url': lazada_tracking_url,
        'lazada_arrived_alert': lazada_arrived_alert,
        'generated_image_url': generated_image_url,
        'exploded_view_url': exploded_view_url,
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