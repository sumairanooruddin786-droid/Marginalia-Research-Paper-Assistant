"""Run from the project folder:  python scripts/check_gemini.py
Tests your API key, the embedding model and the chat model, and lists usable models."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import get_settings  # noqa: E402

s = get_settings()
print("Chat model     :", s.chat_model)
print("Embedding model:", s.embedding_model)
print("Fallback model :", s.fallback_model)
if not s.google_api_key:
    sys.exit("GOOGLE_API_KEY is empty. Put it in .env")

from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings  # noqa: E402

try:
    GoogleGenerativeAIEmbeddings(model=s.embedding_model, google_api_key=s.google_api_key).embed_query("test")
    print("Embeddings : OK")
except Exception as e:
    print("Embeddings : FAILED ->", str(e)[:300])
try:
    r = ChatGoogleGenerativeAI(model=s.chat_model, google_api_key=s.google_api_key).invoke("Say OK")
    print("Chat       : OK ->", str(r.content)[:60])
except Exception as e:
    print("Chat       : FAILED ->", str(e)[:300])

try:
    from google import genai

    client = genai.Client(api_key=s.google_api_key)
    names = [m.name for m in client.models.list() if "generateContent" in (m.supported_actions or [])]
    print("\nModels your key can use for chat (put one in GEMINI_CHAT_MODEL):")
    for n in names:
        print("  ", n.replace("models/", ""))
except Exception as e:
    print("Could not list models ->", str(e)[:200])