import base64
import os
import re
from typing import Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

APP_NAME = "AI Finder API"
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
IMAGE_API_BASE = os.getenv("IMAGE_API_BASE", "https://api.openai.com/v1").rstrip("/")
IMAGE_API_KEY = os.getenv("IMAGE_API_KEY", "")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-1")
ALLOWED_ORIGINS = [x.strip() for x in os.getenv("ALLOWED_ORIGINS", "*").split(",") if x.strip()]

app = FastAPI(title=APP_NAME, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if ALLOWED_ORIGINS == ["*"] else ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    model: Optional[str] = None

class ImagePrompt(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)

class DirectMessage(BaseModel):
    conversation_id: str
    body: str = Field(min_length=1, max_length=10000)

async def require_user(authorization: Optional[str]):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "يلزم تسجيل الدخول.")
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(503, "خدمة الحسابات غير مهيأة على الخادم.")
    token = authorization.split(" ", 1)[1].strip()
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}"},
        )
    if response.status_code != 200:
        raise HTTPException(401, "جلسة الدخول غير صالحة أو منتهية.")
    return response.json()

def supabase_headers():
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(503, "قاعدة البيانات غير مهيأة على الخادم.")
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }

async def db_request(method: str, path: str, **kwargs):
    headers = supabase_headers()
    headers.update(kwargs.pop("headers", {}))
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.request(method, f"{SUPABASE_URL}/rest/v1/{path}", headers=headers, **kwargs)
    if response.status_code >= 400:
        raise HTTPException(400, "تعذر تنفيذ العملية على قاعدة البيانات.")
    if not response.content:
        return None
    return response.json()

@app.get("/")
async def root():
    return {"name": APP_NAME, "status": "ok", "docs": "/docs"}

@app.get("/health")
async def health():
    return {"status": "ok", "ai_configured": bool(OPENROUTER_API_KEY), "database_configured": bool(SUPABASE_URL and SUPABASE_ANON_KEY and SUPABASE_SERVICE_ROLE_KEY)}

@app.post("/api/ai/chat")
async def ai_chat(payload: ChatRequest, authorization: Optional[str] = Header(default=None)):
    await require_user(authorization)
    if not OPENROUTER_API_KEY:
        raise HTTPException(503, "مزود النصوص غير مهيأ. أضف OPENROUTER_API_KEY إلى متغيرات بيئة الخادم.")
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json={"model": payload.model or OPENROUTER_MODEL, "messages": [{"role": "user", "content": payload.message}]},
        )
    if response.status_code >= 400:
        raise HTTPException(502, "فشل مزود الذكاء الاصطناعي في معالجة الطلب.")
    data = response.json()
    return {"reply": data["choices"][0]["message"]["content"], "model": data.get("model")}

@app.post("/api/ai/vision")
async def ai_vision(prompt: str, file: UploadFile = File(...), authorization: Optional[str] = Header(default=None)):
    await require_user(authorization)
    if not OPENROUTER_API_KEY:
        raise HTTPException(503, "مزود تحليل الصور غير مهيأ.")
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(415, "الملف يجب أن يكون صورة.")
    raw = await file.read()
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(413, "حجم الصورة الأقصى 8 ميغابايت.")
    encoded = base64.b64encode(raw).decode("ascii")
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json={"model": OPENROUTER_MODEL, "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt or "صف هذه الصورة بدقة."},
                {"type": "image_url", "image_url": {"url": f"data:{file.content_type};base64,{encoded}"}},
            ]}]},
        )
    if response.status_code >= 400:
        raise HTTPException(502, "فشل مزود تحليل الصور.")
    data = response.json()
    return {"reply": data["choices"][0]["message"]["content"], "model": data.get("model")}

@app.post("/api/ai/image")
async def generate_image(payload: ImagePrompt, authorization: Optional[str] = Header(default=None)):
    await require_user(authorization)
    if not IMAGE_API_KEY:
        raise HTTPException(503, "توليد الصور غير مهيأ. أضف IMAGE_API_KEY وIMAGE_MODEL.")
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{IMAGE_API_BASE}/images/generations",
            headers={"Authorization": f"Bearer {IMAGE_API_KEY}", "Content-Type": "application/json"},
            json={"model": IMAGE_MODEL, "prompt": payload.prompt, "n": 1, "size": "1024x1024"},
        )
    if response.status_code >= 400:
        raise HTTPException(502, "فشل مزود توليد الصور.")
    data = response.json()
    item = data.get("data", [{}])[0]
    image_url = item.get("url") or (f"data:image/png;base64,{item['b64_json']}" if item.get("b64_json") else None)
    return {"image": image_url, "revised_prompt": item.get("revised_prompt")}

@app.get("/api/conversations")
async def conversations(authorization: Optional[str] = Header(default=None)):
    user = await require_user(authorization)
    uid = user["id"]
    return await db_request("GET", f"conversation_members?user_id=eq.{uid}&select=conversation_id,conversations(id,title,created_at)", headers={"Prefer": "return=representation"})


class NewConversation(BaseModel):
    recipient_id: str

@app.get("/api/users")
async def search_users(q: str = "", authorization: Optional[str] = Header(default=None)):
    user = await require_user(authorization)
    term = re.sub(r"[^a-zA-Z0-9_\-\u0600-\u06FF ]", "", q.strip())[:60]
    if not term:
        return []
    uid = user["id"]
    return await db_request("GET", f"profiles?id=neq.{uid}&or=(username.ilike.*{term}*,display_name.ilike.*{term}*)&select=id,username,display_name,avatar_url&limit=20")

@app.post("/api/conversations")
async def create_conversation(payload: NewConversation, authorization: Optional[str] = Header(default=None)):
    user = await require_user(authorization)
    uid = user["id"]
    if payload.recipient_id == uid:
        raise HTTPException(400, "لا يمكنك بدء محادثة مع حسابك.")
    created = await db_request("POST", "conversations", json={"title": "محادثة خاصة"}, headers={"Prefer": "return=representation"})
    conversation_id = created[0]["id"]
    await db_request("POST", "conversation_members", json=[
        {"conversation_id": conversation_id, "user_id": uid},
        {"conversation_id": conversation_id, "user_id": payload.recipient_id},
    ], headers={"Prefer": "return=minimal"})
    return {"id": conversation_id}
\n@app.get("/api/messages/{conversation_id}")
async def get_messages(conversation_id: str, authorization: Optional[str] = Header(default=None)):
    user = await require_user(authorization)
    uid = user["id"]
    membership = await db_request("GET", f"conversation_members?conversation_id=eq.{conversation_id}&user_id=eq.{uid}&select=id")
    if not membership:
        raise HTTPException(403, "ليس لديك صلاحية لقراءة هذه المحادثة.")
    return await db_request("GET", f"messages?conversation_id=eq.{conversation_id}&select=id,sender_id,body,created_at&order=created_at.asc")

@app.post("/api/messages")
async def send_message(payload: DirectMessage, authorization: Optional[str] = Header(default=None)):
    user = await require_user(authorization)
    uid = user["id"]
    membership = await db_request("GET", f"conversation_members?conversation_id=eq.{payload.conversation_id}&user_id=eq.{uid}&select=id")
    if not membership:
        raise HTTPException(403, "ليس لديك صلاحية لإرسال رسالة في هذه المحادثة.")
    return await db_request("POST", "messages", json={"conversation_id": payload.conversation_id, "sender_id": uid, "body": payload.body}, headers={"Prefer": "return=representation"})
