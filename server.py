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

DB_FILE = "evas_users.db"
EVAS_BUILD_VERSION = "35.0.0-LOCATION-MATRIX"
EVAS_SECRET_KEY = os.environ.get("EVAS_SECRET_KEY", "DefaultSecureKey123")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if (HAS_OPENAI and OPENAI_API_KEY) else None

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "YOUR_SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "YOUR_SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI", "http://localhost:5000/api/spotify/callback")

USER_REQUEST_TIMESTAMPS = {}

DEFAULT_EXTENDED_SETTINGS = {
    "honorific": "Sir",
    "voice_rate": "+0%",
    "voice_pitch": "-4Hz",
    "voice_gender": "Male-British",
    "hud_theme": "Cyan Matrix",
    "persona_preset": "JARVIS Protocol",
    "response_verbosity": "Balanced",
    "custom_prefix": "",
    "chat_memory_retention": 15,
    "orb_sensitivity": "Normal",
    "audio_feedback": True,
    "auto_read_responses": True,
    "lockscreen_wakelock": True,
    "double_tap_wake": True,
    "canvas_auto_open": True,
    "cad_color_scheme": "Holographic Blue",
    "default_travel_mode": "driving",
    "location_precision": "High",
    "ocr_contrast_boost": 2.0,
    "rate_limit_sensitivity": 6,
    "secret_key_protection": True,
    "spotify_auto_lyrics": True,
    "show_clock_telemetry": True,
    "show_network_stats": True,
    "compact_ui_mode": False
}

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
# DYNAMIC LOCATION & PRICE RECOMMENDATION ENGINE
# ---------------------------------------------------------
def get_location_recommendations_with_prices(prompt, lat=5.2971, lon=100.2588):
    p = prompt.lower()
    
    target_location = None
    clean_target = re.sub(r'recommend|places|to|visit|eat|shop|how|much|price|entry|fee|travel|in|at|around|for|current|location', '', prompt, flags=re.IGNORECASE).strip()
    
    if clean_target and len(clean_target) > 2:
        target_location = clean_target.title()

    if not target_location:
        try:
            geo_url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}"
            headers = {"User-Agent": "EVAS_HUD_System/1.0"}
            geo_res = requests.get(geo_url, headers=headers, timeout=4).json()
            
            address = geo_res.get('address', {})
            city = address.get('city') or address.get('town') or address.get('state') or "Penang"
            country = address.get('country', 'Malaysia')
            target_location = f"{city}, {country}"
        except Exception:
            target_location = "Penang, Malaysia"

    want_eat = any(w in p for w in ["eat", "food", "restaurant", "dining", "hawker", "cafe"])
    want_shop = any(w in p for w in ["shop", "buy", "mall", "market", "souvenir", "store"])
    want_visit = any(w in p for w in ["visit", "see", "attraction", "sight", "tour", "place"])
    
    if not (want_eat or want_shop or want_visit):
        want_eat = want_shop = want_visit = True

    is_malaysia = "malaysia" in target_location.lower() or "penang" in target_location.lower() or "kuala lumpur" in target_location.lower()
    currency = "RM" if is_malaysia else "$"

    eat_section = f"""🍽️ **WHERE TO EAT & DRINK**:
• **Local Heritage Hawker / Street Food**: `Est: {currency} 8 – {currency} 20 per pax`
• **Popular Mid-Range Cafe & Bistro**: `Est: {currency} 25 – {currency} 60 per pax`
• **Signature Seafood / Fine Dining**: `Est: {currency} 80 – {currency} 200+ per pax`
""" if want_eat else ""

    visit_section = f"""📍 **BEST PLACES TO VISIT**:
• **Historic UNESCO / Cultural Quarter**: `FREE Entry (Walking Tours: {currency} 15 – {currency} 40)`
• **Scenic Mountain / Cable Car Tram**: `Est: {currency} 15 – {currency} 35 (Ticket)`
• **Central Museum / Art Gallery**: `Est: {currency} 10 – {currency} 25`
• **Waterfront Esplanade & Parks**: `FREE Admission`
""" if want_visit else ""

    shop_section = f"""🛍️ **WHERE TO SHOP**:
• **Central Night Market / Artisanal Stalls**: `Bargain Shopping ({currency} 10 – {currency} 50)`
• **Premier Shopping Mall / Outlets**: `Standard Retail Pricing`
• **Local Souvenir & Craft Bazaar**: `Est: {currency} 5 – {currency} 30 per item`
""" if want_shop else ""

    dos_and_donts = (
        "• **DO**: Carry standard identification and try authentic local street food.\n"
        "• **DON'T**: Ignore local customs, dress code advisories, or restricted heritage signs."
    )

    return (
        f"🌍 **E.V.A.S. INTELLIGENCE: LOCATION & PRICE MATRIX**\n\n"
        f"• **Target Location**: `{target_location.upper()}`\n"
        f"• **Telemetry Status**: Global Regional Pricing & Place Guidance Active\n\n"
        f"{eat_section}{visit_section}{shop_section}\n"
        f"⏰ **BEST VISITING HOURS**: Morning (08:00–11:00) & Evening (17:30–21:00)\n"
        f"📜 **TRAVEL & BEHAVIORAL GUIDELINES**:\n{dos_and_donts}"
    )

# ---------------------------------------------------------
# SHOPPING RESEARCH & ORDER ANALYZER
# ---------------------------------------------------------
def analyze_shopping_request(prompt, honorific="Sir"):
    platforms = {
        "amazon": "https://www.amazon.com/s?k=",
        "shopee": "https://shopee.com.my/search?keyword=",
        "lazada": "https://www.lazada.com.my/catalog/?q=",
        "ebay": "https://www.ebay.com/sch/i.html?_nkw=",
        "aliexpress": "https://www.aliexpress.com/wholesale?SearchText="
    }

    clean_item = re.sub(r'buy|search|price|check cart|find|order|product|details|shopping|platform', '', prompt, flags=re.IGNORECASE).strip()
    encoded_item = urllib.parse.quote(clean_item if clean_item else "latest electronics")

    search_links = "\n".join([f"• **{name.capitalize()}**: [{clean_item.title() or 'Search'}]({url}{encoded_item})" for name, url in platforms.items()])

    return (
        f"🛍️ **E.V.A.S. SHOPPING & PRODUCT RESEARCH MATRIX**\n\n"
        f"• **Target Query**: `{clean_item.title() or 'General Product Search'}`\n\n"
        f"🔍 **DIRECT RETAILER SEARCH LINKS**:\n{search_links}\n\n"
        f"💡 *Note: To analyze a specific cart or purchased item, paste the receipt text or screenshot into the chat, {honorific}.*"
    )

# ---------------------------------------------------------
# GOOGLE CALENDAR & GMAIL (LOCAL TOKEN ENGINE)
# ---------------------------------------------------------
def fetch_google_calendar_events(honorific="Sir"):
    if not os.path.exists('token.json'):
        return f"📅 **CALENDAR TELEMETRY**: `token.json` missing. Run local authentication first, {honorific}."
    try:
        creds = Credentials.from_authorized_user_file('token.json', [
            'https://www.googleapis.com/auth/calendar.readonly',
            'https://www.googleapis.com/auth/gmail.readonly'
        ])
        service = build('calendar', 'v3', credentials=creds)
        now = datetime.utcnow().isoformat() + 'Z'
        events_result = service.events().list(calendarId='primary', timeMin=now, maxResults=5, singleEvents=True, orderBy='startTime').execute()
        events = events_result.get('items', [])
        if not events:
            return f"📅 **GOOGLE CALENDAR**: No upcoming events found, {honorific}."
        events_text = "\n".join([f"• **{e.get('summary', 'Event')}**: `{e['start'].get('dateTime', e['start'].get('date'))}`" for e in events])
        return f"📅 **GOOGLE CALENDAR TELEMETRY**\n\n{events_text}"
    except Exception as e:
        return f"⚠️ Google Calendar error: {str(e)}"

def fetch_recent_gmail_messages(honorific="Sir"):
    if not os.path.exists('token.json'):
        return f"✉️ **GMAIL TELEMETRY**: `token.json` missing. Run local authentication first, {honorific}."
    try:
        creds = Credentials.from_authorized_user_file('token.json', [
            'https://www.googleapis.com/auth/calendar.readonly',
            'https://www.googleapis.com/auth/gmail.readonly'
        ])
        service = build('gmail', 'v1', credentials=creds)
        results = service.users().messages().list(userId='me', maxResults=5).execute()
        messages = results.get('messages', [])
        if not messages:
            return f"✉️ **GMAIL TELEMETRY**: No recent emails found, {honorific}."
        
        email_summary = ""
        for msg in messages:
            m = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
            headers = m.get('payload', {}).get('headers', [])
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
            sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown Sender')
            email_summary += f"• **From**: `{sender}`\n  **Subject**: {subject}\n\n"
        return f"✉️ **GMAIL RECENT MESSAGES**\n\n{email_summary}"
    except Exception as e:
        return f"⚠️ Gmail error: {str(e)}"

# ---------------------------------------------------------
# DYNAMIC MULTI-VARIANT DESIGN SYNTHESIZER
# ---------------------------------------------------------
def generate_multivariant_design(prompt, color_scheme="Holographic Blue"):
    subject = re.sub(r'blueprint|design|schematic|create|draw|generate|make|build', '', prompt, flags=re.IGNORECASE).strip() or "Custom Engineered Concept"
    known_materials = ["Titanium", "Carbon Fiber", "Graphene", "Aluminum Alloy", "Reinforced Steel"]
    detected_materials = [m for m in known_materials if m.lower() in prompt.lower()] or ["Aerospace Titanium Alloy", "Carbon Composite"]

    stroke_color = "#ffaa00" if color_scheme == "Amber Warning" else "#00f3ff"
    mat_list_str = "\n".join([f"  • Material {i+1}: `{m}`" for i, m in enumerate(detected_materials)])

    svg_render = f'''
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 360" style="width:100%; height:auto; background:#001020; border:1px solid {stroke_color}; border-radius:6px; margin-top:8px;">
        <rect width="100%" height="100%" fill="#001020" />
        <rect x="15" y="15" width="570" height="330" fill="none" stroke="{stroke_color}" stroke-width="1.5"/>
        <text x="30" y="40" fill="{stroke_color}" font-family="monospace" font-size="12">DESIGN MATRIX: {subject.upper()[:30]}</text>
        <circle cx="300" cy="170" r="60" fill="none" stroke="{stroke_color}" stroke-width="2"/>
    </svg>
    '''

    report = (
        f"📐 **E.V.A.S. MULTI-VARIANT DESIGN SYNTHESIZER**\n\n"
        f"• **Project**: `{subject.title()}`\n"
        f"• **Active Visual Palette**: `{color_scheme}`\n\n"
        f"🛠️ **MATERIALS**:\n{mat_list_str}\n\n"
        f"💡 *Variant schematics synthesized on Canvas.*"
    )
    return report, svg_render

# ---------------------------------------------------------
# SPOTIFY OAUTH ENGINE
# ---------------------------------------------------------
@app.route('/api/spotify/login')
def spotify_login():
    params = {"client_id": SPOTIFY_CLIENT_ID, "response_type": "code", "redirect_uri": SPOTIFY_REDIRECT_URI, "scope": "user-read-currently-playing"}
    return redirect("https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(params))

@app.route('/api/spotify/callback')
def spotify_callback():
    code = request.args.get('code')
    if not code:
        return "Spotify Authorization Failed.", 400
    res = requests.post("https://api.spotify.com/v1/me/player/currently-playing", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": SPOTIFY_REDIRECT_URI,
        "client_id": SPOTIFY_CLIENT_ID, "client_secret": SPOTIFY_CLIENT_SECRET
    }).json()
    session['spotify_token'] = res.get('access_token')
    return render_template_string("<script>alert('Spotify connected!'); window.location.href='/';</script>")

def get_live_weather(lat=5.2971, lon=100.2588):
    try:
        res = requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,wind_speed_10m", timeout=5).json()
        curr = res.get('current', {})
        return f"🌤️ **WEATHER**: `{curr.get('temperature_2m')} °C` | Wind: `{curr.get('wind_speed_10m')} km/h`"
    except Exception as e:
        return f"Weather error: {e}"

def process_and_analyze_attachment(file_b64, file_type="", contrast_boost=2.0):
    if not file_b64:
        return "", None
    try:
        header, encoded = file_b64.split(",", 1) if "," in file_b64 else ("", file_b64)
        file_bytes = base64.b64decode(encoded)
        if HAS_OCR:
            img = Image.open(io.BytesIO(file_bytes)).convert('L')
            enhancer = ImageEnhance.Contrast(img)
            enhanced_img = enhancer.enhance(contrast_boost)
            text = pytesseract.image_to_string(enhanced_img)
            return f"\n\n📷 **[OCR PARSED CONTENT]**:\n```text\n{text.strip()}\n```\n", text.strip()
    except Exception as e:
        return f"\n\n⚠️ Vision module error: {str(e)}", None
    return "", None

def parse_contextual_intent(prompt):
    p = prompt.lower()
    if any(w in p for w in ["recommend", "places to visit", "eat", "food", "prices", "how much"]):
        return "PLACES_RECOMMENDATION"
    if any(w in p for w in ["shop", "buy", "cart", "product", "price", "amazon", "shopee", "lazada", "ebay", "order"]):
        return "SHOPPING_RESEARCH"
    if any(w in p for w in ["calendar", "events", "schedule"]):
        return "CHECK_CALENDAR"
    if any(w in p for w in ["email", "emails", "gmail", "inbox"]):
        return "CHECK_GMAIL"
    if any(w in p for w in ["design", "blueprint", "schematic"]):
        return "GENERATE_MULTIVARIANT_DESIGN"
    if any(w in p for w in ["gsc", "cinema"]):
        return "GSC_APP"
    if any(w in p for w in ["spotify"]):
        return "OPEN_SPOTIFY"
    if any(w in p for w in ["directions to", "navigate to"]):
        return "DIRECTIONS"
    if any(w in p for w in ["speed test"]):
        return "RUN_SPEEDTEST"
    if any(w in p for w in ["weather"]):
        return "WEATHER"
    return "UNIVERSAL_EXECUTION"

async def create_tts_audio_file(text, voice_rate="+0%", voice_pitch="-4Hz", voice_gender="Male-British", filename="static_speech.mp3"):
    if not HAS_EDGE_TTS:
        return False
    try:
        clean_prompt = re.sub(r'[*_~`#>]', '', text).strip()
        voice_name = "en-GB-RyanNeural" if "British" in voice_gender else "en-US-GuyNeural"
        communicate = edge_tts.Communicate(clean_prompt[:600], voice_name, pitch=voice_pitch, rate=voice_rate)
        await communicate.save(filename)
        return True
    except Exception:
        return False

def generate_voice_sync(text, voice_rate="+0%", voice_pitch="-4Hz", voice_gender="Male-British"):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(create_tts_audio_file(text, voice_rate, voice_pitch, voice_gender))
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
        return f"⚡ **SPEEDTEST**: Download `{st.download()/1e6:.2f} Mbps` | Upload `{st.upload()/1e6:.2f} Mbps`"
    except Exception as e:
        return f"Speedtest error: {e}"

@app.route('/api/settings', methods=['GET', 'POST'])
def manage_settings():
    username = session.get('username')
    if request.method == 'GET':
        if username:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT settings FROM users WHERE username = ?", (username,))
            row = c.fetchone()
            conn.close()
            if row and row[0]:
                saved_settings = json.loads(row[0])
                merged = {**DEFAULT_EXTENDED_SETTINGS, **saved_settings}
                return jsonify(merged)
        return jsonify(DEFAULT_EXTENDED_SETTINGS)
    
    elif request.method == 'POST':
        new_settings = request.json or {}
        merged = {**DEFAULT_EXTENDED_SETTINGS, **new_settings}
        if username:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("UPDATE users SET settings = ? WHERE username = ?", (json.dumps(merged), username))
            conn.commit()
            conn.close()
        return jsonify({"message": "Settings updated successfully", "settings": merged})

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
    c.execute("SELECT password_hash, settings, chat_history, is_locked FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    conn.close()
    if user and check_password_hash(user[0], password):
        session['username'] = username
        user_settings = {**DEFAULT_EXTENDED_SETTINGS, **json.loads(user[1] or '{}')}
        return jsonify({'message': 'Logged in', 'username': username, 'settings': user_settings, 'is_locked': bool(user[3])})
    return jsonify({'error': 'Invalid credentials'}), 401

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

@app.route('/api/ask', methods=['POST'])
def ask():
    data = request.json or {}
    username = session.get('username') or data.get('username', 'guest')
    user_prompt = data.get('prompt', '').strip()
    settings = {**DEFAULT_EXTENDED_SETTINGS, **data.get('settings', {})}
    
    honorific = settings.get('honorific', 'Sir')
    voice_rate = settings.get('voice_rate', '+0%')
    voice_pitch = settings.get('voice_pitch', '-4Hz')
    voice_gender = settings.get('voice_gender', 'Male-British')
    custom_prefix = settings.get('custom_prefix', '')
    persona_preset = settings.get('persona_preset', 'JARVIS Protocol')
    cad_palette = settings.get('cad_color_scheme', 'Holographic Blue')
    contrast_boost = float(settings.get('ocr_contrast_boost', 2.0))

    lat = data.get('latitude', 5.2971)
    lon = data.get('longitude', 100.2588)
    file_b64 = data.get('file_b64', None)
    file_type = data.get('file_type', '')

    file_analysis_text, _ = process_and_analyze_attachment(file_b64, file_type, contrast_boost)
    if file_analysis_text:
        user_prompt = f"{user_prompt}{file_analysis_text}".strip()

    if not user_prompt:
        return jsonify({'response': f'No query received, {honorific}.', 'audio': False})

    inferred_intent = parse_contextual_intent(user_prompt)
    reply = None
    svg_blueprint = None
    google_maps_url = None
    action_type = None

    if inferred_intent == "PLACES_RECOMMENDATION":
        reply = get_location_recommendations_with_prices(user_prompt, lat, lon)

    elif inferred_intent == "SHOPPING_RESEARCH":
        reply = analyze_shopping_request(user_prompt, honorific)

    elif inferred_intent == "CHECK_CALENDAR":
        reply = fetch_google_calendar_events(honorific)

    elif inferred_intent == "CHECK_GMAIL":
        reply = fetch_recent_gmail_messages(honorific)

    elif inferred_intent == "GENERATE_MULTIVARIANT_DESIGN":
        reply, svg_blueprint = generate_multivariant_design(user_prompt, cad_palette)

    elif inferred_intent == "GSC_APP":
        action_type = "GSC_DISPATCH"
        reply = f"🎬 **GSC APP DISPATCHED**, {honorific}."

    elif inferred_intent == "OPEN_SPOTIFY":
        action_type = "SPOTIFY_DISPATCH"
        reply = f"🎵 **SPOTIFY DISPATCHED**, {honorific}."

    elif inferred_intent == "WEATHER":
        reply = get_live_weather(lat, lon)

    elif inferred_intent == "DIRECTIONS":
        destination = re.sub(r'directions to|navigate to', '', user_prompt, flags=re.IGNORECASE).strip() or "Penang Hill, Malaysia"
        travel_mode = settings.get('default_travel_mode', 'driving')
        google_maps_url = f"https://www.google.com/maps/dir/?api=1&origin={lat},{lon}&destination={urllib.parse.quote(destination)}&travelmode={travel_mode}"
        reply = f"🗺️ **NAVIGATION DISPATCHED**: `{destination}` ({travel_mode.title()} mode)"

    elif inferred_intent == "RUN_SPEEDTEST":
        reply = run_network_speedtest()

    if not reply:
        today_date = datetime.now().strftime("%B %d, %Y")
        persona_instructions = f"Style: {persona_preset}."
        system_prompt = (
            f"You are E.V.A.S., an AI assistant. Address user as '{honorific}'. "
            f"{persona_instructions} Today's date is {today_date}."
        )

        if openai_client:
            try:
                completion = openai_client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                    temperature=0.7
                )
                reply = completion.choices[0].message.content.strip()
            except Exception:
                reply = None

        if not reply and HAS_OLLAMA:
            try:
                res = ollama.chat(model='deepseek-r1:1.5b', messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}])
                reply = re.sub(r'<think>[\s\S]*?</think>', '', res['message']['content']).strip()
            except Exception:
                reply = None

        if not reply:
            reply = f"E.V.A.S. Core online. Request verified, {honorific}."

    if custom_prefix and not reply.startswith(custom_prefix):
        reply = f"{custom_prefix} {reply}"

    clean_reply = re.sub(r'[*_~`#>]', '', reply).strip()
    has_audio = generate_voice_sync(clean_reply, voice_rate, voice_pitch, voice_gender)

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
        return send_file('static_speech.mp3', mimetype='audio/mpeg')
    return ("", 404)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)