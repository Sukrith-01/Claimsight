FROM python:3.12-slim

# tesseract-ocr: the OCR engine pytesseract calls out to. Without this
# system package, extraction on scanned/image documents fails at runtime
# even though `pip install pytesseract` succeeds silently - pytesseract
# is just a thin wrapper around the tesseract binary, not an OCR engine
# itself.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY configs/ configs/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
