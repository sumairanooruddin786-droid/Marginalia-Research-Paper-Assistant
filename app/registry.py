"""Tiny JSON registry listing the papers that have been indexed."""
import json
import threading
from pathlib import Path
from typing import Dict, Optional


class Registry:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._docs: Dict[str, dict] = {}
        if path.exists():
            try:
                self._docs = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._docs = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._docs, indent=2), encoding="utf-8")

    def all(self) -> list:
        with self._lock:
            return sorted(self._docs.values(), key=lambda d: d["uploaded_at"])

    def get(self, doc_id: str) -> Optional[dict]:
        with self._lock:
            return self._docs.get(doc_id)

    def ids(self) -> list:
        with self._lock:
            return list(self._docs.keys())

    def add(self, doc: dict) -> None:
        with self._lock:
            self._docs[doc["id"]] = doc
            self._save()

    def remove(self, doc_id: str) -> bool:
        with self._lock:
            existed = self._docs.pop(doc_id, None) is not None
            if existed:
                self._save()
            return existed

    def clear(self) -> None:
        with self._lock:
            self._docs = {}
            self._save()
