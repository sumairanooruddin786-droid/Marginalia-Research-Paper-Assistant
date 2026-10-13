import hashlib
import io
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.config import Settings
from app.main import create_app
from app.rag import RAGService


class FakeEmbeddings:
    """Deterministic bag-of-words embeddings so retrieval is testable offline."""

    DIM = 256

    def _vec(self, text):
        v = [0.0] * self.DIM
        for w in re.findall(r"[a-z]{3,}", text.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.DIM] += 1.0
        norm = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)

    # chromadb's langchain wrapper may call the instance directly
    def __call__(self, texts):
        return self.embed_documents(texts)


class FakeLLM:
    """Echoes the first context excerpt with a citation, or NOT_FOUND on demand."""

    def invoke(self, messages):
        text = messages[-1].content
        if "Standalone question" in text:
            follow = re.search(r"Follow-up question: (.*)\n", text).group(1)
            return SimpleNamespace(content=follow)
        if "martian" in text.lower():
            return SimpleNamespace(content="NOT_FOUND")
        first = re.search(r"\[1\] \(Paper: (.+?), page (\d+)\)", text)
        return SimpleNamespace(content=f"The paper discusses this topic [1, 2]. See {first.group(1)}.")


def make_pdf(pages):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for text in pages:
        y = 800
        for line in text.split("\n"):
            c.drawString(50, y, line)
            y -= 16
        c.showPage()
    c.save()
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path):
    settings = Settings(google_api_key="test", data_dir=tmp_path)
    service = RAGService(settings, embeddings=FakeEmbeddings(), llm=FakeLLM())
    return TestClient(create_app(service))


@pytest.fixture()
def paper_pdf():
    return make_pdf(
        [
            "Abstract. We propose a convolutional neural network for classifying chest x-ray images.\n"
            "The model solves the problem of slow manual diagnosis in hospitals and clinics today.",
            "Methodology. We train a ResNet-50 on the ChestXray14 dataset using the Adam optimizer\n"
            "with a learning rate of 0.001 and data augmentation for robustness across scanners.",
            "Limitations. The dataset is imbalanced and future work will explore transformers\n"
            "and multi-center validation to improve generalisation of the classifier overall.",
        ]
    )
