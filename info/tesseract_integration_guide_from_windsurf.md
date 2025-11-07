# Findings

- **Current usage**
  - [orchestrator.run_pipeline](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/orchestrator.py:191:0-780:21) imports and calls [ask_textract(...)](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/textract_client.py:54:0-92:17) from `rbidp.clients.textract_client`.
  - [ask_textract](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/textract_client.py:54:0-92:17):
    - Converts images to PDF if needed.
    - Calls [call_fortebank_textract](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/textract_client.py:9:0-52:17) (`POST https://dev-ocr.fortebank.com/v1/pdf` with multipart `pdf` and `ocr=tesseract`).
    - Returns a dict with keys:
      - `success: bool`
      - `error: Optional[str]`
      - `raw_path: str`
      - `raw_obj: dict`
      - `converted_pdf: Optional[str]`
  - Downstream expects:
    - `textract_result.get("success")`
    - `textract_result.get("raw_obj")` for `filter_textract_response(...)`
    - Optional `converted_pdf`

- **New async client (test version)**
  - [info-about-server/test-async-tesseract/tesseract_async_client.py](cci:7://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/info-about-server/test-async-tesseract/tesseract_async_client.py:0:0-0:0):
    - Endpoints: `POST {base_url}/pdf` (multipart `file`) and `GET {base_url}/result/{id}`; default base `https://dev-ocr.fortebank.com/v2`.
    - Async workflow: upload -> poll until ready -> returns JSON with `status/result`.
  - Your added client [rbidp/clients/tesseract_async_client.py](cci:7://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/tesseract_async_client.py:0:0-0:0) mirrors these methods:
    - [upload(file_path)](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/tesseract_async_client.py:23:4-32:26), [get_result(file_id)](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/tesseract_async_client.py:34:4-40:26), [wait_for_result(file_id, ...)](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/tesseract_async_client.py:42:4-57:46).

# Integration Goals

- Keep `textract_client` intact.
- Add a toggle to choose OCR provider per run/environment.
- Do not break orchestrator’s expectations for OCR result structure.
- Keep world-class code quality: clean abstractions, testable, minimal coupling.

# Proposed Design

- **Introduce an OCR provider abstraction (Strategy pattern)**
  - Define a minimal interface/Protocol for OCR providers that returns the same shape as today’s [ask_textract](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/textract_client.py:54:0-92:17).
    - Example Protocol `OCRProvider`:
      - `process(source_path: str, output_dir: str, save_json: bool) -> dict`
      - Return dict must include:
        - `success: bool`
        - `error: Optional[str]`
        - `raw_path: Optional[str]`
        - `raw_obj: dict`
        - `converted_pdf: Optional[str]`
  - Provide two adapters implementing this:
    - **TextractAdapter**: thin wrapper over existing [ask_textract(...)](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/textract_client.py:54:0-92:17).
    - **TesseractAsyncAdapter**: wraps [TesseractAsyncClient](cci:2://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/tesseract_async_client.py:7:0-18:57) and normalizes response to the same dict format.

- **Centralize pre-processing (image→PDF)**
  - Today, [ask_textract](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/textract_client.py:54:0-92:17) does conversion itself.
  - To equalize behavior across providers, extract the conversion logic into a shared helper (e.g., `preprocess_input_to_pdf(source_path) -> Tuple[work_pdf_path, converted_pdf_path_or_none]`).
  - Both adapters call this helper to ensure identical input to OCR providers.

- **Sync orchestrator compatibility**
  - Orchestrator is synchronous. Keep it that way.
  - In `TesseractAsyncAdapter.process`, run the async flow safely:
    - Use [asyncio.run(...)](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/info-about-server/test-async-tesseract/main.py:8:0-15:57) internally (or a small event loop helper) to:
      - [upload()](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/tesseract_async_client.py:23:4-32:26)
      - [wait_for_result(...)](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/tesseract_async_client.py:42:4-57:46)
  - Normalize the final JSON to `raw_obj` and set `success/error` fields.

- **Config and toggle**
  - Add env/config key: `OCR_PROVIDER` with values `textract` (default) or `tesseract_async`.
  - Optional provider-specific config:
    - `TESSERACT_BASE_URL` (default `https://dev-ocr.fortebank.com/v2`)
    - `TESSERACT_TIMEOUT_SEC` (e.g., 120)
    - `TESSERACT_POLL_INTERVAL_SEC` (e.g., 2.0)
    - `TESSERACT_WAIT_TIMEOUT_SEC` (e.g., 300)
  - Factory function:
    - `make_ocr_provider_from_env() -> OCRProvider`
    - Reads env/config, returns the appropriate adapter instance with settings.

- **Return shape compatibility**
  - The async endpoint likely returns something like:
    - Upload: `{ id: "..." }`
    - Poll: `{ status: "...", result: {...} }` (or similar)
  - Adapter must map to:
    - `success = (status in {"done","completed","success","finished","ready"} and result present)` or direct `result.success`.
    - `raw_obj = result` (the full OCR JSON needed by `filter_textract_response`).
    - `error = None` when success, otherwise best-effort message (e.g., from `status` or an `error` field).
    - `raw_path` optional: write the JSON to `output_dir/TEXTRACT_RAW` for parity, or set to `None` if you do not persist.
    - `converted_pdf` from the shared preprocessor.

- **Timing and metrics**
  - Orchestrator already measures `t_ocr`. Keep it unchanged; it measures around the provider call.
  - The adapter should not alter orchestrator timing; just return the dict.
  - Consider provider name in artifacts or metadata for observability (e.g., write `metadata["ocr_provider"]`).

- **Error handling**
  - On HTTP or JSON errors, return:
    - `success=False`
    - `error=str(e)`
    - `raw_obj={}`
  - Keep orchestrator early-return logic intact.

- **Testing**
  - Unit tests for both adapters:
    - Success flow, failure flow, timeout flow.
    - Image input conversion path.
  - Contract test that `OCRProvider.process` returns the required dict keys for both providers.

# Proposed Integration Steps (no code yet)

- **1) Define interface**
  - New module: `rbidp/clients/ocr_provider.py`
  - `class OCRProvider(Protocol): process(...) -> dict`

- **2) Extract preprocessing helper**
  - New utility: `rbidp/processors/input_preprocess.py` with `preprocess_input_to_pdf(...)`.

- **3) Implement adapters**
  - `rbidp/clients/textract_adapter.py` using [ask_textract(...)](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/textract_client.py:54:0-92:17) or calling the new preprocessor then [call_fortebank_textract](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/textract_client.py:9:0-52:17).
  - `rbidp/clients/tesseract_async_adapter.py` using [TesseractAsyncClient](cci:2://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/tesseract_async_client.py:7:0-18:57), with [asyncio.run(...)](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/info-about-server/test-async-tesseract/main.py:8:0-15:57) inside, normalize outputs, optionally write raw JSON to `output_dir/TEXTRACT_RAW`.

- **4) Provider factory and config**
  - Add config/env reading in [rbidp/core/config.py](cci:7://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/core/config.py:0:0-0:0) (non-breaking defaults).
  - `rbidp/clients/ocr_factory.py` with `make_ocr_provider_from_env()`.

- **5) Orchestrator wiring (minimal change)**
  - Replace the direct call to [ask_textract](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/textract_client.py:54:0-92:17) with:
    - `provider = make_ocr_provider_from_env()`
    - `textract_result = provider.process(str(saved_path), output_dir=str(ocr_dir), save_json=False)`
  - Keep the rest of the pipeline untouched.

- **6) Optional**
  - Write `ocr_provider` into `metadata.json` for traceability.

# Benefits

- Clean separation via Strategy pattern.
- Minimal orchestrator changes.
- Shared preprocessing avoids divergence.
- Easy to add more OCR providers later.
- Testable, configurable, and production-safe (toggle by env).

If this plan works for you, I’ll draft the modules and wiring exactly as described without touching existing behavior for the default (`textract`) provider.