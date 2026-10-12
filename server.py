from flask import Flask, render_template_string, request, jsonify, send_file, make_response
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
GLOBAL_NEWS_CACHE = []

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

def fetch_accurate_weather(lat, lon, location_name="Current Location"):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m&timezone=auto"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json().get('current', {})
            temp = data.get('temperature_2m', 'N/A')
            feels = data.get('apparent_temperature', 'N/A')
            humidity = data.get('relative_humidity_2m', 'N/A')
            wind = data.get('wind_speed_10m', 'N/A')
            
            wmo_codes = {
                0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
                45: "Foggy", 51: "Light drizzle", 61: "Slight rain", 63: "Moderate rain",
                65: "Heavy rain", 80: "Slight rain showers", 95: "Thunderstorm"
            }
            condition = wmo_codes.get(data.get('weather_code', 0), "Clear")

            return (f"Live Meteorological Telemetry [{location_name} @ {lat:.4f}, {lon:.4f}]:\n"
                    f"• Condition: {condition}\n"
                    f"• Temperature: {temp}°C (Feels like {feels}°C)\n"
                    f"• Humidity: {humidity}%\n"
                    f"• Wind Speed: {wind} km/h")
    except Exception as e:
        print(f"[WEATHER API ERROR]: {e}")
    return None

def search_general_knowledge(query):
    try:
        results = list(DDGS().text(query, max_results=6))
        if results:
            snippets = [f"• {res['title']}: {res['body']}" for res in results if 'body' in res]
            return f"Comprehensive analysis on '{query}':\n\n" + "\n\n".join(snippets[:4])
        return None
    except Exception:
        return None

def sanitize_text_for_speech(text):
    """Strips markdown, code block ticks, hash headers, and symbols so JARVIS speaks plain words."""
    clean = re.sub(r'```[\s\S]*?```', ' Code block omitted for brevity. ', text)
    clean = re.sub(r'[*_~`#\-•|>]+', ' ', clean)
    clean = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', clean)
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

@app.route('/manifest.json')
def manifest():
    if os.path.exists('manifest.json'):
        return send_file('manifest.json')
    return jsonify({})

@app.route('/sw.js')
def service_worker():
    if os.path.exists('sw.js'):
        return send_file('sw.js')
    return ("", 204)

@app.route('/api/request_2fa', methods=['POST'])
def request_2fa():
    otp_code = str(random.randint(100000, 999999))
    return jsonify({'status': 'sent', 'demo_code': otp_code})

@app.route('/api/get_news', methods=['GET'])
def get_news():
    if GLOBAL_NEWS_CACHE:
        return jsonify({'status': 'success', 'news': GLOBAL_NEWS_CACHE})
    else:
        try:
            results = list(DDGS().text("breaking world global news headlines today", max_results=5))
            news = [f"📰 [{res['title']}] - {res['body']}" for res in results]
            return jsonify({'status': 'success', 'news': news})
        except Exception:
            return jsonify({'status': 'error', 'news': ["Global news service temporarily offline."]})

@app.route('/api/diagnostics', methods=['GET'])
def run_diagnostics():
    """System diagnostic worker: Scans for anomalies and executes self-healing protocols."""
    anomalies = []
    status_summary = {}

    # 1. Ollama LLM Engine Check
    if HAS_OLLAMA:
        try:
            ollama.list()
            status_summary['ollama'] = 'ONLINE'
        except Exception as e:
            status_summary['ollama'] = 'OFFLINE / ANOMALY'
            anomalies.append(f"Ollama local service unresponsive: {str(e)}")
    else:
        status_summary['ollama'] = 'NOT INSTALLED (FALLBACK ACTIVE)'

    # 2. Weather Telemetry Check
    try:
        w_check = requests.get("https://api.open-meteo.com/v1/forecast?latitude=5.2971&longitude=100.2588&current=temperature_2m", timeout=3)
        if w_check.status_code == 200:
            status_summary['weather_api'] = 'ONLINE'
        else:
            status_summary['weather_api'] = f'DEGRADED (HTTP {w_check.status_code})'
            anomalies.append(f"Weather API returned status code {w_check.status_code}")
    except Exception as e:
        status_summary['weather_api'] = 'OFFLINE'
        anomalies.append(f"Weather API request failed: {str(e)}")

    # 3. DuckDuckGo Search Engine Check
    try:
        search_test = list(DDGS().text("ping test", max_results=1))
        status_summary['search_engine'] = 'ONLINE' if search_test else 'NO RESULTS'
    except Exception as e:
        status_summary['search_engine'] = 'DEGRADED'
        anomalies.append(f"DuckDuckGo search error: {str(e)}")

    # 4. Storage & Memory Diagnostics (Self-Healing)
    try:
        if not os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
                f.write("System memory archive initialized.\n")
            anomalies.append("Memory file missing. Self-healed by initializing new memory archive.")
        status_summary['memory_archive'] = 'VERIFIED'
    except Exception as e:
        status_summary['memory_archive'] = 'READ/WRITE ERROR'
        anomalies.append(f"Memory storage failure: {str(e)}")

    # 5. Disk Space Diagnostics
    try:
        total, used, free = shutil.disk_usage("/")
        free_gb = free / (1024 ** 3)
        status_summary['free_disk'] = f"{free_gb:.2f} GB"
        if free_gb < 1.0:
            anomalies.append(f"Low disk space detected: {free_gb:.2f} GB remaining.")
    except Exception:
        status_summary['free_disk'] = 'UNKNOWN'

    diagnostic_report = (
        f"Diagnostic Scan Complete, Sir.\n\n"
        f"• Local LLM Engine: {status_summary.get('ollama')}\n"
        f"• Weather Telemetry: {status_summary.get('weather_api')}\n"
        f"• Search Engine Link: {status_summary.get('search_engine')}\n"
        f"• Memory Archive: {status_summary.get('memory_archive')}\n"
        f"• Disk Space Remaining: {status_summary.get('free_disk')}\n\n"
    )

    if anomalies:
        diagnostic_report += "⚠️ Detected Anomalies:\n" + "\n".join([f"  - {a}" for a in anomalies])
    else:
        diagnostic_report += "✅ All subroutines and neural links operating at optimal capacity. Zero anomalies detected."

    return jsonify({
        'status': 'success',
        'report': diagnostic_report,
        'has_anomalies': len(anomalies) > 0,
        'anomalies_list': anomalies
    })

@app.route('/api/run_python', methods=['POST'])
def run_python():
    data = request.json or {}
    code_str = data.get('code', '')
    if not code_str:
        return jsonify({'output': 'No code provided.'})
        
    old_stdout = sys.stdout
    redirected_output = sys.stdout = io.StringIO()
    try:
        exec(code_str, {'__builtins__': __builtins__})
        output = redirected_output.getvalue()
    except Exception as e:
        output = f"Execution Error: {str(e)}"
    finally:
        sys.stdout = old_stdout
        
    return jsonify({'output': output if output else 'Code executed successfully with no print output.'})

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
    battery_info = data.get('battery', 'Battery Normal')
    mode_transport = data.get('transport_mode', 'car')
    is_dnd = data.get('dnd_mode', False)
    device_type = data.get('device_type', 'desktop')

    if not user_prompt and not images and not files:
        return jsonify({'response': f'No command or payload received, {honorific}.', 'audio': False})

    cmd_lower = user_prompt.lower()
    reply = None
    media_action = None
    nav_destination = None
    ev_chargers = False
    c3po_nav_text = None
    is_shutdown = False
    trigger_blackout = False
    disable_blackout = False
    disable_navigation = False
    app_launch_intent = None
    activate_map = False

    # Mode Exit Command Handlers
    if "disable blackout" in cmd_lower or "exit blackout" in cmd_lower or "turn off blackout" in cmd_lower or "disable stealth" in cmd_lower:
        disable_blackout = True
        reply = f"Job done, {honorific}. Disabling stealth blackout and restoring full HUD visual arrays."

    elif "disable navigation" in cmd_lower or "exit navigation" in cmd_lower or "turn off navigation" in cmd_lower or "close map" in cmd_lower or "hide map" in cmd_lower:
        disable_navigation = True
        activate_map = False
        reply = f"Job done, {honorific}. Deactivating GPS navigation overlay and returning to standard diagnostic view."

    elif "diagnostics" in cmd_lower or "check anomalies" in cmd_lower or "scan system" in cmd_lower or "run diagnostic" in cmd_lower:
        diag_res = run_diagnostics().get_json()
        reply = diag_res.get('report', f'Diagnostic scan finished, {honorific}.')

    elif "weather" in cmd_lower or "temperature" in cmd_lower or "forecast" in cmd_lower:
        if lat and lon:
            reply = fetch_accurate_weather(lat, lon, "Your Current Position")
        else:
            reply = fetch_accurate_weather(5.2971, 100.2588, location)

    elif "show map" in cmd_lower or "activate map" in cmd_lower or "open map" in cmd_lower:
        activate_map = True
        reply = f"Activating tactical GPS HUD map overlay now, {honorific}."

    elif "direction" in cmd_lower or "navigate" in cmd_lower or "route" in cmd_lower or "map to" in cmd_lower:
        activate_map = True
        dest_match = re.sub(r'get directions to|directions to|navigate to|map to|take me to', '', user_prompt, flags=re.IGNORECASE).strip()
        nav_destination = dest_match if dest_match else "Target Destination"
        ev_chargers = (mode_transport == 'ev')
        
        c3po_nav_text = f"Oh my! Computing optimal GPS route for {mode_transport.upper()} mode to {nav_destination}. Proceeding now, Master!"
        reply = f"Full GPS navigation locked on {nav_destination}. C-3PO routing initiated, {honorific}."

    elif "news" in cmd_lower or "headlines" in cmd_lower:
        if GLOBAL_NEWS_CACHE:
            reply = "Here are the latest world headlines:\n\n" + "\n\n".join(GLOBAL_NEWS_CACHE[:4])
        else:
            reply = f"Fetching real-time global news feed now, {honorific}."
    elif "blackout" in cmd_lower or "black out" in cmd_lower or "stealth mode" in cmd_lower:
        trigger_blackout = True
        reply = f"Engaging HUD blackout mode. Terminal core remaining active, {honorific}."
    elif "shut down" in cmd_lower or "shutdown" in cmd_lower:
        is_shutdown = True
        reply = f"Initiating system shutdown. Entering standby mode, {honorific}."

    elif "play" in cmd_lower and ("spotify" in cmd_lower or "song" in cmd_lower or "music" in cmd_lower):
        song = re.sub(r'play|on spotify|spotify|song|music', '', user_prompt, flags=re.IGNORECASE).strip()
        media_action = {"type": "spotify", "query": song}
        reply = f"Streaming '{song}' on Spotify, {honorific}."
    elif "play" in cmd_lower or "youtube" in cmd_lower:
        yt_query = re.sub(r'play|on youtube|youtube|video', '', user_prompt, flags=re.IGNORECASE).strip()
        media_action = {"type": "youtube", "query": yt_query}
        reply = f"Loading YouTube video for '{yt_query}', {honorific}."

    elif "open" in cmd_lower or "launch" in cmd_lower:
        target_app = cmd_lower.replace("open", "").replace("launch", "").strip()
        app_schemes = {
            "spotify": "spotify://", "youtube": "vnd.youtube://", "maps": "https://maps.google.com",
            "google maps": "comgooglemaps://", "chrome": "googlechrome://", "whatsapp": "whatsapp://"
        }
        if device_type == "mobile" and target_app in app_schemes:
            app_launch_intent = app_schemes[target_app]
            reply = f"Launching {target_app} on mobile device, {honorific}."
        else:
            if HAS_PYAUTOGUI:
                try:
                    subprocess.Popen(f"start {target_app}", shell=True)
                except Exception:
                    pass
            reply = f"Launching {target_app} on host system, {honorific}."

    file_context_str = ""
    if files:
        file_snippets = []
        for f in files:
            file_name = f.get('name', 'Attachment')
            file_content = f.get('content', '')
            file_snippets.append(f"--- [ATTACHED FILE: {file_name}] ---\n{file_content}\n")
        file_context_str = "\n".join(file_snippets)

    if not reply:
        user_memory = get_user_memory()
        system_instructions = (
            "You are J.A.R.V.I.S., a hyper-intelligent AI assistant created by Stark Industries. "
            "Examine all user requests, homework problems, math equations, attached documents, and photo image uploads with complete accuracy. "
            "ACADEMIC & HOMEWORK GUIDELINES: Provide step-by-step educational breakdowns, formula definitions, and clear final solutions. "
            "PYTHON SCRIPTING: When generating Python scripts, provide complete runnable code blocks inside ```python ``` tags with clear line-by-line explanations. "
            "BLUEPRINT GRAPHICS: If asked to draft or design a schematic or blueprint, generate valid SVG vector graphics wrapped in <svg>...</svg> tags. "
            f"Always finish your response addressing the user strictly as {honorific}. "
            f"Device Telemetry: [{battery_info}]. Location: [{location}]. "
            f"\n[USER MEMORY ARCHIVE]:\n{user_memory}"
        )

        full_prompt = user_prompt
        if file_context_str:
            full_prompt = f"{file_context_str}\n\nUser Question/Instruction:\n{user_prompt if user_prompt else 'Analyze the attached file and solve any homework questions present.'}"

        if HAS_OLLAMA:
            try:
                model_to_use = 'llava' if images else 'qwen2.5:0.5b'
                message_obj = {"role": "user", "content": full_prompt}
                if images:
                    message_obj["images"] = images

                response = ollama.chat(
                    model=model_to_use,
                    messages=[
                        {"role": "system", "content": system_instructions},
                        message_obj
                    ],
                    options={"num_predict": 700, "temperature": 0.2},
                    keep_alive=-1
                )
                reply = response['message']['content'].strip()
            except Exception:
                reply = None

        if not reply:
            ai_answer = search_general_knowledge(full_prompt)
            if ai_answer:
                reply = ai_answer
            else:
                reply = f"I have thoroughly processed your request regarding '{user_prompt if user_prompt else 'the attached payload'}'. All neural pathways nominal, {honorific}."

    clean_text = re.sub(r'[*_~`]', '', reply).strip()
    clean_text = re.sub(rf'(?:,\s*)?\b(?:Sir|Ma\'am|Master)\b(?:\.|\s*)*$', '', clean_text, flags=re.IGNORECASE).strip()
    
    if not c3po_nav_text:
        clean_text = f"{clean_text.rstrip('.,!')}, {honorific}."

    speech_ready_text = sanitize_text_for_speech(clean_text)

    has_audio = False
    if not is_dnd:
        try:
            target_text = c3po_nav_text if c3po_nav_text else speech_ready_text
            voice = "en-GB-ThomasNeural" if c3po_nav_text else "en-GB-RyanNeural"
            pitch = "+4Hz" if c3po_nav_text else "-3Hz"
            rate = "+10%" if c3po_nav_text else "+2%"
            
            asyncio.run(generate_voice_file(target_text, voice, pitch, rate))
            has_audio = True
        except Exception as e:
            print(f"[AUDIO GENERATION ERROR]: {e}")
            has_audio = False

    return jsonify({
        'response': clean_text, 
        'audio': has_audio, 
        'c3po_text': c3po_nav_text,
        'media_action': media_action,
        'nav_destination': nav_destination,
        'ev_chargers': ev_chargers,
        'is_shutdown': is_shutdown,
        'blackout': trigger_blackout,
        'disable_blackout': disable_blackout,
        'disable_navigation': disable_navigation,
        'app_intent': app_launch_intent,
        'device_type': device_type,
        'activate_map': activate_map
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