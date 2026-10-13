"""PDF validation and page-by-page text extraction."""
import io
import re
from typing import List, Tuple

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from .errors import AppError


def validate_pdf_upload(filename: str, data: bytes, max_mb: int) -> None:
    if not filename.lower().endswith(".pdf"):
        raise AppError(415, "Unsupported file format. Only PDF files are accepted.")
    if not data:
        raise AppError(400, "The file is empty.")
    if len(data) > max_mb * 1024 * 1024:
        raise AppError(413, f"The file is larger than the {max_mb} MB limit.")
    if not data.lstrip()[:5] == b"%PDF-":
        raise AppError(415, "This file has a .pdf extension but is not a valid PDF.")


def clean_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"-\n(?=[a-z])", "", text)  # re-join words hyphenated at line ends
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pages(data: bytes) -> Tuple[List[Tuple[int, str]], int]:
    """Return ([(page_number starting at 1, text)], total_pages); blank pages are skipped."""
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise AppError(400, "The PDF is password-protected and cannot be read.")
        pages = []
        for number, page in enumerate(reader.pages, start=1):
            text = clean_text(page.extract_text() or "")
            if text:
                pages.append((number, text))
        total = len(reader.pages)
    except AppError:
        raise
    except (PyPdfError, ValueError, KeyError, OSError):
        raise AppError(400, "The PDF is corrupted or could not be read.")
    if not pages:
        raise AppError(
            422,
            "No selectable text was found. This looks like a scanned PDF; "
            "please upload a text-based PDF.",
        )
    return pages, total
