from .conftest import make_pdf


def upload(client, name, data, ctype="application/pdf"):
    return client.post("/api/documents", files=[("files", (name, data, ctype))])


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ai_configured"] is True


def test_chat_without_documents(client):
    r = client.post("/api/chat", json={"question": "Summarize this paper."})
    assert r.status_code == 400
    assert "No document uploaded" in r.json()["detail"]


def test_empty_question(client, paper_pdf):
    upload(client, "a.pdf", paper_pdf)
    for q in ("", "   \n "):
        r = client.post("/api/chat", json={"question": q})
        assert r.status_code == 400 and "type a question" in r.json()["detail"]


def test_unsupported_formats(client):
    r = upload(client, "notes.txt", b"hello world", "text/plain")
    res = r.json()["results"][0]
    assert res["status"] == "error" and "Unsupported file format" in res["error"]
    fake = upload(client, "fake.pdf", b"this is not really a pdf").json()["results"][0]
    assert fake["status"] == "error" and "not a valid PDF" in fake["error"]
    assert client.get("/api/documents").json()["documents"] == []


def test_corrupt_pdf(client):
    res = upload(client, "bad.pdf", b"%PDF-1.4 garbage garbage garbage").json()["results"][0]
    assert res["status"] == "error"


def test_no_files(client):
    assert client.post("/api/documents").status_code == 400


def test_upload_and_chat_with_sources(client, paper_pdf):
    r = upload(client, "xray.pdf", paper_pdf)
    body = r.json()
    assert body["indexed"] == 1
    doc = body["results"][0]["document"]
    assert doc["pages"] == 3 and doc["chunks"] >= 3

    r = client.post("/api/chat", json={"question": "Which dataset and optimizer are used in the methodology?"})
    assert r.status_code == 200
    data = r.json()
    assert data["found"] is True and data["sources"]
    top = data["sources"][0]
    assert top["document"] == "xray.pdf" and top["page"] in (1, 2, 3)
    assert "[1][2]" in data["answer"] or "[1]" in data["answer"]


def test_methodology_question_hits_correct_page(client, paper_pdf):
    upload(client, "xray.pdf", paper_pdf)
    data = client.post("/api/chat", json={"question": "ResNet-50 ChestXray14 Adam optimizer learning rate"}).json()
    assert data["sources"][0]["page"] == 2


def test_summary_covers_whole_paper(client, paper_pdf):
    upload(client, "xray.pdf", paper_pdf)
    data = client.post("/api/chat", json={"question": "Summarize this paper."}).json()
    assert data["passages_read"] >= 3


def test_not_found_answer(client, paper_pdf):
    upload(client, "xray.pdf", paper_pdf)
    data = client.post("/api/chat", json={"question": "What do martian rovers eat?"}).json()
    assert data["found"] is False and data["sources"] == []
    assert "isn't available in the uploaded documents" in data["answer"]


def test_duplicate_and_delete(client, paper_pdf):
    upload(client, "xray.pdf", paper_pdf)
    dup = upload(client, "copy.pdf", paper_pdf).json()["results"][0]
    assert dup["status"] == "error" and "already uploaded" in dup["error"]
    doc_id = client.get("/api/documents").json()["documents"][0]["id"]
    assert client.delete(f"/api/documents/{doc_id}").status_code == 200
    assert client.get("/api/documents").json()["documents"] == []
    assert client.delete(f"/api/documents/{doc_id}").status_code == 404
    r = client.post("/api/chat", json={"question": "anything"})
    assert r.status_code == 400


def test_multi_paper_and_selection(client, paper_pdf):
    other = make_pdf(["Quantum error correction codes protect qubits from decoherence in noisy hardware."] * 2)
    upload(client, "xray.pdf", paper_pdf)
    upload(client, "quantum.pdf", other)
    docs = client.get("/api/documents").json()["documents"]
    assert len(docs) == 2
    quantum_id = next(d["id"] for d in docs if d["name"] == "quantum.pdf")
    data = client.post("/api/chat", json={"question": "What is the method?", "doc_ids": [quantum_id]}).json()
    assert {s["document"] for s in data["sources"]} <= {"quantum.pdf"}
    assert data["documents_searched"] == 1


def test_followup_with_history(client, paper_pdf):
    upload(client, "xray.pdf", paper_pdf)
    r = client.post(
        "/api/chat",
        json={
            "question": "And which algorithm?",
            "history": [{"role": "user", "content": "What dataset?"}, {"role": "assistant", "content": "ChestXray14"}],
        },
    )
    assert r.status_code == 200


def test_missing_api_key(tmp_path):
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app
    from app.rag import RAGService
    from .conftest import make_pdf as mk

    svc = RAGService(Settings(google_api_key="", data_dir=tmp_path))
    c = TestClient(create_app(svc))
    res = c.post("/api/documents", files=[("files", ("a.pdf", mk(["Some text content here that is long enough to index properly."]), "application/pdf"))]).json()["results"][0]
    assert res["status"] == "error" and "GOOGLE_API_KEY" in res["error"]
