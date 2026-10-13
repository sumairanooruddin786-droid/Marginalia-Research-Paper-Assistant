"""RAG pipeline: ingest PDFs -> chunk -> embed -> ChromaDB -> retrieve -> Gemini answer."""
import hashlib
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import List, Optional

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .config import Settings
from .errors import AppError
from .pdf_utils import extract_pages, validate_pdf_upload
from .prompts import (
    ANSWER_TEMPLATE,
    CONDENSE_PROMPT,
    NOT_FOUND_MESSAGE,
    SYSTEM_PROMPT,
)
from .registry import Registry
from .schemas import ChatResponse, HistoryTurn, Source

SUMMARY_INTENT = re.compile(
    r"\b(summari[sz]e|summary|overview|tl;?dr|abstract|what is (this|the) paper (about)?|"
    r"main (idea|contribution)s?)\b",
    re.IGNORECASE,
)
CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
EMBED_BATCH = 32
log = logging.getLogger("rpa")


class RAGService:
    def __init__(self, settings: Settings, embeddings=None, llm=None):
        self.settings = settings
        self.registry = Registry(settings.registry_path)
        self._embeddings = embeddings
        self._llm = llm
        self._store: Optional[Chroma] = None
        self._lock = threading.Lock()
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    # ------------------------------------------------------------------ providers
    @property
    def configured(self) -> bool:
        return bool(self.settings.google_api_key) or (
            self._embeddings is not None and self._llm is not None
        )

    def _require_configured(self) -> None:
        if not self.configured:
            raise AppError(
                503,
                "GOOGLE_API_KEY is not set. Add your Gemini API key to the .env file "
                "and restart the server.",
            )

    @property
    def embeddings(self):
        if self._embeddings is None:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            self._embeddings = GoogleGenerativeAIEmbeddings(
                model=self.settings.embedding_model,
                google_api_key=self.settings.google_api_key,
            )
        return self._embeddings

    @property
    def llm(self):
        if self._llm is None:
            from langchain_google_genai import ChatGoogleGenerativeAI

            self._llm = ChatGoogleGenerativeAI(
                model=self.settings.chat_model,
                google_api_key=self.settings.google_api_key,
                temperature=0.1,
                max_retries=2,
            )
        return self._llm

    @property
    def store(self) -> Chroma:
        if self._store is None:
            self.settings.chroma_dir.mkdir(parents=True, exist_ok=True)
            self._store = Chroma(
                collection_name="research_papers",
                embedding_function=self.embeddings,
                persist_directory=str(self.settings.chroma_dir),
                collection_metadata={"hnsw:space": "cosine"},
            )
        return self._store

    # ------------------------------------------------------------------ ingestion
    def ingest(self, filename: str, data: bytes) -> dict:
        """Index one PDF. Returns the registry record; raises AppError on failure."""
        validate_pdf_upload(filename, data, self.settings.max_upload_mb)
        self._require_configured()

        doc_id = hashlib.sha256(data).hexdigest()[:12]
        existing = self.registry.get(doc_id)
        if existing:
            raise AppError(409, f"'{existing['name']}' is already uploaded.")

        pages, total_pages = extract_pages(data)
        chunks: List[Document] = []
        for page_number, text in pages:
            for piece in self._splitter.split_text(text):
                if len(piece.strip()) < 40:  # skip page numbers, stray headers
                    continue
                chunks.append(
                    Document(
                        page_content=piece,
                        metadata={
                            "doc_id": doc_id,
                            "source": filename,
                            "page": page_number,
                            "chunk_index": len(chunks),
                        },
                    )
                )
        if not chunks:
            raise AppError(422, "No usable text could be extracted from this PDF.")

        try:
            self._add_in_batches(doc_id, chunks)
        except Exception as exc:  # roll back partial indexing
            self._delete_vectors(doc_id)
            raise self._friendly_llm_error(exc, "indexing")

        record = {
            "id": doc_id,
            "name": filename,
            "pages": total_pages,
            "chunks": len(chunks),
            "size_kb": round(len(data) / 1024),
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        self.registry.add(record)
        return record

    def _add_in_batches(self, doc_id: str, chunks: List[Document]) -> None:
        for start in range(0, len(chunks), EMBED_BATCH):
            batch = chunks[start : start + EMBED_BATCH]
            ids = [f"{doc_id}-{c.metadata['chunk_index']}" for c in batch]
            for attempt in range(4):
                try:
                    self.store.add_documents(batch, ids=ids)
                    break
                except Exception:
                    if attempt == 3:
                        raise
                    time.sleep(2 ** attempt * 2)  # back off on rate limits

    def _delete_vectors(self, doc_id: str) -> None:
        try:
            self.store.delete(where={"doc_id": doc_id})
        except Exception:
            pass

    def delete(self, doc_id: str) -> None:
        if not self.registry.get(doc_id):
            raise AppError(404, "That document was not found.")
        self._delete_vectors(doc_id)
        self.registry.remove(doc_id)

    def clear(self) -> None:
        for doc_id in self.registry.ids():
            self._delete_vectors(doc_id)
        self.registry.clear()

    # ------------------------------------------------------------------ retrieval
    def _target_ids(self, requested: Optional[List[str]]) -> List[str]:
        known = self.registry.ids()
        if not requested:
            return known
        return [d for d in requested if d in known]

    def _summary_chunks(self, doc_id: str, limit: int = 8) -> List[Document]:
        """Evenly spaced chunks across a paper (intro .. conclusion) for summary requests."""
        got = self.store.get(where={"doc_id": doc_id}, include=["documents", "metadatas"])
        items = sorted(
            zip(got["documents"], got["metadatas"]),
            key=lambda x: (x[1]["page"], x[1]["chunk_index"]),
        )
        if not items:
            return []
        if len(items) > limit:
            step = (len(items) - 1) / (limit - 1)
            items = [items[round(i * step)] for i in range(limit)]
        return [Document(page_content=t, metadata=m) for t, m in items]

    def _retrieve(self, question: str, doc_ids: List[str]) -> List[Document]:
        k = self.settings.top_k
        if SUMMARY_INTENT.search(question):
            docs: List[Document] = []
            for d in doc_ids[:5]:
                docs.extend(self._summary_chunks(d))
            return docs
        if 1 < len(doc_ids) <= 4:  # keep every selected paper represented
            per_doc = max(3, k // len(doc_ids))
            docs = []
            for d in doc_ids:
                docs.extend(self.store.similarity_search(question, k=per_doc, filter={"doc_id": d}))
            return docs
        return self.store.similarity_search(question, k=k, filter={"doc_id": {"$in": doc_ids}})

    # ------------------------------------------------------------------ generation
    @staticmethod
    def _text(response) -> str:
        content = response.content
        if isinstance(content, str):
            return content
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)

    @staticmethod
    def _friendly_llm_error(exc: Exception, stage: str) -> AppError:
        log.error("Gemini error while %s: %r", stage, exc)
        raw = str(exc)
        msg = raw.lower()
        detail = " ".join(raw.split())[:220]
        if "429" in msg or "quota" in msg or "resource_exhausted" in msg or "rate limit" in msg:
            return AppError(429, "The Gemini rate limit or quota was reached. Wait a minute and try again.")
        if "404" in msg or "not found" in msg or "is not supported" in msg:
            return AppError(502, "The Gemini model name was not found. Set GEMINI_CHAT_MODEL in .env to a model "
                                 "your key can use (run: python scripts/check_gemini.py). Details: " + detail)
        if "api key" in msg or "api_key" in msg or "401" in msg or "403" in msg or "permission" in msg:
            return AppError(502, "The Gemini API key was rejected. Check GOOGLE_API_KEY in your .env file. Details: " + detail)
        return AppError(502, f"The AI service failed while {stage}. Details: {detail}")

    def _condense(self, question: str, history: List[HistoryTurn]) -> str:
        turns = [t for t in history if t.role in ("user", "assistant") and t.content.strip()][-6:]
        if not turns:
            return question
        transcript = "\n".join(f"{t.role}: {t.content.strip()[:600]}" for t in turns)
        try:
            out = self._text(
                self.llm.invoke(
                    [HumanMessage(content=CONDENSE_PROMPT.format(history=transcript, question=question))]
                )
            ).strip()
            return out or question
        except Exception:
            return question  # fall back to the raw question

    def answer(self, question: str, doc_ids: Optional[List[str]], history: List[HistoryTurn]) -> ChatResponse:
        question = (question or "").strip()
        if not question:
            raise AppError(400, "Please type a question first.")
        if len(question) > self.settings.max_question_chars:
            raise AppError(400, f"Questions are limited to {self.settings.max_question_chars} characters.")
        if not self.registry.ids():
            raise AppError(400, "No document uploaded yet. Upload at least one research paper (PDF) to start asking questions.")
        targets = self._target_ids(doc_ids)
        if not targets:
            raise AppError(400, "None of the selected papers are available. Select at least one uploaded paper.")
        self._require_configured()

        try:
            standalone = self._condense(question, history)
            docs = self._retrieve(standalone, targets)
        except AppError:
            raise
        except Exception as exc:
            raise self._friendly_llm_error(exc, "searching your papers")

        # de-duplicate while keeping order
        seen, unique = set(), []
        for d in docs:
            key = (d.metadata["doc_id"], d.metadata["chunk_index"])
            if key not in seen:
                seen.add(key)
                unique.append(d)

        if not unique:
            return ChatResponse(answer=NOT_FOUND_MESSAGE, found=False, sources=[], passages_read=0, documents_searched=len(targets))

        context = "\n\n".join(
            f"[{i}] (Paper: {d.metadata['source']}, page {d.metadata['page']})\n{d.page_content}"
            for i, d in enumerate(unique, start=1)
        )
        try:
            raw = self._text(
                self.llm.invoke(
                    [
                        SystemMessage(content=SYSTEM_PROMPT),
                        HumanMessage(content=ANSWER_TEMPLATE.format(context=context, question=standalone)),
                    ]
                )
            ).strip()
        except Exception as exc:
            raise self._friendly_llm_error(exc, "writing the answer")

        if not raw or raw.upper().startswith("NOT_FOUND"):
            return ChatResponse(answer=NOT_FOUND_MESSAGE, found=False, sources=[], passages_read=len(unique), documents_searched=len(targets))

        # normalise "[1, 2]" -> "[1][2]" and keep only citations that exist
        def expand(m: re.Match) -> str:
            nums = [int(n) for n in re.split(r"\s*,\s*", m.group(1))]
            return "".join(f"[{n}]" for n in nums if 1 <= n <= len(unique))

        answer = CITATION.sub(expand, raw)
        cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer)})
        if not cited:  # model forgot to cite: fall back to the top passages
            cited = list(range(1, min(4, len(unique)) + 1))

        sources = []
        for n in cited:
            d = unique[n - 1]
            snippet = re.sub(r"\s+", " ", d.page_content).strip()
            sources.append(
                Source(
                    id=n,
                    document=d.metadata["source"],
                    doc_id=d.metadata["doc_id"],
                    page=d.metadata.get("page"),
                    snippet=snippet[:700],
                )
            )
        return ChatResponse(
            answer=answer,
            found=True,
            sources=sources,
            passages_read=len(unique),
            documents_searched=len(targets),
        )