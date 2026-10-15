from flask import Flask, render_template_string, request, jsonify, send_file, make_response, send_from_directory
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
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except Exception:
    HAS_BS4 = False

try:
    import edge_tts
    import asyncio
    HAS_EDGE_TTS = True
except Exception:
    HAS_EDGE_TTS = False

try:
    import ollama
    HAS_OLLAMA = True
except Exception:
    HAS_OLLAMA = False

try:
    import speedtest
    HAS_SPEEDTEST = True
except Exception:
    HAS_SPEEDTEST = False

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

MEMORY_FILE = "evas_memory.json"
GENERATED_FILES_DIR = "generated_files"
os.makedirs(GENERATED_FILES_DIR, exist_ok=True)

EVAS_BUILD_VERSION = "12.0.0-SPEEDTEST-CORE"

# ---------------------------------------------------------
# ENVIRONMENT SECURITY & CONFIGURATION
# ---------------------------------------------------------
MACRODROID_DEVICE_ID = os.environ.get("MACRODROID_DEVICE_ID", "YOUR_MACRODROID_DEVICE_ID_HERE")
EVAS_SECRET_KEY = os.environ.get("EVAS_SECRET_KEY", "DefaultSecureKey123")

DEFAULT_CONTACTS = {
    "mom": "+60123456789",
    "dad": "+60198765432",
    "emergency": "999",
    "office": "+6046543210"
}

try:
    CONTACTS = json.loads(os.environ.get("EVAS_CONTACTS", "{}")) or DEFAULT_CONTACTS
except Exception:
    CONTACTS = DEFAULT_CONTACTS

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

# ---------------------------------------------------------
# NETWORK DIAGNOSTICS TELEMETRY ENGINE
# ---------------------------------------------------------
def run_network_speedtest():
    """Performs live speed test measuring download, upload, and latency."""
    if not HAS_SPEEDTEST:
        return "⚠️ Speedtest module not available. Install 'speedtest-cli' in requirements.txt."
    
    try:
        st = speedtest.Speedtest(secure=True)
        st.get_best_server()
        
        download_bps = st.download()
        upload_bps = st.upload()
        ping_ms = st.results.ping
        
        download_mbps = download_bps / 1000000.0
        upload_mbps = upload_bps / 1000000.0
        
        server_info = st.results.server.get('sponsor', 'Unknown')
        server_location = st.results.server.get('name', 'Unknown')
        
        return (
            f"⚡ **LIVE NETWORK DIAGNOSTIC REPORT**\n\n"
            f"• **Download Speed**: `{download_mbps:.2f} Mbps`\n"
            f"• **Upload Speed**: `{upload_mbps:.2f} Mbps`\n"
            f"• **Latency / Ping**: `{ping_ms:.1f} ms`\n"
            f"• **Test Node Server**: `{server_info}` ({server_location})\n"
            f"• **Status**: Connection operational."
        )
    except Exception as e:
        print(f"[SPEEDTEST ERROR]: {e}")
        return f"Failed to execute network diagnostic test: {str(e)}"

# ---------------------------------------------------------
# MACRODROID WEBHOOK DISPATCHER
# ---------------------------------------------------------
def dispatch_macrodroid_command(action_name, target_param=""):
    if not MACRODROID_DEVICE_ID or MACRODROID_DEVICE_ID == "YOUR_MACRODROID_DEVICE_ID_HERE":
        print("[MACRODROID WARNING]: Device ID not set in environment variables.")
        return False
        
    encoded_target = urllib.parse.quote(target_param)
    webhook_url = f"https://trigger.macrodroid.com/{MACRODROID_DEVICE_ID}/evas_command?action={action_name}&target={encoded_target}"
    
    try:
        res = requests.get(webhook_url, timeout=4)
        return res.status_code == 200
    except Exception as e:
        print(f"[MACRODROID HTTP ERROR]: {e}")
        return False

# ---------------------------------------------------------
# LIVE SEARCH & WEATHER TELEMETRY ENGINES
# ---------------------------------------------------------
def perform_live_web_search(query):
    extracted_data = []

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    encoded_query = urllib.parse.quote(query)
    google_url = f"https://www.google.com/search?q={encoded_query}&hl=en"
    
    try:
        response = requests.get(google_url, headers=headers, timeout=4)
        if response.status_code == 200 and HAS_BS4:
            soup = BeautifulSoup(response.text, "html.parser")
            snippets = soup.find_all(['div', 'span'], class_=re.compile(r'(VwiC3b|yXMda|MUxGv|Hg231c)'))
            for s in snippets:
                txt = s.get_text().strip()
                if len(txt) > 30 and txt not in extracted_data:
                    extracted_data.append(txt)
            if not extracted_data:
                for p in soup.find_all('p'):
                    txt = p.get_text().strip()
                    if len(txt) > 30 and txt not in extracted_data:
                        extracted_data.append(txt)
    except Exception:
        pass

    if not extracted_data:
        try:
            with DDGS() as ddgs:
                ddg_results = list(ddgs.text(query, max_results=5))
                if ddg_results:
                    for res in ddg_results:
                        if 'body' in res and res['body']:
                            extracted_data.append(f"**{res.get('title', 'Result')}**\n{res['body']}")
        except Exception as e:
            print(f"[SEARCH FALLBACK LOG]: {e}")

    if extracted_data:
        return "\n\n".join(extracted_data[:4])
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

# ---------------------------------------------------------
# INTENT PARSER
# ---------------------------------------------------------
def parse_contextual_intent(prompt):
    p = prompt.lower()

    if any(w in p for w in ["speed test", "test speed", "wifi speed", "internet speed", "bandwidth test", "connection speed"]):
        return "RUN_SPEEDTEST"
    if any(w in p for w in ["open app", "launch app", "open whatsapp", "open spotify", "open youtube", "open instagram", "open tiktok", "open facebook"]):
        return "MACRODROID_APP_CONTROL"
    if any(w in p for w in ["call", "dial", "phone", "ring"]):
        return "MAKE_CALL"
    if any(w in p for w in ["incoming call", "simulate call", "trigger ring"]):
        return "SIMULATE_INCOMING_CALL"
    if any(w in p for w in ["directions to", "route to", "navigate to", "map to", "maps to", "take me to", "how to go to", "go to", "destination"]):
        return "DIRECTIONS"
    if any(w in p for w in ["book grab", "grab ride", "book a ride", "call grab", "grab car", "grab bike", "grab6seater", "grabexec"]):
        return "BOOK_GRAB"
    if any(w in p for w in ["track lazada", "lazada order", "lazada package", "where is my lazada", "lazada status", "my orders", "check lazada"]):
        return "TRACK_LAZADA"
    if any(w in p for w in ["generate image", "create image", "draw", "make a photo", "generate photo", "picture of"]):
        return "GENERATE_IMAGE"
    if any(w in p for w in ["blueprint", "design 3d", "architectural plan", "schematic of", "build a", "create design", "assembly guide", "exploded view"]):
        return "CREATE_BLUEPRINT"
    if any(w in p for w in ["weather", "temperature", "forecast", "how hot", "how cold"]):
        return "WEATHER"
    if any(w in p for w in ["remember that", "save note", "keep in mind"]):
        return "SAVE_FACT"

    return "UNIVERSAL_EXECUTION"

# ---------------------------------------------------------
# ROUTES
# ---------------------------------------------------------
@app.route('/')
def home():
    if os.path.exists('index.html'):
        with open('index.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
    else:
        html_content = "<h1>E.V.A.S. Core Active. Upload index.html to view complete HUD.</h1>"
    
    response = make_response(render_template_string(html_content))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    return response

@app.route('/manifest.json')
def get_manifest():
    return send_from_directory('.', 'manifest.json', mimetype='application/manifest+json')

@app.route('/sw.js')
def get_sw():
    return send_from_directory('.', 'sw.js', mimetype='application/javascript')

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
                        headers: {
                            'Content-Type': 'application/json',
                            'X-EVAS-KEY': 'DefaultSecureKey123'
                        },
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

@app.route('/api/version')
def get_version():
    return jsonify({"version": EVAS_BUILD_VERSION})

@app.route('/api/ask', methods=['POST'])
def ask():
    data = request.json or {}
    provided_key = request.headers.get("X-EVAS-KEY") or data.get("secret_key")
    
    if EVAS_SECRET_KEY and provided_key != EVAS_SECRET_KEY:
        return jsonify({'response': '🔒 Unauthorized access blocked. Invalid Secret Key.', 'audio': False}), 403

    user_prompt = data.get('prompt', '').strip()
    honorific = data.get('honorific', 'Sir')
    location = data.get('location', 'Bayan Lepas, Penang, Malaysia')
    lat = data.get('latitude', None)
    lon = data.get('longitude', None)
    is_dnd = data.get('dnd_mode', False)

    if not user_prompt:
        return jsonify({'response': f'No command received, {honorific}.', 'audio': False})

    inferred_intent = parse_contextual_intent(user_prompt)
    reply = None
    call_phone_number = None
    incoming_call_event = None
    google_maps_url = None
    cctv_stream_url = None
    cancel_cctv = False
    open_translate_hud = False
    generated_image_url = None
    exploded_view_url = None
    grab_deep_link = None
    lazada_tracking_url = None

    if inferred_intent == "RUN_SPEEDTEST":
        reply = run_network_speedtest()

    elif inferred_intent == "MACRODROID_APP_CONTROL":
        target_app = re.sub(r'open app|launch app|open|launch', '', user_prompt, flags=re.IGNORECASE).strip()
        if not target_app: target_app = "whatsapp"
        
        success = dispatch_macrodroid_command("launch_app", target_app)
        if success:
            reply = f"📱 **SECURE MACRODROID DISPATCH**: Launching `{target_app.upper()}` on your phone, {honorific}."
        else:
            reply = f"⚠️ MacroDroid command sent for `{target_app.upper()}`. Ensure `MACRODROID_DEVICE_ID` is set in Render Environment Variables, {honorific}."

    elif inferred_intent == "MAKE_CALL":
        target = re.sub(r'call|dial|phone|ring', '', user_prompt, flags=re.IGNORECASE).strip().lower()
        phone_num = CONTACTS.get(target)
        if not phone_num:
            digits = re.sub(r'[^\d+]', '', target)
            phone_num = digits if digits else "+60123456789"

        call_phone_number = f"tel:{phone_num}"
        reply = f"📞 Directing call to **{target.upper()}** (`{phone_num}`), {honorific}."

    elif inferred_intent == "SIMULATE_INCOMING_CALL":
        incoming_call_event = {
            "caller_id": "HQ Secure Line",
            "caller_number": "+1 (800) 555-EVAS",
            "auto_wake": True
        }
        reply = f"🚨 Incoming Telemetry Call Detected! Auto-waking screen HUD and overriding silent profiles, {honorific}."

    elif inferred_intent == "DIRECTIONS":
        destination = re.sub(r'directions to|route to|navigate to|map to|maps to|take me to|how to go to|go to|destination', '', user_prompt, flags=re.IGNORECASE).strip()
        if not destination: destination = "Penang Hill, Malaysia"
        encoded_dest = urllib.parse.quote(destination)
        
        if lat is not None and lon is not None:
            google_maps_url = f"https://www.google.com/maps/dir/?api=1&origin={lat},{lon}&destination={encoded_dest}&travelmode=driving"
        else:
            google_maps_url = f"https://www.google.com/maps/dir/?api=1&destination={encoded_dest}&travelmode=driving"

        reply = (
            f"🗺️ **DIRECT GOOGLE MAPS NAVIGATION LAUNCHED**\n\n"
            f"• **Destination**: `{destination}`\n"
            f"• **Routing Protocol**: Direct Navigation ('Go Now') Mode Enabled\n"
            f"• **Action**: Launching Google Maps with `{destination}` pre-filled, {honorific}."
        )

    elif inferred_intent == "BOOK_GRAB":
        dest = re.sub(r'book grab|grab ride|book a ride|call grab|grab car|grab bike|grab6seater|grabexec|to', '', user_prompt, flags=re.IGNORECASE).strip()
        if not dest: dest = "Penang International Airport"
        dest_enc = urllib.parse.quote(dest)
        grab_deep_link = f"grab://open?screen=transport&destination={dest_enc}&dropoff_address={dest_enc}"
        reply = f"Opening Grab for destination '{dest}', {honorific}."

    elif inferred_intent == "TRACK_LAZADA":
        lazada_tracking_url = "https://www.lazada.com.my/user/order/list"
        reply = f"Opening Lazada order tracking, {honorific}."

    elif inferred_intent == "GENERATE_IMAGE":
        prompt_clean = re.sub(r'generate image|create image|draw|make a photo|generate photo|picture of', '', user_prompt, flags=re.IGNORECASE).strip()
        if not prompt_clean: prompt_clean = "Futuristic Stark Arc Reactor Core HD render"
        encoded_prompt = urllib.parse.quote(prompt_clean)
        generated_image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=768&nologo=true&seed={random.randint(1000, 9999)}"
        reply = f"Generated render for '{prompt_clean}', {honorific}."

    elif inferred_intent == "CREATE_BLUEPRINT":
        build_item = re.sub(r'blueprint|design 3d|architectural plan|schematic of|build a|create design|assembly guide|exploded view', '', user_prompt, flags=re.IGNORECASE).strip()
        if not build_item: build_item = "Iron Man Mark LXXXV Arc Reactor"
        prompt_cad = urllib.parse.quote(f"CAD schematic blueprint of {build_item}, technical lines on blue grid")
        prompt_exploded = urllib.parse.quote(f"Exploded view assembly breakdown diagram of {build_item}")
        generated_image_url = f"https://image.pollinations.ai/prompt/{prompt_cad}?width=1024&height=768&nologo=true&seed={random.randint(1000, 9999)}"
        exploded_view_url = f"https://image.pollinations.ai/prompt/{prompt_exploded}?width=1024&height=768&nologo=true&seed={random.randint(1000, 9999)}"
        reply = f"CAD Blueprint & Exploded view generated for {build_item}, {honorific}."

    elif inferred_intent == "WEATHER":
        reply = fetch_global_weather(location, lat, lon)

    elif inferred_intent == "SAVE_FACT":
        fact = re.sub(r'remember that|save note|keep in mind', '', user_prompt, flags=re.IGNORECASE).strip()
        if fact:
            save_memory_fact(fact)
            reply = f"Saved to persistent memory, {honorific}: '{fact}'"

    if not reply:
        live_search_data = perform_live_web_search(user_prompt)

        system_prompt = (
            f"You are E.V.A.S. (Eventually Very Advanced System). Answer the user accurately, directly, and comprehensively based on the live search data provided. Address them as '{honorific}'."
        )

        if HAS_OLLAMA:
            try:
                prompt_content = f"User Request: {user_prompt}\n\nLive Search Telemetry:\n{live_search_data if live_search_data else 'None'}"
                response = ollama.chat(
                    model='deepseek-r1:1.5b',
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt_content}],
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
            if live_search_data:
                reply = f"### 📰 LIVE TELEMETRY REPORT:\n\n{live_search_data}"
            else:
                reply = f"E.V.A.S. Core online. Request received, {honorific}: **'{user_prompt}'**."

    clean_text = re.sub(r'[*_~`]', '', reply).strip()

    has_audio = False
    if not is_dnd and HAS_EDGE_TTS:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(generate_voice_file(clean_text, "en-GB-RyanNeural", "-3Hz", "+2%"))
            loop.close()
            has_audio = True
        except Exception as e:
            print(f"[TTS GENERATION ERROR]: {e}")

    return jsonify({
        'response': clean_text, 
        'raw_markdown': reply,
        'audio': has_audio,
        'call_phone_number': call_phone_number,
        'incoming_call_event': incoming_call_event,
        'google_maps_url': google_maps_url,
        'grab_deep_link': grab_deep_link,
        'lazada_tracking_url': lazada_tracking_url,
        'generated_image_url': generated_image_url,
        'exploded_view_url': exploded_view_url,
        'cctv_stream_url': cctv_stream_url,
        'cancel_cctv': cancel_cctv,
        'open_translate_hud': open_translate_hud
    })

async def generate_voice_file(text, voice, pitch, rate):
    if HAS_EDGE_TTS:
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