from flask import Flask, render_template_string, request, jsonify, send_file, make_response, send_from_directory
import os
import re
import json
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
    from PIL import Image, ImageEnhance, ImageFilter
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

MEMORY_FILE = "evas_memory.json"
GENERATED_FILES_DIR = "generated_files"
os.makedirs(GENERATED_FILES_DIR, exist_ok=True)

EVAS_BUILD_VERSION = "17.0.0-UNIVERSAL-VISION-ENGINE"

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

# ---------------------------------------------------------
# ADVANCED MULTIMODAL IMAGE & FILE ANALYZER
# ---------------------------------------------------------
def process_and_analyze_attachment(file_b64, file_type=""):
    if not file_b64:
        return "", None
    
    try:
        header, encoded = file_b64.split(",", 1) if "," in file_b64 else ("", file_b64)
        file_bytes = base64.b64decode(encoded)
        
        # 1. Image / Screenshot / Homework Diagram Analysis
        if any(img_ext in file_type for img_ext in ["image", ".png", ".jpg", ".jpeg", ".webp", ".bmp"]) or not file_type:
            if HAS_OCR:
                img = Image.open(io.BytesIO(file_bytes)).convert('L') # Convert to grayscale for OCR precision
                
                # Image enhancement pipeline for clear reading of handwritten/small text
                enhancer = ImageEnhance.Contrast(img)
                enhanced_img = enhancer.enhance(2.0)
                
                extracted_text = pytesseract.image_to_string(enhanced_img)
                if not extracted_text.strip():
                    extracted_text = pytesseract.image_to_string(img) # Fallback to raw grayscale
                
                if extracted_text.strip():
                    analysis_summary = (
                        f"\n\n📷 **[E.V.A.S. VISION ENGINE ATTACHMENT PARSED]**\n"
                        f"• **Source Type**: Image / Screenshot / Document Capture\n"
                        f"• **Extracted Data Content**:\n```text\n{extracted_text.strip()}\n```\n"
                    )
                    return analysis_summary, extracted_text.strip()
                
                return "\n\n📷 **[E.V.A.S. VISION ENGINE]**: Image payload received. No legible printed/handwritten text detected.", None
            else:
                return "\n\n⚠️ **[E.V.A.S. VISION ENGINE]**: Image payload received. OCR processing module pending system configuration.", None
        
        # 2. Plain Text / Code / CSV / Document Files
        elif any(doc_ext in file_type for doc_ext in ["text", ".txt", ".py", ".js", ".html", ".css", ".json", ".csv", ".md"]):
            decoded_text = file_bytes.decode('utf-8', errors='ignore')
            analysis_summary = (
                f"\n\n📄 **[E.V.A.S. FILE READER ATTACHMENT PARSED]**\n"
                f"• **Source Type**: Text / Script / Data File (`{file_type}`)\n"
                f"• **Content Payload**:\n```text\n{decoded_text.strip()}\n```\n"
            )
            return analysis_summary, decoded_text.strip()

    except Exception as e:
        print(f"[ATTACHMENT ANALYSIS ERROR]: {e}")
        return f"\n\n⚠️ **[E.V.A.S. VISION ENGINE]**: Failed to parse file payload. Error: `{str(e)}`", None
        
    return "\n\n📄 **[E.V.A.S. FILE READER]**: File payload attached.", None

# ---------------------------------------------------------
# INTENT PARSER & NAVIGATION ENGINE
# ---------------------------------------------------------
def parse_contextual_intent(prompt):
    p = prompt.lower()
    if any(w in p for w in ["directions to", "route to", "navigate to", "map to", "maps to", "take me to", "how to go to", "go to", "destination"]):
        return "DIRECTIONS"
    if any(w in p for w in ["speed test", "test speed", "wifi speed", "connection speed"]):
        return "RUN_SPEEDTEST"
    return "UNIVERSAL_EXECUTION"

# ---------------------------------------------------------
# GOOGLE SEARCH TELEMETRY ENGINE
# ---------------------------------------------------------
def perform_google_search(query):
    results = []
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

# ---------------------------------------------------------
# TTS VOICE ENGINE
# ---------------------------------------------------------
async def create_tts_audio_file(text, filename="static_speech.mp3"):
    if not HAS_EDGE_TTS:
        return False
    try:
        clean_prompt = re.sub(r'[*_~`#>]', '', text).strip()
        if not clean_prompt:
            clean_prompt = "Response completed."
        communicate = edge_tts.Communicate(clean_prompt[:600], "en-GB-RyanNeural", pitch="-3Hz", rate="+2%")
        await communicate.save(filename)
        return True
    except Exception:
        return False

def generate_voice_sync(text):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(create_tts_audio_file(text))
        loop.close()
        return success
    except Exception:
        return False

def run_network_speedtest():
    if not HAS_SPEEDTEST:
        return "⚠️ Speedtest engine module not available on server host."
    try:
        st = speedtest.Speedtest(secure=True)
        st.get_best_server()
        d_mbps = st.download() / 1000000.0
        u_mbps = st.upload() / 1000000.0
        return (
            f"⚡ **LIVE NETWORK DIAGNOSTIC REPORT**\n\n"
            f"• **Download Speed**: `{d_mbps:.2f} Mbps`\n"
            f"• **Upload Speed**: `{u_mbps:.2f} Mbps`\n"
            f"• **Latency / Ping**: `{st.results.ping:.1f} ms`\n"
            f"• **Status**: Connection operational."
        )
    except Exception as e:
        return f"Network test failed: {e}"

# ---------------------------------------------------------
# ROUTES
# ---------------------------------------------------------
@app.route('/')
def home():
    if os.path.exists('index.html'):
        with open('index.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
    else:
        html_content = "<h1>E.V.A.S. Core Active. Upload index.html to view HUD.</h1>"
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

    user_prompt = data.get('prompt', '').strip()
    honorific = data.get('honorific', 'Sir')
    lat = data.get('latitude', None)
    lon = data.get('longitude', None)
    file_b64 = data.get('file_b64', None)
    file_type = data.get('file_type', '')

    file_analysis_text, raw_extracted_ocr = process_and_analyze_attachment(file_b64, file_type)
    
    if file_analysis_text:
        user_prompt = f"{user_prompt}{file_analysis_text}".strip()

    if not user_prompt:
        return jsonify({'response': f'No query or file received, {honorific}.', 'audio': False})

    inferred_intent = parse_contextual_intent(user_prompt)
    reply = None
    google_maps_url = None

    if inferred_intent == "DIRECTIONS":
        destination = re.sub(
            r'directions to|route to|navigate to|map to|maps to|take me to|how to go to|go to|destination', 
            '', 
            user_prompt, 
            flags=re.IGNORECASE
        ).strip()
        if not destination:
            destination = "Penang Hill, Malaysia"
        
        encoded_dest = urllib.parse.quote(destination)
        if lat is not None and lon is not None:
            google_maps_url = f"https://www.google.com/maps/dir/?api=1&origin={lat},{lon}&destination={encoded_dest}&travelmode=driving"
        else:
            google_maps_url = f"https://www.google.com/maps/dir/?api=1&destination={encoded_dest}&travelmode=driving"

        reply = (
            f"🗺️ **DIRECT GOOGLE MAPS NAVIGATION LAUNCHED**\n\n"
            f"• **Destination**: `{destination}`\n"
            f"• **Routing Protocol**: Direct Navigation Mode Enabled\n"
            f"• **Action**: Launching Google Maps with `{destination}` pre-filled, {honorific}."
        )

    elif inferred_intent == "RUN_SPEEDTEST":
        reply = run_network_speedtest()

    if not reply:
        google_search_data = perform_google_search(user_prompt)
        
        system_prompt = (
            f"You are E.V.A.S., an advanced AI assistant. "
            f"Analyze any provided attached files, images, code, or homework text thoroughly. "
            f"Synthesize the Google Search Telemetry results when answering queries. "
            f"Provide direct, clear, step-by-step verified solutions. Address the user as '{honorific}'."
        )

        if HAS_OLLAMA:
            try:
                full_input = f"User Request: {user_prompt}\n\nGoogle Search Telemetry:\n{google_search_data if google_search_data else 'None'}"
                res = ollama.chat(
                    model='deepseek-r1:1.5b',
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": full_input}],
                    options={"num_predict": 1200, "temperature": 0.2}
                )
                raw = res['message']['content'].strip()
                reply = re.sub(r'<think>[\s\S]*?</think>', '', raw).strip()
            except Exception:
                reply = None

        if not reply:
            if file_analysis_text:
                reply = f"### 📝 E.V.A.S. VISION & FILE ANALYSIS COMPLETE:\n{file_analysis_text}\n\n*Analyzed and processed successfully, {honorific}.*"
            elif google_search_data:
                reply = f"### 🌐 GOOGLE SEARCH LIVE TELEMETRY REPORT:\n\n{google_search_data}\n\n*Query processed successfully, {honorific}.*"
            else:
                reply = f"E.V.A.S. Core online. Request **'{user_prompt}'** verified, {honorific}."

    clean_reply = re.sub(r'[*_~`#>]', '', reply).strip()
    has_audio = generate_voice_sync(clean_reply)

    return jsonify({
        'response': clean_reply, 
        'raw_markdown': reply,
        'audio': has_audio,
        'google_maps_url': google_maps_url
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