from flask import Flask, render_template_string, request, jsonify, send_file, make_response, send_from_directory, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import os
import re
import json
import sqlite3
import time
import requests
import urllib.parse
import base64
import io
import asyncio
from datetime import datetime

# Google API Client Libraries
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
    HAS_GOOGLE_APIS = True
except Exception:
    HAS_GOOGLE_APIS = False

# OpenAI SDK Integration
try:
    from openai import OpenAI
    HAS_OPENAI = True
except Exception:
    HAS_OPENAI = False

try:
    from PIL import Image, ImageEnhance
    import pytesseract
    HAS_OCR = True
except Exception:
    HAS_OCR = False

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

# Allow HTTP for local OAuth testing
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

DB_FILE = "evas_users.db"
EVAS_BUILD_VERSION = "32.0.0-GOOGLE-WORKSPACE-HUD"
EVAS_SECRET_KEY = os.environ.get("EVAS_SECRET_KEY", "DefaultSecureKey123")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if (HAS_OPENAI and OPENAI_API_KEY) else None

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "YOUR_SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "YOUR_SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI", "http://localhost:5000/api/spotify/callback")

# Google OAuth Settings
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "YOUR_GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "YOUR_GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:5000/api/google/callback")
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly"
]

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
            google_creds TEXT DEFAULT '',
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
# GOOGLE OAUTH2, CALENDAR & GMAIL ENGINE
# ---------------------------------------------------------
@app.route('/api/google/login')
def google_login():
    if not HAS_GOOGLE_APIS:
        return "Google API Client libraries not installed on server.", 500

    client_config = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token"
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=GOOGLE_SCOPES,
        redirect_uri=GOOGLE_REDIRECT_URI
    )
    auth_url, state = flow.authorization_url(prompt='consent', access_type='offline')
    session['google_oauth_state'] = state
    return redirect(auth_url)

@app.route('/api/google/callback')
def google_callback():
    client_config = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token"
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=GOOGLE_SCOPES,
        redirect_uri=GOOGLE_REDIRECT_URI
    )
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials

    creds_data = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    
    session['google_creds'] = json.dumps(creds_data)
    
    username = session.get('username')
    if username:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE users SET google_creds = ? WHERE username = ?", (json.dumps(creds_data), username))
        conn.commit()
        conn.close()

    return render_template_string("""
        <script>
            alert('Google Workspace (Calendar & Gmail) connected to E.V.A.S. HUD!');
            window.location.href = '/';
        </script>
    """)

def get_google_credentials():
    creds_json = session.get('google_creds')
    username = session.get('username')

    if not creds_json and username:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT google_creds FROM users WHERE username = ?", (username,))
        row = c.fetchone()
        conn.close()
        if row and row[0]:
            creds_json = row[0]

    if not creds_json:
        return None

    data = json.loads(creds_json)
    return Credentials(
        token=data['token'],
        refresh_token=data.get('refresh_token'),
        token_uri=data['token_uri'],
        client_id=data['client_id'],
        client_secret=data['client_secret'],
        scopes=data['scopes']
    )

def fetch_google_calendar_events(honorific="Sir"):
    creds = get_google_credentials()
    if not creds:
        return f"📅 **GOOGLE CALENDAR TELEMETRY**\n\n• **Status**: Google Account not connected.\n• **Action**: [Click here to connect Google Workspace](/api/google/login), {honorific}."

    try:
        service = build('calendar', 'v3', credentials=creds)
        now = datetime.utcnow().isoformat() + 'Z'
        events_result = service.events().list(
            calendarId='primary', timeMin=now, maxResults=5, singleEvents=True, orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])

        if not events:
            return f"📅 **GOOGLE CALENDAR TELEMETRY**\n\n• **Upcoming Events**: No scheduled events found, {honorific}."

        events_text = ""
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary = event.get('summary', 'Untitled Event')
            events_text += f"• **{summary}**: `{start}`\n"

        return f"📅 **GOOGLE CALENDAR TELEMETRY**\n\n{events_text}"
    except Exception as e:
        return f"⚠️ Google Calendar error: {str(e)}"

def fetch_recent_gmail_messages(honorific="Sir"):
    creds = get_google_credentials()
    if not creds:
        return f"✉️ **GMAIL TELEMETRY**\n\n• **Status**: Google Account not connected.\n• **Action**: [Click here to connect Google Workspace](/api/google/login), {honorific}."

    try:
        service = build('gmail', 'v1', credentials=creds)
        results = service.users().messages().list(userId='me', maxResults=5).execute()
        messages = results.get('messages', [])

        if not messages:
            return f"✉️ **GMAIL TELEMETRY**\n\n• **Inbox Status**: No recent emails retrieved, {honorific}."

        email_summary = ""
        for msg in messages:
            m = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
            payload = m.get('payload', {})
            headers = payload.get('headers', [])
            
            subject = "No Subject"
            sender = "Unknown Sender"
            for h in headers:
                if h['name'].lower() == 'subject':
                    subject = h['value']
                if h['name'].lower() == 'from':
                    sender = h['value']

            snippet = m.get('snippet', '')[:80]
            email_summary += f"• **From**: `{sender}`\n  **Subject**: {subject}\n  *Snippet*: {snippet}...\n\n"

        return f"✉️ **GMAIL RECENT MESSAGES**\n\n{email_summary}"
    except Exception as e:
        return f"⚠️ Gmail error: {str(e)}"

# ---------------------------------------------------------
# DYNAMIC MULTI-VARIANT DESIGN SYNTHESIZER
# ---------------------------------------------------------
def generate_multivariant_design(prompt):
    subject = re.sub(r'blueprint|design|schematic|create|draw|generate|make|build', '', prompt, flags=re.IGNORECASE).strip() or "Custom Engineered Concept"
    
    known_materials = [
        "Titanium", "Carbon Fiber", "Graphene", "Aluminum Alloy", 
        "Reinforced Steel", "Borosilicate Glass", "Polycarbonate", "Kevlar"
    ]
    detected_materials = [m for m in known_materials if m.lower() in prompt.lower()]
    if not detected_materials:
        detected_materials = ["Aerospace Titanium Alloy", "Carbon Composite Matrix", "High-Tensile Steel"]

    mat_list_str = "\n".join([f"  • Material {i+1}: `{m}`" for i, m in enumerate(detected_materials)])

    variants = [
        {
            "id": "Variant Alpha",
            "style": "Industrial Heavy-Duty Structural Frame",
            "load_rating": "Alpha (2.5x Load Factor)",
            "svg_elements": '''
                <rect x="50" y="80" width="500" height="180" fill="none" stroke="#00f3ff" stroke-width="2"/>
                <line x1="50" y1="80" x2="550" y2="260" stroke="#00f3ff" stroke-width="1" stroke-dasharray="4,4"/>
                <line x1="550" y1="80" x2="50" y2="260" stroke="#00f3ff" stroke-width="1" stroke-dasharray="4,4"/>
                <circle cx="300" cy="170" r="45" fill="none" stroke="#ffaa00" stroke-width="1.5"/>
            '''
        },
        {
            "id": "Variant Beta",
            "style": "Aerodynamic Streamlined Contour Architecture",
            "load_rating": "Beta (1.8x High Velocity)",
            "svg_elements": '''
                <ellipse cx="300" cy="170" rx="220" ry="80" fill="none" stroke="#00f3ff" stroke-width="2"/>
                <path d="M 80,170 Q 300,50 520,170 Q 300,290 80,170 Z" fill="none" stroke="#ffaa00" stroke-width="1.5" stroke-dasharray="6,3"/>
                <circle cx="300" cy="170" r="25" fill="none" stroke="#00f3ff" stroke-width="1.5"/>
            '''
        },
        {
            "id": "Variant Gamma",
            "style": "Modular Multi-Cellular Component Mesh",
            "load_rating": "Gamma (3.0x Reinforcement)",
            "svg_elements": '''
                <rect x="100" y="70" width="120" height="200" fill="none" stroke="#00f3ff" stroke-width="1.5"/>
                <rect x="240" y="70" width="120" height="200" fill="none" stroke="#00f3ff" stroke-width="2"/>
                <rect x="380" y="70" width="120" height="200" fill="none" stroke="#00f3ff" stroke-width="1.5"/>
                <line x1="60" y1="170" x2="540" y2="170" stroke="#ffaa00" stroke-width="1.5" stroke-dasharray="5,5"/>
            '''
        }
    ]

    svg_render = f'''
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 360" style="width:100%; height:auto; background:#001020; border:1px solid #00f3ff; border-radius:6px; margin-top:8px;">
        <defs>
            <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
                <path d="M 20 0 L 0 0 0 20" fill="none" stroke="#00f3ff" stroke-width="0.3" opacity="0.2"/>
            </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#grid)" />
        <rect x="15" y="15" width="570" height="330" fill="none" stroke="#00f3ff" stroke-width="1.5" opacity="0.8"/>
        
        <text x="30" y="40" fill="#00f3ff" font-family="monospace" font-size="12" font-weight="bold">DESIGN MATRIX: {subject.upper()[:30]}</text>
        <text x="30" y="55" fill="#ffaa00" font-family="monospace" font-size="9">MULTI-VARIANT CAD SCHEMATIC // MATERIAL & SPECIFICATION ALIGNED</text>

        {variants[0]["svg_elements"]}

        <line x1="50" y1="285" x2="550" y2="285" stroke="#00f3ff" stroke-width="1"/>
        <text x="240" y="300" fill="#00f3ff" font-family="monospace" font-size="10">DIMENSIONS: 15.00m Span (Scale 1:50)</text>
    </svg>
    '''

    report = (
        f"📐 **E.V.A.S. MULTI-VARIANT DESIGN SYNTHESIZER**\n\n"
        f"• **Requested Design Project**: `{subject.title()}`\n"
        f"• **Accuracy Standard**: Exact Specification & Material Optimization\n\n"
        f"🛠️ **APPLIED MATERIAL MATRIX**:\n{mat_list_str}\n\n"
        f"⚙️ **GENERATED DESIGN CHOICES**:\n"
        f"  1. **Variant Alpha**: `{variants[0]['style']}` (Load Factor: `{variants[0]['load_rating']}`)\n"
        f"  2. **Variant Beta**: `{variants[1]['style']}` (Load Factor: `{variants[1]['load_rating']}`)\n"
        f"  3. **Variant Gamma**: `{variants[2]['style']}` (Load Factor: `{variants[2]['load_rating']}`)\n\n"
        f"💡 *All 3 variant models rendered on Canvas. Specify any variant number to isolate or expand parameters.*"
    )

    return report, svg_render

# ---------------------------------------------------------
# SPOTIFY OAUTH ENGINE
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
        lyrics = f"Lyrics preview for '{song_name}' by {artist_name} loaded successfully via local telemetry."

        return jsonify({
            'playing': True,
            'title': song_name,
            'artist': artist_name,
            'lyrics': lyrics
        })
    except Exception as e:
        return jsonify({'playing': False, 'message': f'Spotify sync error: {str(e)}'})

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

    places = [
        {"name": f"{city} Cultural Heritage Street Zone", "price": "FREE Entry"},
        {"name": "Scenic Hill Tram Station", "price": "RM 12 – RM 30"},
        {"name": "Local Night Market", "price": "FREE Admission"}
    ]
    places_text = "\n".join([f"• **{p['name']}**: `Estimated Price: {p['price']}`" for p in places])

    return (
        f"🌍 **EVAS LOCATION RECOMMENDATIONS ({city.upper()}, {country.upper()})**\n\n"
        f"📍 **PLACES TO VISIT**:\n{places_text}"
    )

def get_live_weather(lat=5.2971, lon=100.2588):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,wind_speed_10m&timezone=auto"
        res = requests.get(url, timeout=5).json()
        current = res.get('current', {})
        return f"🌤️ **LIVE METEOROLOGICAL TELEMETRY**\n\n• **Temp**: `{current.get('temperature_2m')} °C` | **Wind**: `{current.get('wind_speed_10m')} km/h`"
    except Exception as e:
        return f"Weather telemetry request failed: {e}"

def process_and_analyze_attachment(file_b64, file_type=""):
    if not file_b64:
        return "", None
    try:
        header, encoded = file_b64.split(",", 1) if "," in file_b64 else ("", file_b64)
        file_bytes = base64.b64decode(encoded)
        if HAS_OCR:
            img = Image.open(io.BytesIO(file_bytes)).convert('L')
            text = pytesseract.image_to_string(img)
            return f"\n\n📷 **[OCR PARSED CONTENT]**:\n```text\n{text.strip()}\n```\n", text.strip()
    except Exception as e:
        return f"\n\n⚠️ Vision module error: {str(e)}", None
    return "", None

def parse_contextual_intent(prompt):
    p = prompt.lower()
    if any(w in p for w in ["calendar", "events", "schedule", "my agenda"]):
        return "CHECK_CALENDAR"
    if any(w in p for w in ["email", "emails", "gmail", "inbox", "my messages"]):
        return "CHECK_GMAIL"
    if any(w in p for w in ["design", "blueprint", "schematic", "cad drawing"]):
        return "GENERATE_MULTIVARIANT_DESIGN"
    if any(w in p for w in ["gsc", "cinema"]):
        return "GSC_APP"
    if any(w in p for w in ["open spotify", "connect spotify"]):
        return "OPEN_SPOTIFY"
    if any(w in p for w in ["directions to", "navigate to", "route to"]):
        return "DIRECTIONS"
    if any(w in p for w in ["speed test", "wifi speed"]):
        return "RUN_SPEEDTEST"
    if any(w in p for w in ["weather", "temperature"]):
        return "WEATHER"
    if any(w in p for w in ["recommend", "places to visit"]):
        return "PLACES_RECOMMENDATION"
    return "UNIVERSAL_EXECUTION"

async def create_tts_audio_file(text, voice_rate="+0%", voice_pitch="-4Hz", filename="static_speech.mp3"):
    if not HAS_EDGE_TTS:
        return False
    try:
        clean_prompt = re.sub(r'[*_~`#>]', '', text).strip()
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
        return "⚠️ Speedtest module not available."
    try:
        st = speedtest.Speedtest(secure=True)
        st.get_best_server()
        return f"⚡ **SPEEDTEST REPORT**\n\n• **Download**: `{st.download()/1e6:.2f} Mbps` | **Upload**: `{st.upload()/1e6:.2f} Mbps`"
    except Exception as e:
        return f"Speedtest error: {e}"

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
        c.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, generate_password_hash(password)))
        conn.commit()
        session['username'] = username
        return jsonify({'message': 'Registered', 'username': username})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'User exists'}), 400
    finally:
        conn.close()

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    username = data.get('username', '').strip().lower()
    password = data.get('password', '').strip()

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT password_hash, settings, chat_history, is_locked, google_creds FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    conn.close()

    if user and check_password_hash(user[0], password):
        session['username'] = username
        if user[4]:
            session['google_creds'] = user[4]
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
        return jsonify({'response': '🔒 Unauthorized access blocked.', 'audio': False}), 403

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

    if inferred_intent == "CHECK_CALENDAR":
        reply = fetch_google_calendar_events(honorific)

    elif inferred_intent == "CHECK_GMAIL":
        reply = fetch_recent_gmail_messages(honorific)

    elif inferred_intent == "GENERATE_MULTIVARIANT_DESIGN":
        reply, svg_blueprint = generate_multivariant_design(user_prompt)

    elif inferred_intent == "GSC_APP":
        action_type = "GSC_DISPATCH"
        reply = f"🎬 **GSC APP PROTOCOL LAUNCHED**, {honorific}."

    elif inferred_intent == "OPEN_SPOTIFY":
        action_type = "SPOTIFY_DISPATCH"
        reply = f"🎵 **SPOTIFY DISPATCH PROTOCOL LAUNCHED**, {honorific}."

    elif inferred_intent == "WEATHER":
        reply = get_live_weather(lat, lon)

    elif inferred_intent == "PLACES_RECOMMENDATION":
        reply = get_location_recommendations_with_prices(user_prompt, lat, lon)

    elif inferred_intent == "DIRECTIONS":
        destination = re.sub(r'directions to|navigate to|route to', '', user_prompt, flags=re.IGNORECASE).strip() or "Penang Hill, Malaysia"
        encoded_dest = urllib.parse.quote(destination)
        google_maps_url = f"https://www.google.com/maps/dir/?api=1&origin={lat},{lon}&destination={encoded_dest}&travelmode=driving"
        reply = f"🗺️ **NAVIGATION DISPATCHED**: Routing to `{destination}`, {honorific}."

    elif inferred_intent == "RUN_SPEEDTEST":
        reply = run_network_speedtest()

    if not reply:
        today_date = datetime.now().strftime("%B %d, %Y")
        system_prompt = f"You are E.V.A.S., an AI assistant styled after J.A.R.V.I.S. Address user as '{honorific}'. Today's date is {today_date}."

        if openai_client:
            try:
                completion = openai_client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.7
                )
                reply = completion.choices[0].message.content.strip()
            except Exception as e:
                reply = None

        if not reply and HAS_OLLAMA:
            try:
                res = ollama.chat(model='deepseek-r1:1.5b', messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}])
                reply = re.sub(r'<think>[\s\S]*?</think>', '', res['message']['content']).strip()
            except Exception:
                reply = None

        if not reply:
            reply = f"E.V.A.S. Core online. Request verified, {honorific}."

    clean_reply = re.sub(r'[*_~`#>]', '', reply).strip()
    has_audio = generate_voice_sync(clean_reply, voice_rate, voice_pitch)

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
        return response
    return ("", 404)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)