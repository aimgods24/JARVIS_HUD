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
from duckduckgo_search import DDGS

try:
    from PIL import Image
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

EVAS_BUILD_VERSION = "13.0.0-FILE-VISION-CORE"

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

def extract_text_from_file_payload(file_data_b64, file_type):
    """Extracts text content from uploaded image/document attachments."""
    try:
        header, encoded = file_data_b64.split(",", 1) if "," in file_data_b64 else ("", file_data_b64)
        file_bytes = base64.b64decode(encoded)
        
        if "image" in file_type or file_type in [".png", ".jpg", ".jpeg", ".webp"]:
            if HAS_OCR:
                img = Image.open(io.BytesIO(file_bytes))
                extracted_text = pytesseract.image_to_string(img)
                return extracted_text.strip() if extracted_text.strip() else "[OCR detected image but no text could be extracted]"
            else:
                return "[Image received. OCR engine (pytesseract) is initializing or not installed.]"
        
        elif "text" in file_type or file_type in [".txt", ".py", ".js", ".json", ".csv", ".md"]:
            return file_bytes.decode('utf-8', errors='ignore')
            
    except Exception as e:
        print(f"[ATTACHMENT PROCESSING ERROR]: {e}")
        return f"[Failed to process attached file: {str(e)}]"

    return "[Unsupported attachment type]"

@app.route('/api/ask', methods=['POST'])
def ask():
    data = request.json or {}
    provided_key = request.headers.get("X-EVAS-KEY") or data.get("secret_key")
    
    if EVAS_SECRET_KEY and provided_key != EVAS_SECRET_KEY:
        return jsonify({'response': '🔒 Unauthorized access blocked. Invalid Secret Key.', 'audio': False}), 403

    user_prompt = data.get('prompt', '').strip()
    honorific = data.get('honorific', 'Sir')
    file_b64 = data.get('file_b64', None)
    file_type = data.get('file_type', '')

    extracted_attachment_text = ""
    if file_b64:
        extracted_attachment_text = extract_text_from_file_payload(file_b64, file_type)
        user_prompt = f"{user_prompt}\n\n[ATTACHED CONTENT/HOMEWORK TEXT]:\n{extracted_attachment_text}".strip()

    if not user_prompt:
        return jsonify({'response': f'No command or file received, {honorific}.', 'audio': False})

    reply = None

    system_prompt = (
        f"You are E.V.A.S., an advanced AI tutor and workspace assistant. "
        f"When provided with homework, math problems, code, or image screenshots, analyze them thoroughly step-by-step and provide clear, precise, and verified solutions. Address the user as '{honorific}'."
    )

    if HAS_OLLAMA:
        try:
            response = ollama.chat(
                model='deepseek-r1:1.5b',
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                options={"num_predict": 1200, "temperature": 0.2}
            )
            raw_reply = response['message']['content'].strip()
            reply = re.sub(r'<think>[\s\S]*?</think>', '', raw_reply).strip()
        except Exception:
            reply = None

    if not reply:
        reply = f"### 📝 HOMEWORK / FILE ANALYSIS TELEMETRY REPORT:\n\nProcessed Request: {user_prompt}"

    clean_text = re.sub(r'[*_~`]', '', reply).strip()

    return jsonify({
        'response': clean_text, 
        'raw_markdown': reply,
        'audio': False
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)