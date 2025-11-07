from typing import Any, Dict, Optional
import asyncio
import os
import httpx


import mimetypes
import json

from rbidp.processors.image_to_pdf_converter import convert_image_to_pdf
from rbidp.core.config import OCR_RAW

class TesseractAsyncClient:
    def __init__(
        self,
        base_url: str = "https://dev-ocr.fortebank.com/v2",
        timeout: float = 60.0,
        verify: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._verify = verify
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "TesseractAsyncClient":
        self._client = httpx.AsyncClient(timeout=self._timeout, verify=self._verify)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def upload(self, file_path: str) -> Dict[str, Any]:
        if self._client is None:
            raise RuntimeError("Client is not started. Use 'async with TesseractAsyncClient()'.")
        url = f"{self.base_url}/pdf"
        filename = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            files = {"file": (filename, f, "application/pdf")}
            resp = await self._client.post(url, files=files)
        resp.raise_for_status()
        return resp.json()

    async def get_result(self, file_id: str) -> Dict[str, Any]:
        if self._client is None:
            raise RuntimeError("Client is not started. Use 'async with TesseractAsyncClient()'.")
        url = f"{self.base_url}/result/{file_id}"
        resp = await self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    async def wait_for_result(
        self,
        file_id: str,
        poll_interval: float = 2.0,
        timeout: float = 300.0,
    ) -> Dict[str, Any]:
        if self._client is None:
            raise RuntimeError("Client is not started. Use 'async with TesseractAsyncClient()'.")
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        last: Dict[str, Any] = {}
        while True:
            last = await self.get_result(file_id)
            status = str(last.get("status", "")).lower()
            if status in {"done", "completed", "success", "finished", "ready"} or last.get("result") is not None:
                return last
            if status in {"failed", "error"}:
                return last
            if loop.time() >= deadline:
                return last
            await asyncio.sleep(poll_interval)


async def ask_tesseract_async(
    file_path: str,
    *,
    base_url: str = "https://dev-ocr.fortebank.com/v2",
    wait: bool = True,
    poll_interval: float = 2.0,
    timeout: float = 300.0,
    client_timeout: float = 60.0,
    verify: bool = True,
) -> Dict[str, Any]:
    async with TesseractAsyncClient(base_url=base_url, timeout=client_timeout, verify=verify) as client:
        upload_resp = await client.upload(file_path)
        file_id = upload_resp.get("id")
        result_obj: Optional[Dict[str, Any]] = None
        success = False
        error: Optional[str] = None
        if wait and file_id:
            result_obj = await client.wait_for_result(
                file_id, poll_interval=poll_interval, timeout=timeout
            )
            status = str(result_obj.get("status", "")).lower()
            success = bool(
                status in {"done", "completed", "success", "finished", "ready"}
                or result_obj.get("result") is not None
            )
            if not success:
                error = result_obj.get("error") or result_obj.get("message")
        else:
            success = bool(file_id)
        return {
            "success": success,
            "error": error,
            "id": file_id,
            "upload": upload_resp,
            "result": result_obj,
        }


def ask_tesseract(
    pdf_path: str,
    output_dir: str = "output",
    save_json: bool = True,
    *,
    base_url: str = "https://dev-ocr.fortebank.com/v2",
    verify: bool = True,
    poll_interval: float = 2.0,
    timeout: float = 300.0,
    client_timeout: float = 60.0,
) -> Dict[str, Any]:
    work_path = pdf_path
    converted_pdf: Optional[str] = None
    mt, _ = mimetypes.guess_type(pdf_path)
    is_pdf = bool(mt == "application/pdf" or pdf_path.lower().endswith(".pdf"))
    ext = os.path.splitext(pdf_path)[1].lower()
    is_image = bool((mt and isinstance(mt, str) and mt.startswith("image/")) or ext in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".heic", ".heif"})
    if not is_pdf and is_image:
        base_dir = os.path.dirname(pdf_path)
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        desired_path = os.path.join(base_dir, f"{base_name}_converted.pdf")
        converted_pdf = convert_image_to_pdf(pdf_path, output_path=desired_path)
        work_path = converted_pdf

    def _run(coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            new_loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(new_loop)
                return new_loop.run_until_complete(coro)
            finally:
                new_loop.close()
                asyncio.set_event_loop(None)
        else:
            return asyncio.run(coro)

    async_result = _run(
        ask_tesseract_async(
            file_path=work_path,
            base_url=base_url,
            wait=True,
            poll_interval=poll_interval,
            timeout=timeout,
            client_timeout=client_timeout,
            verify=verify,
        )
    )

    success = bool(async_result.get("success"))
    error: Optional[str] = None
    raw_obj: Dict[str, Any] = {}

    get_resp = async_result.get("result")
    if isinstance(get_resp, dict):
        inner = get_resp.get("result")
        if isinstance(inner, dict):
            raw_obj = inner
        else:
            raw_obj = get_resp

    if not success:
        error = async_result.get("error")
        if not error and isinstance(get_resp, dict):
            error = get_resp.get("error_message") or get_resp.get("error")

    raw_path: Optional[str] = None
    if save_json:
        try:
            os.makedirs(output_dir, exist_ok=True)
            raw_path = os.path.join(output_dir, OCR_RAW)
            with open(raw_path, "w", encoding="utf-8") as f:
                json.dump(raw_obj if isinstance(raw_obj, dict) else {}, f, ensure_ascii=False)
        except Exception:
            raw_path = None

    return {
        "success": success,
        "error": error,
        "raw_path": raw_path,
        "raw_obj": raw_obj if isinstance(raw_obj, dict) else {},
        "converted_pdf": converted_pdf,
    }
