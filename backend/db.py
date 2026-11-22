"""Supabase data layer: users, chat sessions/messages and uploaded-document records."""

import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional

from supabase import Client, create_client

from backend import config

Row = Dict[str, Any]


@lru_cache(maxsize=1)
def client() -> Client:
    if not (config.SUPABASE_URL and config.SUPABASE_KEY):
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set (see .env.example)")
    return create_client(config.SUPABASE_URL, config.SUPABASE_KEY)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first(res) -> Optional[Row]:
    return res.data[0] if res.data else None


# --- Users --------------------------------------------------------------------

def upsert_user(email: str, name: str, picture: str, user_id: str) -> Row:
    """Create the user on first login, otherwise refresh name/picture."""
    existing = _first(client().table("users").select("*").eq("email", email).execute())
    if existing:
        client().table("users").update({"name": name, "picture": picture}).eq("id", existing["id"]).execute()
        return {**existing, "name": name, "picture": picture}
    new = {"id": user_id, "email": email, "name": name, "picture": picture, "created_at": _now()}
    return _first(client().table("users").insert(new).execute()) or new


def get_user(user_id: str) -> Optional[Row]:
    return _first(client().table("users").select("*").eq("id", user_id).execute())


# --- Chat sessions & messages -------------------------------------------------

def create_chat_session(user_id: str, title: str = "New Chat") -> Row:
    now = _now()
    record = {"id": str(uuid.uuid4()), "user_id": user_id, "title": title, "created_at": now, "updated_at": now}
    return _first(client().table("chat_sessions").insert(record).execute()) or record


def list_chat_sessions(user_id: str) -> List[Row]:
    res = client().table("chat_sessions").select("*").eq("user_id", user_id).order("updated_at", desc=True).execute()
    return res.data or []


def get_chat_session(session_id: str, user_id: str) -> Optional[Row]:
    res = client().table("chat_sessions").select("*").eq("id", session_id).eq("user_id", user_id).execute()
    return _first(res)


def delete_chat_session(session_id: str, user_id: str) -> bool:
    """Messages are removed by the ON DELETE CASCADE in the schema."""
    res = client().table("chat_sessions").delete().eq("id", session_id).eq("user_id", user_id).execute()
    return bool(res.data)


def update_chat_session_title(session_id: str, title: str) -> None:
    client().table("chat_sessions").update({"title": title}).eq("id", session_id).execute()


def add_chat_message(session_id: str, role: str, content: str, source_context: str = "") -> Row:
    now = _now()
    record = {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "role": role,
        "content": content,
        "source_context": source_context,
        "created_at": now,
    }
    client().table("chat_messages").insert(record).execute()
    client().table("chat_sessions").update({"updated_at": now}).eq("id", session_id).execute()
    return record


def list_chat_messages(session_id: str) -> List[Row]:
    res = client().table("chat_messages").select("*").eq("session_id", session_id).order("created_at").execute()
    return res.data or []


# --- Uploaded documents -------------------------------------------------------

def add_user_document(doc_id: str, user_id: str, file_name: str, file_size: str, session_id: str = "") -> Row:
    record = {
        "id": doc_id,
        "user_id": user_id,
        "file_name": file_name,
        "file_size": file_size,
        "status": "processing",
        "chunk_count": 0,
        "upload_date": _now(),
        "session_id": session_id,
    }
    client().table("user_documents").upsert(record).execute()
    return record


def update_user_document(doc_id: str, status: str, chunk_count: int = 0) -> None:
    client().table("user_documents").update({"status": status, "chunk_count": chunk_count}).eq("id", doc_id).execute()


def list_user_documents(user_id: str, search: str = "", sort: str = "desc") -> List[Row]:
    query = client().table("user_documents").select("*").eq("user_id", user_id)
    query = query.order("upload_date", desc=sort.lower() != "asc")
    if search.strip():
        query = query.ilike("file_name", f"%{search.strip()}%")
    return query.execute().data or []


def get_user_document(doc_id: str, user_id: str) -> Optional[Row]:
    res = client().table("user_documents").select("*").eq("id", doc_id).eq("user_id", user_id).execute()
    return _first(res)


def delete_user_document(doc_id: str, user_id: str) -> bool:
    res = client().table("user_documents").delete().eq("id", doc_id).eq("user_id", user_id).execute()
    return bool(res.data)
