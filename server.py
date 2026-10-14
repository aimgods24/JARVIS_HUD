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
from bs4 import BeautifulSoup

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

EVAS_BUILD_VERSION = "6.6.0-DIRECT-GOOGLE-ENGINE"

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

def perform_direct_google_search(query):
    """Directly queries Google search endpoints and extracts paragraph text without an API key."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    encoded_query = urllib.parse.quote(query)
    google_url = f"https://www.google.com/search?q={encoded_query}&hl=en"
    
    extracted_data = []
    try:
        response = requests.get(google_url, headers=headers, timeout=5)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Extract standard Google snippet containers
            snippets = soup.find_all(['div', 'span'], class_=re.compile(r'(VwiC3b|yXMda|MUxGv|Hg231c)'))
            for s in snippets:
                txt = s.get_text().strip()
                if len(txt) > 30 and txt not in extracted_data:
                    extracted_data.append(txt)
                    
            if not extracted_data:
                paragraphs = soup.find_all('p')
                for p in paragraphs:
                    txt = p.get_text().strip()
                    if len(txt) > 30:
                        extracted_data.append(txt)
                        
        if extracted_data:
            return "\n\n".join(extracted_data[:4])
    except Exception as e:
        print(f"[GOOGLE SEARCH ENGINE WARNING]: {e}")
    return None

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

    voice_pitch = data.get('voice_pitch', '-3Hz')
    voice_rate = data.get('voice_rate', '+2%')
    smooth_punct = data.get('smooth_punct', True)

    if not user_prompt:
        return jsonify({'response': f'No command received, {honorific}.', 'audio': False})

    cmd_lower = user_prompt.lower()
    inferred_intent = parse_contextual_intent(user_prompt)
    reply = None
    reasoning_steps = None

    if inferred_intent == "TOGGLE_STUDY_MODE_ON":
        reply = f"🎓 **STUDY MODE ACTIVATED**. Google Search integration enabled."

    elif inferred_intent == "TOGGLE_STUDY_MODE_OFF":
        reply = f"🎓 **STUDY MODE DISABLED**."

    elif inferred_intent == "STUDY_ASSISTANT":
        # Direct Google search retrieval
        google_context = perform_direct_google_search(user_prompt)

        teacher_prompt = (
            "You are E.V.A.S. Study Companion. Use the retrieved Google search telemetry below to generate clear, patient classroom-style explanations or notes in BBC Bitesize format. "
            "Never display raw HTML or code snippets."
        )

        if HAS_OLLAMA:
            try:
                prompt_content = f"Question: {user_prompt}\n\nGoogle Search Data:\n{google_context if google_context else 'No extra search context found.'}"
                response = ollama.chat(
                    model='deepseek-r1:1.5b',
                    messages=[{"role": "system", "content": teacher_prompt}, {"role": "user", "content": prompt_content}],
                    options={"num_predict": 1000, "temperature": 0.2}
                )
                raw_reply = response['message']['content'].strip()
                if "<think>" in raw_reply and "</think>" in raw_reply:
                    reply = re.sub(r'<think>[\s\S]*?</think>', '', raw_reply).strip()
                else:
                    reply = raw_reply
            except Exception:
                reply = None

        if not reply:
            if google_context:
                reply = f"### 🌐 GOOGLE SEARCH RESULTS:\n\n{google_context}"
            else:
                reply = f"Processed request: {user_prompt}"

    if not reply:
        google_context = perform_direct_google_search(user_prompt)
        reply = google_context if google_context else f"Processed request: {user_prompt}"

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
        'study_mode_active': IS_STUDY_MODE_ACTIVE,
        'audio': has_audio
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