"""Central configuration, read once from environment variables / .env."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    google_api_key: str = os.getenv("GOOGLE_API_KEY", "").strip()
    chat_model: str = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.8-flash")
    fallback_model: str = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.8-flash-lite")
    embedding_model: str = os.getenv("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001")
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "1000"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "150"))
    top_k: int = int(os.getenv("TOP_K", "8"))
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "25"))
    max_question_chars: int = 2000
    data_dir: Path = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def registry_path(self) -> Path:
        return self.data_dir / "documents.json"

def get_settings() -> Settings:
    return Settings()