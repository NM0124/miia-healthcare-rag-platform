"""FastAPI server: Google sign-in, chat sessions with RAG answers, document library, and the SPA.

Run with:  uvicorn backend.main:app --port 8000
Route handlers are plain ``def`` so FastAPI runs them in its thread pool (embedding, Docling and
Supabase calls are blocking and must not stall the event loop).
"""

import logging
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from google.auth.exceptions import TransportError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pydantic import BaseModel

from backend import config, db
from backend.rag import answer_question, delete_document_chunks, get_vector_store

logger = logging.getLogger(__name__)
app = FastAPI(title="MIIA Healthcare Intelligence API", version="2.0.0")

# Enable CORS for external frontend deployment (e.g. Vercel)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# Auth: Google ID token -> server-side session token
# ==============================================================================

# token -> {"user_id", "expires_at"}. In-memory: all users must sign in again after a restart.
_sessions: Dict[str, dict] = {}


def _verify_google(credential: str) -> Optional[dict]:
    if not config.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="GOOGLE_CLIENT_ID is not configured on the server.")
    try:
        # Checks signature, expiry and that the token was issued for *our* client id.
        info = id_token.verify_oauth2_token(credential, google_requests.Request(), config.GOOGLE_CLIENT_ID)
    except ValueError:
        return None
    except TransportError:
        raise HTTPException(status_code=503, detail="Could not reach Google to verify the sign-in. Try again.")
    return info if info.get("email") else None


def current_user(authorization: Optional[str] = Header(None)) -> dict:
    token = (authorization or "").replace("Bearer ", "").strip()
    session = _sessions.get(token)
    if session and time.time() > session["expires_at"]:
        _sessions.pop(token, None)
        session = None
    user = db.get_user(session["user_id"]) if session else None
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in.")
    return user


class GoogleAuthRequest(BaseModel):
    credential: str


class CreateSessionRequest(BaseModel):
    title: Optional[str] = "New Chat"


class ChatMessageRequest(BaseModel):
    message: str


class BulkDeleteRequest(BaseModel):
    document_ids: List[str]


@app.post("/api/auth/google")
def google_login(req: GoogleAuthRequest):
    info = _verify_google(req.credential)
    if not info:
        raise HTTPException(status_code=400, detail="Invalid Google OAuth credential.")
    email = info["email"]
    user = db.upsert_user(
        email=email,
        name=info.get("name") or email.split("@")[0],
        picture=info.get("picture", ""),
        user_id=info["sub"],
    )
    token = str(uuid.uuid4())
    _sessions[token] = {"user_id": user["id"], "expires_at": time.time() + config.SESSION_TTL_SECONDS}
    return {
        "token": token,
        "user": {"id": user["id"], "email": user["email"], "name": user["name"], "picture": user.get("picture", "")},
    }


@app.get("/api/auth/me")
def me(user: dict = Depends(current_user)):
    return {"user": user}


@app.post("/api/auth/logout")
def logout(authorization: Optional[str] = Header(None)):
    _sessions.pop((authorization or "").replace("Bearer ", "").strip(), None)
    return {"success": True}


# ==============================================================================
# Chat
# ==============================================================================

@app.get("/api/chat/sessions")
def list_sessions(user: dict = Depends(current_user)):
    return {"sessions": db.list_chat_sessions(user["id"])}


@app.post("/api/chat/sessions")
def create_session(req: CreateSessionRequest, user: dict = Depends(current_user)):
    return {"session": db.create_chat_session(user["id"], title=req.title or "New Chat")}


@app.delete("/api/chat/sessions/{session_id}")
def delete_session(session_id: str, user: dict = Depends(current_user)):
    if not db.delete_chat_session(session_id, user["id"]):
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"success": True}


@app.get("/api/chat/sessions/{session_id}/messages")
def get_messages(session_id: str, user: dict = Depends(current_user)):
    if not db.get_chat_session(session_id, user["id"]):
        raise HTTPException(status_code=404, detail="Chat session not found.")
    return {"messages": db.list_chat_messages(session_id)}


@app.post("/api/chat/sessions/{session_id}/messages")
def send_message(session_id: str, req: ChatMessageRequest, user: dict = Depends(current_user)):
    session = db.get_chat_session(session_id, user["id"])
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    question = req.message.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    if session.get("title") == "New Chat":  # first message names the chat
        db.update_chat_session_title(session_id, question[:32] + ("..." if len(question) > 32 else ""))
    return {"assistant_message": answer_question(session_id, user["id"], question)}


# ==============================================================================
# Document library
# ==============================================================================

def _format_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} B"


def _delete_document(doc_id: str, user_id: str) -> bool:
    """Remove a document's vectors and its record - only if it belongs to this user."""
    if not db.get_user_document(doc_id, user_id):
        return False
    try:
        delete_document_chunks(get_vector_store(config.USER_COLLECTION), doc_id)
    except Exception as exc:
        logger.warning("Could not delete vectors for document %s: %s", doc_id, exc)
    return db.delete_user_document(doc_id, user_id)


@app.get("/api/documents")
def list_documents(search: str = Query(""), sort: str = Query("desc"), user: dict = Depends(current_user)):
    return {"documents": db.list_user_documents(user["id"], search=search, sort=sort)}


@app.post("/api/documents/upload")
def upload_document(
    file: UploadFile = File(...),
    session_id: str = Query(""),
    user: dict = Depends(current_user),
):
    name = file.filename or "uploaded_document"
    if Path(name).suffix.lower() not in config.ALLOWED_UPLOAD_SUFFIXES:
        raise HTTPException(status_code=415, detail=f"Unsupported file type. Allowed: {sorted(config.ALLOWED_UPLOAD_SUFFIXES)}")
    data = file.file.read(config.MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds the {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.")

    doc_id = uuid.uuid4().hex[:16]
    record = db.add_user_document(doc_id, user["id"], name, _format_size(len(data)), session_id)
    try:
        from backend.ingestion import index_user_upload
        chunks = index_user_upload(user["id"], doc_id, name, data)
        db.update_user_document(doc_id, "indexed", chunks)
        record.update(status="indexed", chunk_count=chunks)
    except Exception:
        logger.exception("Indexing failed for '%s'", name)
        db.update_user_document(doc_id, "failed")
        record["status"] = "failed"
    return {"document": record}


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str, user: dict = Depends(current_user)):
    return {"success": _delete_document(doc_id, user["id"])}


@app.post("/api/documents/bulk-delete")
def bulk_delete_documents(req: BulkDeleteRequest, user: dict = Depends(current_user)):
    return {"deleted": sum(_delete_document(doc_id, user["id"]) for doc_id in req.document_ids)}


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve root health/status check
@app.get("/")
def root():
    return {"status": "ok", "message": "MIIA Healthcare Intelligence Backend API is running."}
