import urllib.request
import ssl
import mimetypes
import os
import uuid
import json
from typing import Optional
from rbidp.processors.image_to_pdf_converter import convert_image_to_pdf
from rbidp.clients.tesseract_async_client import ask_tesseract

def call_fortebank_textract(pdf_path: str, ocr_engine: str = "tesseract") -> str:
# def call_fortebank_textract(pdf_path: str, ocr_engine: str = "textract") -> str:
    """
    Sends a PDF to ForteBank Textract OCR endpoint and returns the raw response.
    """
    url = "https://dev-ocr.fortebank.com/v1/pdf"
 
    # Read file bytes
    with open(pdf_path, "rb") as f:
        file_data = f.read()
 
    # Prepare multipart/form-data body manually
    boundary = "----WebKitFormBoundary" + uuid.uuid4().hex
    content_type = f"multipart/form-data; boundary={boundary}"
 
    filename = os.path.basename(pdf_path)
    mime_type = mimetypes.guess_type(filename)[0] or "application/pdf"
    if not mime_type or not mime_type.endswith("pdf"):
        mime_type = "application/pdf"
 
    # Construct the multipart body
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="pdf"; filename="{filename}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode("utf-8") + file_data + b"\r\n" + (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="ocr"\r\n\r\n'
        f"{ocr_engine}\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
 
    # Prepare request
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", content_type)
    req.add_header("Accept", "*/*")
 
    # For dev servers (non-SSL)
    context = ssl._create_unverified_context()
 
    with urllib.request.urlopen(req, context=context) as response:
        result = response.read().decode("utf-8")
 
    return result

def ask_textract(pdf_path: str, output_dir: str = "output", save_json: bool = True) -> dict:
    return ask_tesseract(pdf_path, output_dir=output_dir, save_json=save_json)