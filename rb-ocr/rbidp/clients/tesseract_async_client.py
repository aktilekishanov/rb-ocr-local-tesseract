from typing import Any, Dict, Optional
import asyncio
import os
import httpx


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
