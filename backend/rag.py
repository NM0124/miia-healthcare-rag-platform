"""RAG core: embeddings, Chroma Cloud access, hybrid retrieval (dense + BM25 + RRF),
cross-encoder reranking, and Groq answer generation.
"""

import gzip
import logging
import os
import pickle
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import chromadb
import httpx
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from backend import config, db

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

_WORD_REGEX = re.compile(r"\b\w+\b")


def tokenize_text(text: str) -> List[str]:
    """Fast, deterministic word tokenizer for BM25."""
    if not text:
        return []
    return [w.lower() for w in _WORD_REGEX.findall(text)]


# --- Models (Embeddings & Cross-Encoder Reranker) -----------------------------

@lru_cache(maxsize=1)
def _embeddings() -> HuggingFaceEmbeddings:
    logger.info("Loading embedding model %s on %s", config.EMBEDDING_MODEL, config.EMBEDDING_DEVICE)
    return HuggingFaceEmbeddings(
        model_name=config.EMBEDDING_MODEL,
        model_kwargs={"device": config.EMBEDDING_DEVICE},
        encode_kwargs={"normalize_embeddings": True, "batch_size": 64},
    )


@lru_cache(maxsize=1)
def _reranker() -> Optional[CrossEncoder]:
    try:
        logger.info("Loading cross-encoder reranker %s on %s", config.RERANKER_MODEL, config.RERANKER_DEVICE)
        return CrossEncoder(config.RERANKER_MODEL, device=config.RERANKER_DEVICE)
    except Exception as exc:
        logger.warning("Could not load cross-encoder reranker (%s): %s", config.RERANKER_MODEL, exc)
        return None


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


# In-memory BM25 caches: collection_name -> {"ids": [...], "corpus": [[...]], "bm25": BM25Okapi}
_bm25_memory_cache: Dict[str, Dict[str, Any]] = {}


def _get_bm25_cache_path(collection: str) -> Path:
    config.BM25_DIR.mkdir(parents=True, exist_ok=True)
    return config.BM25_DIR / f"{collection}.pkl.gz"


def get_bm25_index(collection: str) -> Optional[Dict[str, Any]]:
    """Load or build the in-memory BM25 index for a collection."""
    if collection in _bm25_memory_cache:
        return _bm25_memory_cache[collection]

    cache_file = _get_bm25_cache_path(collection)
    if cache_file.exists():
        try:
            with gzip.open(cache_file, "rb") as f:
                data = pickle.load(f)
                _bm25_memory_cache[collection] = data
                logger.info("Loaded BM25 index for '%s' (%d documents)", collection, len(data["ids"]))
                return data
        except Exception as exc:
            logger.warning("Could not read BM25 cache for '%s': %s", collection, exc)

    return None


def update_bm25_index(collection: str, chunk_ids: List[str], chunk_texts: List[str]) -> None:
    """Incrementally add or update document chunks in the collection's BM25 index and save to disk."""
    if not chunk_ids or not chunk_texts:
        return

    data = get_bm25_index(collection)
    new_tokens = [tokenize_text(t) for t in chunk_texts]

    if data is None:
        new_ids = list(chunk_ids)
        new_corpus = new_tokens
    else:
        # Replace existing IDs or append new ones
        id_set = set(chunk_ids)
        existing_pairs = [
            (cid, corp) for cid, corp in zip(data["ids"], data.get("corpus", []))
            if cid not in id_set
        ]
        new_ids = [cid for cid, _ in existing_pairs] + list(chunk_ids)
        new_corpus = [corp for _, corp in existing_pairs] + new_tokens

    new_bm25 = BM25Okapi(new_corpus)
    updated_data = {"ids": new_ids, "corpus": new_corpus, "bm25": new_bm25}
    _bm25_memory_cache[collection] = updated_data

    # Persist asynchronously / save to disk
    try:
        cache_file = _get_bm25_cache_path(collection)
        with gzip.open(cache_file, "wb") as f:
            pickle.dump(updated_data, f, protocol=5)
        logger.info("Persisted BM25 index for '%s' (%d documents)", collection, len(new_ids))
    except Exception as exc:
        logger.warning("Failed to persist BM25 index for '%s': %s", collection, exc)


def remove_from_bm25_index(collection: str, chunk_ids: List[str]) -> None:
    """Remove chunk IDs from the collection's BM25 index and update cache."""
    data = get_bm25_index(collection)
    if not data or not chunk_ids:
        return

    remove_set = set(chunk_ids)
    kept_pairs = [
        (cid, corp) for cid, corp in zip(data["ids"], data.get("corpus", []))
        if cid not in remove_set
    ]
    if len(kept_pairs) == len(data["ids"]):
        return

    new_ids = [cid for cid, _ in kept_pairs]
    new_corpus = [corp for _, corp in kept_pairs]
    new_bm25 = BM25Okapi(new_corpus) if new_corpus else None
    updated_data = {"ids": new_ids, "corpus": new_corpus, "bm25": new_bm25}
    _bm25_memory_cache[collection] = updated_data

    try:
        cache_file = _get_bm25_cache_path(collection)
        with gzip.open(cache_file, "wb") as f:
            pickle.dump(updated_data, f, protocol=5)
    except Exception as exc:
        logger.warning("Failed to update BM25 index after deletion for '%s': %s", collection, exc)


def upsert_chunks(store: Chroma, chunks: List[Document], ids: List[str], batch_size: int = 400) -> int:
    """Upsert chunks under deterministic ids and update BM25 lexical index."""
    for i in range(0, len(chunks), batch_size):
        store.add_documents(documents=chunks[i : i + batch_size], ids=ids[i : i + batch_size])

    # Synchronize BM25 lexical index
    collection_name = store._collection.name
    texts = [c.page_content for c in chunks]
    update_bm25_index(collection_name, ids, texts)

    return len(chunks)


def delete_document_chunks(store: Chroma, document_id: str) -> int:
    """Delete every chunk belonging to one document_id from Chroma and BM25."""
    ids = store.get(where={"document_id": document_id}).get("ids", [])
    if ids:
        store.delete(ids=ids)
        remove_from_bm25_index(store._collection.name, ids)
    return len(ids)


# --- Dense, Sparse, Hybrid, & Reranked Retrieval ------------------------------

def retrieve_dense(
    collection: str,
    query: str,
    k: int = 20,
    filter: Optional[dict] = None,
) -> List[Document]:
    """Dense semantic retrieval via BGE-M3 unit-normalized embeddings."""
    return get_vector_store(collection).similarity_search(query=query, k=k, filter=filter)


def retrieve_sparse(
    collection: str,
    query: str,
    k: int = 20,
    filter: Optional[dict] = None,
) -> List[Document]:
    """Sparse lexical retrieval using BM25Okapi scoring."""
    bm25_data = get_bm25_index(collection)
    if not bm25_data or not bm25_data.get("bm25") or not bm25_data.get("ids"):
        return []

    tokens = tokenize_text(query)
    if not tokens:
        return []

    bm25: BM25Okapi = bm25_data["bm25"]
    all_ids: List[str] = bm25_data["ids"]
    scores = bm25.get_scores(tokens)

    # Sort candidates by BM25 score descending
    candidate_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    # Take positive scored candidates up to 3*k for potential filtering
    top_indices = [i for i in candidate_indices if scores[i] > 0][: k * 3]
    if not top_indices:
        return []

    selected_ids = [all_ids[i] for i in top_indices]

    # Fetch document content and metadata from Chroma Cloud
    col = _chroma_client().get_collection(collection)
    fetch_kwargs: Dict[str, Any] = {"ids": selected_ids, "include": ["documents", "metadatas"]}
    if filter:
        fetch_kwargs["where"] = filter

    try:
        records = col.get(**fetch_kwargs)
        fetched_ids = records.get("ids", [])
        documents = records.get("documents", [])
        metadatas = records.get("metadatas", [])

        # Maintain BM25 score rank order
        id_to_doc = {
            cid: Document(page_content=doc, metadata=meta or {})
            for cid, doc, meta in zip(fetched_ids, documents, metadatas)
            if doc and doc.strip()
        }
        return [id_to_doc[cid] for cid in selected_ids if cid in id_to_doc][:k]
    except Exception as exc:
        logger.warning("Failed to fetch BM25 candidate chunks from collection '%s': %s", collection, exc)
        return []


def reciprocal_rank_fusion(
    dense_docs: List[Document],
    sparse_docs: List[Document],
    k_rrf: int = config.RRF_K,
    top_k: int = 10,
) -> List[Document]:
    """Combine dense and sparse candidate rankings using Reciprocal Rank Fusion (RRF).

    Formula: RRF_score(d) = sum_{m in {dense, sparse}} 1 / (k_rrf + rank_m(d))
    """
    scores: Dict[str, float] = {}
    doc_map: Dict[str, Document] = {}

    def doc_key(d: Document) -> str:
        meta = d.metadata or {}
        cid = meta.get("chunk_id") or meta.get("document_id")
        page = meta.get("page_start", "")
        if cid:
            return f"{cid}_{page}"
        return f"{meta.get('file_name', '')}_{hash(d.page_content[:60])}"

    for rank, doc in enumerate(dense_docs, 1):
        key = doc_key(doc)
        doc_map[key] = doc
        scores[key] = scores.get(key, 0.0) + (1.0 / (k_rrf + rank))

    for rank, doc in enumerate(sparse_docs, 1):
        key = doc_key(doc)
        doc_map[key] = doc
        scores[key] = scores.get(key, 0.0) + (1.0 / (k_rrf + rank))

    sorted_keys = sorted(scores.keys(), key=lambda k_val: scores[k_val], reverse=True)
    return [doc_map[k_val] for k_val in sorted_keys[:top_k]]


def rerank_documents(query: str, documents: List[Document], top_k: int = config.RETRIEVAL_TOP_K) -> List[Document]:
    """Cross-encoder reranking using BAAI/bge-reranker-v2-m3."""
    if not documents:
        return []
    if len(documents) <= 1:
        return documents[:top_k]

    model = _reranker()
    if model is None:
        return documents[:top_k]

    pairs = [(query, doc.page_content) for doc in documents]
    try:
        raw_scores = model.predict(pairs)
        scored_docs = list(zip(documents, raw_scores))
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        return [doc for doc, _ in scored_docs[:top_k]]
    except Exception as exc:
        logger.warning("Reranking failed (%s); returning original rank order", exc)
        return documents[:top_k]


def search(
    collection: str,
    query: str,
    k: int = config.RETRIEVAL_TOP_K,
    filter: Optional[dict] = None,
    mode: Optional[str] = None,
) -> List[Document]:
    """Unified retrieval API: dense, sparse, hybrid (RRF), or hybrid_rerank."""
    active_mode = (mode or config.RETRIEVAL_MODE).lower()

    if active_mode == "dense":
        return retrieve_dense(collection, query, k=k, filter=filter)

    if active_mode == "sparse":
        return retrieve_sparse(collection, query, k=k, filter=filter)

    # Hybrid modes (dense + sparse fusion)
    candidates_k = max(k * 3, 15)
    dense_docs = retrieve_dense(collection, query, k=candidates_k, filter=filter)
    sparse_docs = retrieve_sparse(collection, query, k=candidates_k, filter=filter)

    fused_docs = reciprocal_rank_fusion(
        dense_docs=dense_docs,
        sparse_docs=sparse_docs,
        k_rrf=config.RRF_K,
        top_k=candidates_k if active_mode == "hybrid_rerank" else k,
    )

    if active_mode == "hybrid_rerank":
        return rerank_documents(query=query, documents=fused_docs, top_k=k)

    return fused_docs[:k]


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
