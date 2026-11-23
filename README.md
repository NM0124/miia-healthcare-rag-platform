# MIIA — Healthcare Intelligence RAG Platform

MIIA (Medical Intelligence & Injury Analysis) is a healthcare RAG platform that retrieves relevant information from trusted medical sources before generating responses. It includes document processing and a conversational interface for healthcare-related queries. Key functionalities include medical document ingestion, context-based retrieval, source-backed responses, and persistent chat sessions. AI-assisted injury analysis is also planned as an additional component.
The platform uses React, Python, FastAPI, Docling, BGE-M3 embeddings, ChromaDB Cloud, hybrid retrieval (Dense Search and BM25), Reciprocal Rank Fusion (RRF), Supabase (users, chats), and Groq.

```
backend/
  config.py      all settings (env vars)
  db.py          Supabase: users, chat sessions/messages, document records
  rag.py         embeddings, BM25, Chroma Cloud, hybrid retrieval, cross-encoder reranker, Groq
  ingestion.py   Docling parsing, PDF metadata, chunking, PDF + user-upload indexing
  cdc.py         CDC crawler, extractor, change-tracking manifest, pipeline, scheduler
  main.py        FastAPI routes + Google sign-in + serves the built React app
manage.py        CLI: check, ingest-pdfs, ingest-cdc, cdc-update, cdc-status, cdc-schedule, search
sql/schema.sql   Supabase tables
frontend/        React + Vite + Tailwind
data/            who/ and nhm/ (PDFs here), cdc_urls.txt, bm25/ (lexical indices)
```

## Setup

The database tables (users, chats, and document metadata) must be created once before running the application. Copy the contents of `sql/schema.sql` and run them inside your Supabase project's SQL Editor. The `manage.py` script is a management tool used to verify system connectivity and run knowledge base ingestion pipelines (parsing, chunking, and indexing medical guidelines into ChromaDB Cloud).

```bash
# 1. Virtual environment & dependencies
python -m venv venv
venv\Scripts\activate            # Linux/macOS: source venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env             # fill in your API keys and credentials

# 3. Initialize Supabase tables
# Run sql/schema.sql once in your Supabase SQL Editor

# 4. Verify system connections
python manage.py check
```

## Build the Frontend

```bash
cd frontend
npm install
npm run build
cd ..
```

## Run the Project

Run both the backend API and the frontend together with a single command:

```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open your browser at **http://localhost:8000** to use the application.

## Knowledge Base Ingestion

```bash
python manage.py ingest-pdfs                 # data/who + data/nhm -> Chroma Cloud
python manage.py ingest-cdc                  # URLs in data/cdc_urls.txt -> Chroma Cloud
python manage.py cdc-update                  # incremental refresh via CDC sitemaps
python manage.py search "treatment for severe malaria" -k 5
```

Re-running is safe: chunk IDs are deterministic and unchanged documents are automatically skipped.

## Notes

- Sessions are kept in server memory: restarting the server signs active users out.
- User-uploaded documents are parsed in-memory, chunked, and embedded into Chroma Cloud; raw files are not permanently stored on disk.
