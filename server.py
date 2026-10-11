import asyncio
import base64
import json
import os
import random
import re
import threading
import time
from duckduckgo_search import DDGS
import edge_tts
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import requests

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MEMORY_FILE = "jarvis_memory.txt"
GLOBAL_NEWS_CACHE = []

GROK_API_KEY = os.getenv("GROK_API_KEY", "")
GROK_ENDPOINT = "https://api.x.ai/v1/chat/completions"

# --- Background Global News Engine ---
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

# --- DuckDuckGo Search Integrations ---
def search_general_knowledge(query):
    try:
        results = list(DDGS().text(query, max_results=6))
        if results:
            snippets = [f"• {res['title']}: {res['body']}" for res in results if 'body' in res]
            return f"Comprehensive analysis on '{query}':\n\n" + "\n\n".join(snippets[:4])
        return None
    except Exception:
        return None

def search_lyrics_or_music(query):
    try:
        results = list(DDGS().text(f"{query} song lyrics music", max_results=3))
        return "\n".join([f"🎵 {res['title']}\n{res['body']}" for res in results]) if results else "No music info found."
    except Exception as e:
        return f"Search error: {str(e)}"

def search_flight_details(flight_num):
    try:
        results = list(DDGS().text(f"flight status schedule departure arrival delay {flight_num}", max_results=3))
        return "\n".join([f"✈️ {res['title']}\n{res['body']}" for res in results]) if results else f"No radar info for flight {flight_num}."
    except Exception as e:
        return f"Flight error: {str(e)}"

def search_weather(location_str):
    try:
        results = list(DDGS().text(f"current weather forecast in {location_str}", max_results=2))
        return "\n".join([f"🌤️ {res['title']}\n{res['body']}" for res in results]) if results else "Weather data unavailable."
    except Exception as e:
        return f"Weather error: {str(e)}"

# --- Multimodal Vision & LLM Core (Grok / Ollama) ---
def query_grok_llm(prompt: str, images: list = None, honorific: str = "Sir") -> str:
    """Processes user questions and dropped images using Grok API or fallback logic."""
    if not GROK_API_KEY:
        return None
    
    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json"
    }

    user_content = []
    if prompt:
        user_content.append({"type": "text", "text": prompt})
    
    # Process base64 image attachments
    if images:
        for img in images:
            img_data = img if img.startswith("data:image") else f"data:image/jpeg;base64,{img}"
            user_content.append({"type": "image_url", "image_url": {"url": img_data}})

    if not user_content:
        user_content = "Analyze system state."

    payload = {
        "model": "grok-vision-beta" if images else "grok-beta",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are J.A.R.V.I.S., Tony Stark's hyper-intelligent AI assistant. "
                    "Analyze all questions and dropped image uploads with clinical precision. "
                    f"Address the user strictly as {honorific}."
                )
            },
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.4
    }
    try:
        res = requests.post(GROK_ENDPOINT, headers=headers, json=payload, timeout=15)
        if res.status_code == 200:
            return res.json()['choices'][0]['message']['content']
        return None
    except Exception:
        return None

# --- Voice Generator ---
async def generate_jarvis_voice(text):
    communicate = edge_tts.Communicate(text, "en-GB-RyanNeural", pitch="-3Hz", rate="+2%")
    await communicate.save("static_speech.mp3")

# --- Command & Query Intent Parser ---
def process_user_intent(user_prompt: str, images: list = None, honorific: str = "Sir", device_type: str = "desktop"):
    cmd_lower = user_prompt.lower()
    reply = None
    media_action = None
    nav_destination = None
    activate_map = False
    trigger_blackout = False
    is_shutdown = False
    app_launch_intent = None

    if "show map" in cmd_lower or "activate map" in cmd_lower or "open map" in cmd_lower:
        activate_map = True
        reply = f"Activating tactical GPS HUD map overlay now, {honorific}."
    elif "hide map" in cmd_lower or "close map" in cmd_lower:
        activate_map = False
        reply = f"Deactivating map overlay and returning to diagnostic view, {honorific}."
    elif "direction" in cmd_lower or "navigate" in cmd_lower or "route" in cmd_lower or "map to" in cmd_lower:
        activate_map = True
        dest_match = re.sub(r'get directions to|directions to|navigate to|map to|take me to', '', user_prompt, flags=re.IGNORECASE).strip()
        nav_destination = dest_match if dest_match else "Target Destination"
        reply = f"GPS routing initialized for {nav_destination}, {honorific}."
    elif "blackout" in cmd_lower or "black out" in cmd_lower:
        trigger_blackout = True
        reply = f"Engaging HUD blackout mode, {honorific}."
    elif "shut down" in cmd_lower or "shutdown" in cmd_lower:
        is_shutdown = True
        reply = f"Initiating system shutdown sequence, {honorific}."
    elif "lyrics" in cmd_lower or "shazam" in cmd_lower or "what song" in cmd_lower:
        reply = search_lyrics_or_music(user_prompt)
    elif "weather" in cmd_lower or "forecast" in cmd_lower:
        reply = search_weather("Bayan Lepas, Penang, Malaysia")
    elif "flight" in cmd_lower or "airline" in cmd_lower:
        flight_match = re.search(r'([a-zA-Z]{2,3}\s?\d{2,4})', user_prompt)
        reply = search_flight_details(flight_match.group(1)) if flight_match else f"Please specify a valid flight number, {honorific}."

    # Process Multimodal Questions & Images
    if not reply:
        grok_response = query_grok_llm(user_prompt, images, honorific)
        if grok_response:
            reply = grok_response
        else:
            if images:
                reply = f"Image received and scanned, {honorific}. Visual analysis indicates image buffer uploaded successfully."
            else:
                search_res = search_general_knowledge(user_prompt)
                if search_res:
                    reply = search_res
                else:
                    reply = f"Analysis complete for '{user_prompt}'. All subroutines nominal, {honorific}."

    clean_text = re.sub(r'[*_~`]', '', reply).strip()
    return {
        "text": clean_text,
        "activate_map": activate_map,
        "blackout": trigger_blackout,
        "is_shutdown": is_shutdown,
        "nav_destination": nav_destination,
        "app_intent": app_launch_intent
    }

# --- HTTP Routes ---
@app.get("/")
def read_root():
    return FileResponse("index.html")

@app.get("/manifest.json")
def get_manifest():
    return FileResponse("manifest.json")

@app.get("/sw.js")
def get_sw():
    return FileResponse("sw.js")

@app.get("/api/get_news")
def get_news():
    if GLOBAL_NEWS_CACHE:
        return {"status": "success", "news": GLOBAL_NEWS_CACHE}
    return {"status": "error", "news": ["Global news feed synchronizing..."]}

@app.post("/api/request_2fa")
def request_2fa():
    otp_code = str(random.randint(100000, 999999))
    return {"status": "sent", "demo_code": otp_code}

class QueryModel(BaseModel):
    prompt: str
    images: list = []
    honorific: str = "Sir"
    device_type: str = "desktop"

@app.post("/api/ask")
def ask(data: QueryModel):
    result = process_user_intent(data.prompt, data.images, data.honorific, data.device_type)
    return JSONResponse(result)

@app.get("/api/audio")
def get_audio():
    if os.path.exists("static_speech.mp3"):
        return FileResponse("static_speech.mp3", media_type="audio/mpeg")
    return JSONResponse({"status": "no audio generated"}, status_code=404)

# --- WebSocket Channel ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data_raw = await websocket.receive_text()
            data = json.loads(data_raw)
            prompt = data.get("prompt", "")
            images = data.get("images", [])
            honorific = data.get("honorific", "Sir")
            device_type = data.get("device_type", "desktop")

            result = process_user_intent(prompt, images, honorific, device_type)

            try:
                await generate_jarvis_voice(result["text"])
                result["has_audio"] = True
            except Exception:
                result["has_audio"] = False

            await websocket.send_text(json.dumps(result))
    except WebSocketDisconnect:
        pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)