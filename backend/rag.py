"""RAG core: embeddings, Chroma Cloud access, dense retrieval, and Groq answer generation."""

import logging
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import chromadb
import httpx
import torch
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

from backend import config, db

# Prevent PyTorch from spawning multi-threaded buffer pools on constrained cloud servers
torch.set_num_threads(1)
torch.set_grad_enabled(False)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are MIIA (Medical Intelligence and Injury Analysis), an evidence-grounded clinical AI assistant.\n"
    "Your task is to provide clear, accurate, and responsible healthcare answers based strictly on the "
    "provided medical context and user documents.\n"
    "Always cite relevant sources (e.g. document name or guidelines) when quoting values or recommendations.\n"
    "If the context does not contain sufficient information, state that clearly and advise consulting a "
    "qualified physician.\n"
    "Always maintain an objective, compassionate, and evidence-grounded tone."
)

# --- Models (Dense Embeddings) ------------------------------------------------

@lru_cache(maxsize=1)
def _embeddings() -> HuggingFaceEmbeddings:
    logger.info("Loading embedding model %s on %s", config.EMBEDDING_MODEL, config.EMBEDDING_DEVICE)
    return HuggingFaceEmbeddings(
        model_name=config.EMBEDDING_MODEL,
        model_kwargs={"device": config.EMBEDDING_DEVICE},
        encode_kwargs={"normalize_embeddings": True, "batch_size": 64},
    )


# --- Vector store -------------------------------------------------------------

@lru_cache(maxsize=1)
def _chroma_client() -> "chromadb.ClientAPI":
    if not (config.CHROMA_API_KEY and config.CHROMA_TENANT and config.CHROMA_DATABASE):
        raise RuntimeError("CHROMA_API_KEY, CHROMA_TENANT and CHROMA_DATABASE must be set (see .env.example)")
    return chromadb.HttpClient(
        host=config.CHROMA_HOST,
        port=443,
        ssl=True,
        headers={"x-chroma-token": config.CHROMA_API_KEY},
        tenant=config.CHROMA_TENANT,
        database=config.CHROMA_DATABASE,
    )


@lru_cache(maxsize=8)
def get_vector_store(collection: str) -> Chroma:
    """Return a (cached) LangChain Chroma handle for one Chroma Cloud collection."""
    return Chroma(client=_chroma_client(), collection_name=collection, embedding_function=_embeddings())
    

def upsert_chunks(store: Chroma, chunks: List[Document], ids: List[str], batch_size: int = 400) -> int:
    """Upsert chunks under deterministic ids into Chroma Cloud."""
    for i in range(0, len(chunks), batch_size):
        store.add_documents(documents=chunks[i : i + batch_size], ids=ids[i : i + batch_size])
    return len(chunks)


def delete_document_chunks(store: Chroma, document_id: str) -> int:
    """Delete every chunk belonging to one document_id from Chroma."""
    ids = store.get(where={"document_id": document_id}).get("ids", [])
    if ids:
        store.delete(ids=ids)
    return len(ids)


# --- Dense Retrieval ----------------------------------------------------------

def retrieve_dense(
    collection: str,
    query: str,
    k: int = 20,
    filter: Optional[dict] = None,
) -> List[Document]:
    """Dense semantic retrieval via BGE-M3 unit-normalized embeddings."""
    return get_vector_store(collection).similarity_search(query=query, k=k, filter=filter)


def search(
    collection: str,
    query: str,
    k: int = config.RETRIEVAL_TOP_K,
    filter: Optional[dict] = None,
    mode: Optional[str] = None,
) -> List[Document]:
    """Unified retrieval API: pure dense semantic retrieval."""
    return retrieve_dense(collection, query, k=k, filter=filter)


def retrieve_context(
    query: str,
    user_id: str,
    k: int = config.RETRIEVAL_TOP_K,
    mode: Optional[str] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Gather grounded context across user uploads, WHO/NHM guidelines, and CDC pages."""
    sources = [
        ("User Document", config.USER_COLLECTION, {"user_id": user_id}, "file_name"),
        ("WHO/NHM Guideline", config.WHO_COLLECTION, None, "title"),
        ("CDC Guidance", config.CDC_COLLECTION, None, "title"),
    ]
    blocks: List[str] = []
    citations: List[Dict[str, Any]] = []

    for label, collection, flt, name_key in sources:
        try:
            docs = search(collection, query, k=k, filter=flt, mode=mode)
        except Exception as exc:
            logger.warning("Retrieval from '%s' failed: %s", collection, exc)
            continue

        for doc in docs:
            meta = doc.metadata
            source = meta.get(name_key) or meta.get("file_name") or label
            page = meta.get("page_start", 1)
            text = doc.page_content.strip()
            blocks.append(f"[{label}: {source} | Page {page}]:\n{text}")
            citations.append({
                "source": source,
                "page": page,
                "snippet": text[:200] + ("..." if len(text) > 200 else ""),
            })

    return "\n\n---\n\n".join(blocks), citations


# --- Generation ---------------------------------------------------------------

def ask_groq(messages: List[Dict[str, str]], temperature: float = 0.2) -> str:
    if not config.GROQ_API_KEY:
        return "**[System Notice: GROQ_API_KEY is not configured on the server.]**"
    payload = {"model": config.GROQ_MODEL, "messages": messages, "temperature": temperature, "max_tokens": 1024}
    try:
        resp = httpx.post(
            config.GROQ_URL,
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
            json=payload,
            timeout=30.0,
        )
        if resp.status_code != 200:
            logger.error("Groq API error %d: %s", resp.status_code, resp.text)
            return f"Error communicating with Groq AI service (HTTP {resp.status_code})."
        return resp.json()["choices"][0]["message"]["content"]
    except httpx.HTTPError as exc:
        logger.error("Groq request failed: %s", exc)
        return f"Service connection error: {exc}"


def answer_question(session_id: str, user_id: str, question: str) -> Dict[str, Any]:
    """Full RAG turn: store question -> retrieve context -> ask Groq -> store and return the reply."""
    db.add_chat_message(session_id, "user", question)
    context, citations = retrieve_context(question, user_id)

    source_context = ""
    if citations:
        best = citations[0]
        source_context = f'"{best["source"]}, Page {best["page"]}: {best["snippet"]}"'

    # Last 8 stored messages for conversational memory, excluding the question just saved.
    history = db.list_chat_messages(session_id)[-8:-1]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history]
    if context:
        question = (
            f"Context Information:\n{context}\n\nUser Question: {question}\n\n"
            "Please answer based on the context above, citing the relevant findings."
        )
    messages.append({"role": "user", "content": question})

    reply = ask_groq(messages)
    return db.add_chat_message(session_id, "assistant", reply, source_context=source_context)
