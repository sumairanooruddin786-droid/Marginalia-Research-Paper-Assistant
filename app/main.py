"""FastAPI application: REST API + static frontend."""
import logging
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .errors import AppError
from .rag import RAGService
from .schemas import ChatRequest, ChatResponse

log = logging.getLogger("rpa")
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def create_app(service: RAGService = None) -> FastAPI:
    settings = get_settings()
    rag = service or RAGService(settings)
    app = FastAPI(title="Research Paper Assistant", version="1.0.0")
    app.state.rag = rag

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.message})

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_: Request, exc: Exception):
        log.exception("Unhandled error")
        return JSONResponse(status_code=500, content={"detail": "Something went wrong on the server. Please try again."})

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "ai_configured": rag.configured,
            "chat_model": settings.chat_model,
            "documents": len(rag.registry.ids()),
        }

    @app.get("/api/documents")
    def list_documents():
        return {"documents": rag.registry.all()}

    @app.post("/api/documents")
    async def upload_documents(files: List[UploadFile] = File(default=[])):
        if not files:
            raise AppError(400, "No file received. Choose one or more PDF files to upload.")
        results = []
        for f in files:
            name = f.filename or "unnamed file"
            try:
                data = await f.read()
                record = rag.ingest(name, data)
                results.append({"name": name, "status": "indexed", "document": record})
            except AppError as exc:
                results.append({"name": name, "status": "error", "error": exc.message, "code": exc.status})
            except Exception:
                log.exception("Upload failed for %s", name)
                results.append({"name": name, "status": "error", "error": "Unexpected error while indexing this file.", "code": 500})
        return {
            "results": results,
            "indexed": sum(r["status"] == "indexed" for r in results),
            "documents": rag.registry.all(),
        }

    @app.delete("/api/documents/{doc_id}")
    def delete_document(doc_id: str):
        rag.delete(doc_id)
        return {"documents": rag.registry.all()}

    @app.delete("/api/documents")
    def clear_documents():
        rag.clear()
        return {"documents": []}

    @app.post("/api/chat", response_model=ChatResponse)
    def chat(req: ChatRequest):
        return rag.answer(req.question, req.doc_ids, req.history)

    if FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app


app = create_app()
