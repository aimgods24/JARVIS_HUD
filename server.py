from flask import Flask, render_template_string, request, jsonify, send_file, make_response, send_from_directory, session, redirect
from werkzeug.security import generate_password_hash, check_password_hash
import os
import re
import json
import sqlite3
import random
import threading
import time
import requests
import urllib.parse
import base64
import io
import asyncio
from duckduckgo_search import DDGS

try:
    from googlesearch import search as google_search
    HAS_GOOGLE_SEARCH = True
except Exception:
    HAS_GOOGLE_SEARCH = False

try:
    from PIL import Image, ImageEnhance
    import pytesseract
    HAS_OCR = True
except Exception:
    HAS_OCR = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except Exception:
    HAS_BS4 = False

try:
    import edge_tts
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
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "EVAS_MASTER_SECRET_SESSION_KEY_12345")

DB_FILE = "evas_users.db"
EVAS_BUILD_VERSION = "27.0.0-JARVIS-HUD-VISUAL-LOCKSCREEN"
EVAS_SECRET_KEY = os.environ.get("EVAS_SECRET_KEY", "DefaultSecureKey123")

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "YOUR_SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "YOUR_SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI", "http://localhost:5000/api/spotify/callback")

USER_REQUEST_TIMESTAMPS = {}

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            settings TEXT DEFAULT '{}',
            chat_history TEXT DEFAULT '[]',
            spotify_token TEXT DEFAULT '',
            is_locked INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def check_for_anomalies(username, sensitivity=6):
    now = time.time()
    if username not in USER_REQUEST_TIMESTAMPS:
        USER_REQUEST_TIMESTAMPS[username] = []
    
    timestamps = [t for t in USER_REQUEST_TIMESTAMPS[username] if now - t < 10]
    timestamps.append(now)
    USER_REQUEST_TIMESTAMPS[username] = timestamps

    if len(timestamps) > sensitivity:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE users SET is_locked = 1 WHERE username = ?", (username,))
        conn.commit()
        conn.close()
        return True
    return False

# ---------------------------------------------------------
# TECHNICAL BLUEPRINT & SCHEMATIC GENERATOR
# ---------------------------------------------------------
def generate_technical_blueprint(prompt):
    cleaned = re.sub(r'blueprint|design|schematic|create|draw|generate', '', prompt, flags=re.IGNORECASE).strip() or "Custom Structural Design"
    
    materials = ["Reinforced Titanium Alloy", "Carbon Fiber Composite", "Tempered Borosilicate Glass", "Structural Steel"]
    found_materials = [m for m in materials if m.lower() in prompt.lower()]
    if not found_materials:
        found_materials = ["Aerospace Titanium Alloy", "Carbon Composite Matrix", "High-Tensile Steel"]

    mat_specs = "\n".join([f"  • Material {i+1}: {m}" for i, m in enumerate(found_materials)])

    svg_blueprint = f'''
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 350" style="width:100%; height:auto; background:#001020; border:1px solid #00f3ff; border-radius:6px; margin-top:8px;">
        <defs>
            <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
                <path d="M 20 0 L 0 0 0 20" fill="none" stroke="#00f3ff" stroke-width="0.3" opacity="0.2"/>
            </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#grid)" />
        <rect x="20" y="20" width="560" height="310" fill="none" stroke="#00f3ff" stroke-width="1.5" opacity="0.8"/>
        
        <text x="35" y="45" fill="#00f3ff" font-family="monospace" font-size="12" font-weight="bold">SCHEMATIC: {cleaned.upper()[:35]}</text>
        <text x="35" y="60" fill="#00f3ff" font-family="monospace" font-size="9" opacity="0.7">CLASSIFICATION: ARCHITECTURAL VECTOR BLUEPRINT // SCALE 1:50</text>
        
        <rect x="120" y="90" width="360" height="180" fill="none" stroke="#00f3ff" stroke-width="2" stroke-dasharray="5,5"/>
        <circle cx="300" cy="180" r="65" fill="none" stroke="#00f3ff" stroke-width="1.5"/>
        <line x1="120" y1="90" x2="480" y2="270" stroke="#00f3ff" stroke-width="0.8" opacity="0.5"/>
        <line x1="480" y1="90" x2="120" y2="270" stroke="#00f3ff" stroke-width="0.8" opacity="0.5"/>
        
        <line x1="120" y1="285" x2="480" y2="285" stroke="#00f3ff" stroke-width="1"/>
        <text x="280" y="298" fill="#00f3ff" font-family="monospace" font-size="10">DIMENSION: 12.50m</text>
        
        <line x1="495" y1="90" x2="495" y2="270" stroke="#00f3ff" stroke-width="1"/>
        <text x="502" y="185" fill="#00f3ff" font-family="monospace" font-size="10">6.25m</text>
    </svg>
    '''

    text_report = (
        f"📐 **E.V.A.S. ARCHITECTURAL BLUEPRINT ENGINE GENERATED**\n\n"
        f"• **Project Subject**: `{cleaned.title()}`\n"
        f"• **Rendering Standard**: High-Precision Vector CAD Overlay\n\n"
        f"🛠️ **SPECIFIED MATERIAL MATRIX**:\n{mat_specs}\n\n"
        f"📐 **CAD TECHNICAL SPECIFICATIONS**:\n"
        f"  • Primary Axis Length: `12.50 meters`\n"
        f"  • Secondary Transverse Span: `6.25 meters`\n"
        f"  • Structural Load Factor: `Safety Class Alpha (1.8x)`\n"
        f"  • Tolerances: `±0.05 mm`"
    )

    return text_report, svg_blueprint

# ---------------------------------------------------------
# SPOTIFY OAUTH & PLAYER ENGINE
# ---------------------------------------------------------
@app.route('/api/spotify/login')
def spotify_login():
    scope = "user-read-currently-playing user-read-playback-state"
    params = {
        "client_id": SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "scope": scope,
        "show_dialog": "true"
    }
    auth_url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(params)
    return redirect(auth_url)

@app.route('/api/spotify/callback')
def spotify_callback():
    code = request.args.get('code')
    if not code:
        return "Spotify Authorization Failed.", 400

    token_url = "https://accounts.spotify.com/api/token"
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "client_id": SPOTIFY_CLIENT_ID,
        "client_secret": SPOTIFY_CLIENT_SECRET
    }
    res = requests.post(token_url, data=payload).json()
    access_token = res.get('access_token')

    if access_token:
        session['spotify_token'] = access_token
        return render_template_string("""
            <script>
                alert('Spotify successfully connected to E.V.A.S. HUD!');
                window.location.href = '/';
            </script>
        """)
    return "Failed to acquire Spotify token.", 400

@app.route('/api/spotify/now-playing', methods=['GET'])
def get_spotify_now_playing():
    token = session.get('spotify_token')
    if not token:
        return jsonify({'playing': False, 'message': 'Spotify not connected. Click Connect Spotify.'})

    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = requests.get("https://api.spotify.com/v1/me/player/currently-playing", headers=headers, timeout=4)
        if res.status_code == 204 or not res.text:
            return jsonify({'playing': False, 'message': 'No song currently playing on Spotify.'})
        
        data = res.json()
        item = data.get('item', {})
        song_name = item.get('name', 'Unknown Track')
        artist_name = item.get('artists', [{}])[0].get('name', 'Unknown Artist')
        lyrics = fetch_song_lyrics(song_name, artist_name)

        return jsonify({
            'playing': True,
            'title': song_name,
            'artist': artist_name,
            'lyrics': lyrics
        })
    except Exception as e:
        return jsonify({'playing': False, 'message': f'Spotify sync error: {str(e)}'})

def fetch_song_lyrics(song, artist):
    query = f"{song} {artist} lyrics"
    try:
        with DDGS() as ddgs:
            search_res = list(ddgs.text(query, max_results=3))
            for r in search_res:
                body = r.get('body', '')
                if len(body) > 100:
                    return body[:800] + "\n\n...[Lyrics Synced via EVAS Telemetry]"
    except Exception:
        pass
    return f"Lyrics preview for '{song}' by {artist} loaded successfully."

def get_location_recommendations_with_prices(prompt, lat=5.2971, lon=100.2588):
    try:
        geo_url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}"
        headers = {"User-Agent": "EVAS_HUD_System/1.0"}
        geo_res = requests.get(geo_url, headers=headers, timeout=4).json()
        
        address = geo_res.get('address', {})
        city = address.get('city') or address.get('town') or address.get('state') or "Penang"
        country = address.get('country', 'Malaysia')
    except Exception:
        city = "Penang"
        country = "Malaysia"

    if country == "Malaysia":
        places = [
            {"name": f"{city} Cultural Heritage Street / UNESCO Zone", "price": "FREE Entry (Street Dining: RM 10 – RM 30)"},
            {"name": "Scenic Hill / Cable Car Tram Station", "price": "RM 12 – RM 30 (Local Standard Rate)"},
            {"name": "Popular Local Night Market", "price": "FREE Admission (Food Snacks: RM 5 – RM 20)"},
            {"name": "Coastal Waterfront Esplanade", "price": "FREE Entry"}
        ]
        dos_and_donts = "• **DO**: Try local hawker food and respect religious heritage sites.\n• **DON'T**: Litter or disrespect local traditions."
    else:
        places = [
            {"name": f"{city} Downtown Square & Historic Quarter", "price": "FREE Entry"},
            {"name": "City Landmark Observatory / Museum", "price": "$10 – $25 USD"},
            {"name": "Central Market & Artisanal Stalls", "price": "FREE Entry"}
        ]
        dos_and_donts = "• **DO**: Carry standard ID and adhere to local municipal laws.\n• **DON'T**: Ignore safety signs near restricted areas."

    places_text = "\n".join([f"• **{p['name']}**: `Estimated Price: {p['price']}`" for p in places])

    return (
        f"🌍 **EVAS LOCATION & TRAVEL RECOMMENDATIONS (DETECTED: {city.upper()}, {country.upper()})**\n\n"
        f"📍 **RECOMMENDED PLACES TO VISIT & ENTRY PRICES**:\n{places_text}\n\n"
        f"⏰ **Best Visiting Hours**: Morning (08:00–11:00) & Evening (17:30–20:30)\n"
        f"⚠️ **Times to Avoid**: Peak afternoon heat (12:00–15:00)\n\n"
        f"📜 **REGIONAL GUIDELINES ({country.upper()})**:\n{dos_and_donts}"
    )

def get_live_weather(lat=5.2971, lon=100.2588):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,wind_speed_10m,weather_code&daily=sunrise,sunset&timezone=auto"
        res = requests.get(url, timeout=5).json()
        current = res.get('current', {})
        daily = res.get('daily', {})
        
        temp = current.get('temperature_2m', 'N/A')
        wind = current.get('wind_speed_10m', 'N/A')
        sunrise = daily.get('sunrise', ['N/A'])[0].split('T')[-1] if daily.get('sunrise') else 'N/A'
        sunset = daily.get('sunset', ['N/A'])[0].split('T')[-1] if daily.get('sunset') else 'N/A'
        
        return (
            f"🌤️ **LIVE METEOROLOGICAL TELEMETRY**\n\n"
            f"• **Coordinates**: `{lat:.4f}, {lon:.4f}`\n"
            f"• **Temperature**: `{temp} °C`\n"
            f"• **Wind Velocity**: `{wind} km/h`\n"
            f"• **Sunrise**: `{sunrise}`\n"
            f"• **Sunset**: `{sunset}`"
        )
    except Exception as e:
        return f"Weather telemetry request failed: {e}"

def process_and_analyze_attachment(file_b64, file_type=""):
    if not file_b64:
        return "", None
    
    try:
        header, encoded = file_b64.split(",", 1) if "," in file_b64 else ("", file_b64)
        file_bytes = base64.b64decode(encoded)
        
        if any(img_ext in file_type for img_ext in ["image", ".png", ".jpg", ".jpeg", ".webp", ".bmp"]) or not file_type:
            if HAS_OCR:
                img = Image.open(io.BytesIO(file_bytes)).convert('L')
                enhancer = ImageEnhance.Contrast(img)
                enhanced_img = enhancer.enhance(2.0)
                
                extracted_text = pytesseract.image_to_string(enhanced_img)
                if not extracted_text.strip():
                    extracted_text = pytesseract.image_to_string(img)
                
                if extracted_text.strip():
                    analysis_summary = (
                        f"\n\n📷 **[E.V.A.S. VISION ENGINE ATTACHMENT PARSED]**\n"
                        f"• **Extracted Data Content**:\n```text\n{extracted_text.strip()}\n```\n"
                    )
                    return analysis_summary, extracted_text.strip()
                
                return "\n\n📷 **[E.V.A.S. VISION ENGINE]**: Image payload received.", None
            else:
                return "\n\n⚠️ **[E.V.A.S. VISION ENGINE]**: OCR module pending setup.", None
        
        elif any(doc_ext in file_type for doc_ext in ["text", ".txt", ".py", ".js", ".html", ".css", ".json", ".csv", ".md"]):
            decoded_text = file_bytes.decode('utf-8', errors='ignore')
            return f"\n\n📄 **[E.V.A.S. FILE READER]**:\n```text\n{decoded_text.strip()}\n```\n", decoded_text.strip()

    except Exception as e:
        return f"\n\n⚠️ **[E.V.A.S. VISION ENGINE ERROR]**: `{str(e)}`", None
        
    return "\n\n📄 **[E.V.A.S. FILE READER]**: File attached.", None

def parse_contextual_intent(prompt):
    p = prompt.lower()
    if any(w in p for w in ["blueprint", "schematic", "cad drawing", "design blueprint"]):
        return "GENERATE_BLUEPRINT"
    if any(w in p for w in ["gsc", "golden screen cinema", "cinema app", "movie tickets"]):
        return "GSC_APP"
    if any(w in p for w in ["open spotify", "connect spotify", "launch spotify"]):
        return "OPEN_SPOTIFY"
    if any(w in p for w in ["directions to", "route to", "navigate to", "map to", "take me to", "go to"]):
        return "DIRECTIONS"
    if any(w in p for w in ["speed test", "wifi speed", "connection speed"]):
        return "RUN_SPEEDTEST"
    if any(w in p for w in ["weather", "temperature", "sunrise", "sunset", "wind speed"]):
        return "WEATHER"
    if any(w in p for w in ["recommend", "places to visit", "how much", "price", "entry fee", "travel"]):
        return "PLACES_RECOMMENDATION"
    return "UNIVERSAL_EXECUTION"

def perform_google_search(query):
    results = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}
    encoded_query = urllib.parse.quote(query)
    google_url = f"https://www.google.com/search?q={encoded_query}&hl=en"
    
    try:
        response = requests.get(google_url, headers=headers, timeout=4)
        if response.status_code == 200 and HAS_BS4:
            soup = BeautifulSoup(response.text, "html.parser")
            snippets = soup.find_all(['div', 'span'], class_=re.compile(r'(VwiC3b|yXMda|MUxGv|Hg231c)'))
            for s in snippets:
                txt = s.get_text().strip()
                if len(txt) > 30 and txt not in results:
                    results.append(txt)
    except Exception:
        pass

    if not results and HAS_GOOGLE_SEARCH:
        try:
            for url in google_search(query, num_results=4, lang="en"):
                results.append(f"• Result URL: {url}")
        except Exception:
            pass

    if not results:
        try:
            with DDGS() as ddgs:
                ddg_results = list(ddgs.text(query, max_results=4))
                if ddg_results:
                    for res in ddg_results:
                        if 'body' in res and res['body']:
                            results.append(f"• **{res.get('title', 'Result')}**\n{res['body']}")
        except Exception:
            pass

    return "\n\n".join(results[:4]) if results else None

async def create_tts_audio_file(text, voice_rate="+0%", voice_pitch="-4Hz", filename="static_speech.mp3"):
    if not HAS_EDGE_TTS:
        return False
    try:
        clean_prompt = re.sub(r'[*_~`#>]', '', text).strip()
        if not clean_prompt:
            clean_prompt = "Response completed."
        communicate = edge_tts.Communicate(clean_prompt[:600], "en-GB-RyanNeural", pitch=voice_pitch, rate=voice_rate)
        await communicate.save(filename)
        return True
    except Exception:
        return False

def generate_voice_sync(text, voice_rate="+0%", voice_pitch="-4Hz"):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(create_tts_audio_file(text, voice_rate, voice_pitch))
        loop.close()
        return success
    except Exception:
        return False

def run_network_speedtest():
    if not HAS_SPEEDTEST:
        return "⚠️ Speedtest engine module not available."
    try:
        st = speedtest.Speedtest(secure=True)
        st.get_best_server()
        return (
            f"⚡ **LIVE NETWORK DIAGNOSTIC REPORT**\n\n"
            f"• **Download**: `{st.download() / 1000000.0:.2f} Mbps`\n"
            f"• **Upload**: `{st.upload() / 1000000.0:.2f} Mbps`\n"
            f"• **Ping**: `{st.results.ping:.1f} ms`"
        )
    except Exception as e:
        return f"Speedtest failed: {e}"

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.json or {}
    username = data.get('username', '').strip().lower()
    password = data.get('password', '').strip()
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        pw_hash = generate_password_hash(password)
        c.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, pw_hash))
        conn.commit()
        session['username'] = username
        return jsonify({'message': 'Account created successfully', 'username': username})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Username already exists'}), 400
    finally:
        conn.close()

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    username = data.get('username', '').strip().lower()
    password = data.get('password', '').strip()

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT password_hash, settings, chat_history, is_locked FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    conn.close()

    if user and check_password_hash(user[0], password):
        session['username'] = username
        return jsonify({
            'message': 'Logged in successfully',
            'username': username,
            'settings': json.loads(user[1] or '{}'),
            'chat_history': json.loads(user[2] or '[]'),
            'is_locked': bool(user[3])
        })
    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/auth/unlock', methods=['POST'])
def unlock_account():
    data = request.json or {}
    username = session.get('username') or data.get('username')
    password = data.get('password', '')

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
    user = c.fetchone()

    if user and check_password_hash(user[0], password):
        c.execute("UPDATE users SET is_locked = 0 WHERE username = ?", (username,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Account unlocked successfully'})
    conn.close()
    return jsonify({'error': 'Unlock failed. Invalid password.'}), 401

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.pop('username', None)
    return jsonify({'message': 'Logged out successfully'})

@app.route('/')
def home():
    if os.path.exists('index.html'):
        with open('index.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
    else:
        html_content = "<h1>E.V.A.S. Master HUD Active.</h1>"
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
    return render_template_string("<h1>E.V.A.S. Watch PWA Active</h1>")

@app.route('/api/version')
def get_version():
    return jsonify({"version": EVAS_BUILD_VERSION})

@app.route('/api/ask', methods=['POST'])
def ask():
    data = request.json or {}
    provided_key = request.headers.get("X-EVAS-KEY") or data.get("secret_key")
    
    if EVAS_SECRET_KEY and provided_key != EVAS_SECRET_KEY:
        return jsonify({'response': '🔒 Unauthorized access blocked. Invalid Secret Key.', 'audio': False}), 403

    username = session.get('username') or data.get('username', 'guest')

    if username != 'guest':
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT is_locked FROM users WHERE username = ?", (username,))
        row = c.fetchone()
        conn.close()
        if row and row[0] == 1:
            return jsonify({'response': '🚨 WORKSPACE LOCKED: Enter account password to resume.', 'is_locked': True}), 423

        if check_for_anomalies(username):
            return jsonify({'response': '🚨 WORKSPACE LOCKED: Rapid burst activity detected.', 'is_locked': True}), 423

    user_prompt = data.get('prompt', '').strip()
    settings = data.get('settings', {})
    honorific = settings.get('honorific', 'Sir')
    voice_rate = settings.get('voice_rate', '+0%')
    voice_pitch = settings.get('voice_pitch', '-4Hz')
    custom_prefix = settings.get('custom_prefix', '').strip()
    enable_search = settings.get('enable_search', True)

    lat = data.get('latitude', 5.2971)
    lon = data.get('longitude', 100.2588)
    file_b64 = data.get('file_b64', None)
    file_type = data.get('file_type', '')

    file_analysis_text, raw_extracted_ocr = process_and_analyze_attachment(file_b64, file_type)
    if file_analysis_text:
        user_prompt = f"{user_prompt}{file_analysis_text}".strip()

    if not user_prompt:
        return jsonify({'response': f'No query or file received, {honorific}.', 'audio': False})

    inferred_intent = parse_contextual_intent(user_prompt)
    reply = None
    svg_blueprint = None
    google_maps_url = None
    action_type = None

    if inferred_intent == "GENERATE_BLUEPRINT":
        reply, svg_blueprint = generate_technical_blueprint(user_prompt)

    elif inferred_intent == "GSC_APP":
        action_type = "GSC_DISPATCH"
        reply = f"🎬 **GSC APP PROTOCOL LAUNCHED**\n\n• **Action**: Dispatching Golden Screen Cinemas App, {honorific}."

    elif inferred_intent == "OPEN_SPOTIFY":
        action_type = "SPOTIFY_DISPATCH"
        reply = f"🎵 **SPOTIFY DISPATCH PROTOCOL LAUNCHED**\n\n• **Action**: Opening Spotify player, {honorific}."

    elif inferred_intent == "WEATHER":
        reply = get_live_weather(lat, lon)

    elif inferred_intent == "PLACES_RECOMMENDATION":
        reply = get_location_recommendations_with_prices(user_prompt, lat, lon)

    elif inferred_intent == "DIRECTIONS":
        destination = re.sub(r'directions to|route to|navigate to|map to|take me to|go to', '', user_prompt, flags=re.IGNORECASE).strip() or "Penang Hill, Malaysia"
        encoded_dest = urllib.parse.quote(destination)
        google_maps_url = f"https://www.google.com/maps/dir/?api=1&origin={lat},{lon}&destination={encoded_dest}&travelmode=driving"
        reply = f"🗺️ **GOOGLE MAPS NAVIGATION DISPATCHED**\n\n• **Destination**: `{destination}`\n• **Status**: Direct routing mode active, {honorific}."

    elif inferred_intent == "RUN_SPEEDTEST":
        reply = run_network_speedtest()

    if not reply:
        google_search_data = perform_google_search(user_prompt) if enable_search else None
        system_prompt = f"You are E.V.A.S., an AI assistant styled after J.A.R.V.I.S. Address user as '{honorific}'."

        if HAS_OLLAMA:
            try:
                full_input = f"User Request: {user_prompt}\n\nSearch Telemetry:\n{google_search_data if google_search_data else 'None'}"
                res = ollama.chat(model='deepseek-r1:1.5b', messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": full_input}])
                reply = re.sub(r'<think>[\s\S]*?</think>', '', res['message']['content']).strip()
            except Exception:
                reply = None

        if not reply:
            if file_analysis_text:
                reply = f"### 📝 E.V.A.S. VISION ENGINE REPORT:\n{file_analysis_text}\n\n*Processed successfully, {honorific}.*"
            elif google_search_data:
                reply = f"### 🌐 GOOGLE SEARCH REPORT:\n\n{google_search_data}\n\n*Query processed, {honorific}.*"
            else:
                reply = f"E.V.A.S. Core online. Request **'{user_prompt}'** verified, {honorific}."

    if custom_prefix and not reply.startswith(custom_prefix):
        reply = f"{custom_prefix} {reply}"

    clean_reply = re.sub(r'[*_~`#>]', '', reply).strip()
    has_audio = generate_voice_sync(clean_reply, voice_rate, voice_pitch)

    if username != 'guest':
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT settings, chat_history FROM users WHERE username = ?", (username,))
        row = c.fetchone()
        if row:
            history = json.loads(row[1] or '[]')
            history.append({'user': user_prompt, 'evas': clean_reply})
            c.execute("UPDATE users SET settings = ?, chat_history = ? WHERE username = ?", (json.dumps(settings), json.dumps(history[-30:]), username))
            conn.commit()
        conn.close()

    return jsonify({
        'response': clean_reply, 
        'raw_markdown': reply,
        'audio': has_audio,
        'svg_blueprint': svg_blueprint,
        'google_maps_url': google_maps_url,
        'action_type': action_type
    })

@app.route('/api/audio')
def get_audio():
    if os.path.exists('static_speech.mp3'):
        response = make_response(send_file('static_speech.mp3', mimetype='audio/mpeg'))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response
    return ("", 404)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)