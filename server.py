from flask import Flask, render_template_string, request, jsonify, send_file, make_response, send_from_directory
import os
import re
import json
import random
import threading
import time
import requests
import urllib.parse

# Safe imports for external tools
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

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

MEMORY_FILE = "evas_memory.json"
GENERATED_FILES_DIR = "generated_files"
os.makedirs(GENERATED_FILES_DIR, exist_ok=True)

EVAS_BUILD_VERSION = "6.7.0-STABLE-RENDER-ENGINE"
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
    """Safely queries Google Search results without crashing on missing libraries."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    encoded_query = urllib.parse.quote(query)
    google_url = f"https://www.google.com/search?q={encoded_query}&hl=en"
    
    extracted_data = []
    try:
        response = requests.get(google_url, headers=headers, timeout=5)
        if response.status_code == 200 and HAS_BS4:
            soup = BeautifulSoup(response.text, "html.parser")
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
        print(f"[GOOGLE SEARCH ENGINE LOG]: {e}")
    return None

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

    return "UNIVERSAL_EXECUTION"

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

@app.route('/api/version')
def get_version():
    return jsonify({"version": EVAS_BUILD_VERSION, "study_mode_active": IS_STUDY_MODE_ACTIVE})

@app.route('/api/ask', methods=['POST'])
def ask():
    global IS_STUDY_MODE_ACTIVE
    data = request.json or {}
    user_prompt = data.get('prompt', '').strip()
    honorific = data.get('honorific', 'Sir')
    is_dnd = data.get('dnd_mode', False)

    if not user_prompt:
        return jsonify({'response': f'No command received, {honorific}.', 'audio': False})

    inferred_intent = parse_contextual_intent(user_prompt)
    reply = None

    if inferred_intent == "TOGGLE_STUDY_MODE_ON":
        reply = f"🎓 **STUDY MODE ACTIVATED**. Google Search integration enabled."

    elif inferred_intent == "TOGGLE_STUDY_MODE_OFF":
        reply = f"🎓 **STUDY MODE DISABLED**."

    elif inferred_intent == "STUDY_ASSISTANT":
        google_context = perform_direct_google_search(user_prompt)

        teacher_prompt = (
            "You are E.V.A.S. Study Companion. Use the retrieved Google search telemetry below to generate clear classroom-style explanations or notes in BBC Bitesize format."
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

    has_audio = False
    if not is_dnd and HAS_EDGE_TTS:
        try:
            asyncio.run(generate_voice_file(clean_text, "en-GB-RyanNeural", "-3Hz", "+2%"))
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
    if HAS_EDGE_TTS:
        communicate = edge_tts.Communicate(text, voice, pitch=pitch, rate=rate)
        await communicate.save("static_speech.mp3")

@app.route('/api/audio')
def get_audio():
    if os.path.exists('static_speech.mp3'):
        return send_file('static_speech.mp3', mimetype='audio/mpeg')
    return ("", 404)

if __name__ == '__main__':
    # Render binds dynamically to port specified in environment
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)