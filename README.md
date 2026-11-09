# Redactor

Upload an image, PDF or Word file, then redact sensitive data by drawing boxes or using auto-detection (emails, phones, card numbers, IBAN, Italian codice fiscale, SSN, dates, URLs, IPs, custom keywords).

- `frontend/`: Next.js, TypeScript, Tailwind, gsap
- `backend/`: FastAPI, PyMuPDF (PDF), RapidOCR (images and scanned pages), python-docx (Word)

## Run

Backend:

    cd backend
    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    uvicorn app.main:app --reload --port 8000

Frontend:

    cd frontend
    npm install
    npm run dev

Open http://localhost:3000.

## How redaction works

- PDF: regions are burned in with PyMuPDF `apply_redactions`, which removes the underlying text and image pixels. Metadata is scrubbed.
- Image: regions are painted black and the image is re-encoded as PNG, dropping EXIF.
- DOCX: matched text is replaced with block characters in body, tables, headers and footers. Drawing boxes is not available for Word files.
- Files are processed in memory and never stored.
# cc-project
