# Findings

- **Async OCR API (tesseract_async)**
  - **POST /v2/pdf**: returns `{"id", "filename", "status":"uploaded", "created_at", "message"}`.
  - **GET /v2/result/{id}**: returns `{"id","filename","status","result":{...}}`.
  - **result.data**: `text`, `lines`, `pages`, `words`, `blocks`, `confidence`.
  - **result.meta**: `lang`, `engine`, `input_type`, `page_count`, `timing_breakdown`, `timestamps`.
  - **result flags**: `result.success`, `result.error`, `result.error_message`.
  - Examples: see info/tesseract_async_POST_response_example.json and info/tesseract_async_GET_response_example.json.

- **Existing client we’re replacing**
  - [rbidp/clients/textract_client.py](cci:7://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/textract_client.py:0:0-0:0) is synchronous and returns:
    - `{"success", "error", "raw_path", "raw_obj", "converted_pdf"}`
    - Converts non-PDF images to PDF before sending.
    - Orchestrator uses [ask_textract(..., save_json=False)](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/textract_client.py:54:0-92:17) then passes `raw_obj` to [filter_textract_response](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/processors/filter_textract_response.py:2:0-61:19).

- **New client to integrate**
  - [rbidp/clients/tesseract_async_client.py](cci:7://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/tesseract_async_client.py:0:0-0:0)
    - Async context manager: [upload()](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/tesseract_async_client.py:27:4-36:26), [get_result()](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/info/test-async-tesseract/tesseract_async_client.py:33:4-39:26), [wait_for_result()](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/info/test-async-tesseract/tesseract_async_client.py:41:4-61:46).
    - Helper [ask_tesseract_async(file_path, base_url, wait=True, ...)](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/tesseract_async_client.py:69:0-104:9) returns:
      - `{"success", "error", "id", "upload", "result}`
      - Here, `result` is the full GET response object containing `{"id","filename","status","result":{...}}`.
  - Test usage pattern shown in info/test-async-tesseract.

- **Downstream processing**
  - [filter_textract_response(obj, output_dir, filename)](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/processors/filter_textract_response.py:2:0-61:19) expects either:
    - `obj.data.pages` (list of `{page_number, text}`) OR
    - AWS Textract `Blocks` structure.
  - Our new service provides `result.data.pages` (via GET). So for compatibility, pass the inner `result` object (the one that has `data.pages`) into [filter_textract_response](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/processors/filter_textract_response.py:2:0-61:19).

# Migration goal

Replace all uses of the Textract client with the async Tesseract endpoints, keeping the pipeline structure and outputs unchanged (ideally no changes to downstream processors and filenames).

# Minimal, safe, drop-in approach (recommended)

- **Add a synchronous wrapper `ask_tesseract(...)`** in [rbidp/clients/tesseract_async_client.py](cci:7://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/tesseract_async_client.py:0:0-0:0) to emulate the existing [ask_textract(...)](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/textract_client.py:54:0-92:17) interface:
  - Inputs: `pdf_path`, `output_dir="ocr"`, `save_json=False`.
  - Behavior:
    - Detect if input is an image; if so, convert via `convert_image_to_pdf(...)` exactly like [ask_textract](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/textract_client.py:54:0-92:17) does.
    - Call [ask_tesseract_async(...)](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/tesseract_async_client.py:69:0-104:9) with `wait=True` using [asyncio.run(...)](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/info/test-async-tesseract/main.py:8:0-15:57) (or loop-safe equivalent).
    - Build a result dict that mirrors the old contract:
      - `success`: from [ask_tesseract_async](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/tesseract_async_client.py:69:0-104:9) result.
      - `error`: from [ask_tesseract_async](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/tesseract_async_client.py:69:0-104:9) result (GET failure or status failed).
      - `raw_obj`: set to the inner GET payload’s `result` object, i.e. `async_result["result"].get("result", {})`. This guarantees `raw_obj.get("data",{}).get("pages")` exists for [filter_textract_response](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/processors/filter_textract_response.py:2:0-61:19).
      - `raw_path`: if `save_json` is True, write raw JSON to the same `TEXTRACT_RAW` filename to avoid changing other code.
      - `converted_pdf`: pass through path if conversion was needed.
    - Make `base_url`, `verify`, `poll_interval`, `timeout`, and `client_timeout` configurable.
      - Default `base_url="https://dev-ocr.fortebank.com/v2"`.
      - In dev, if TLS is self-signed, allow `verify=False`.

- **Orchestrator change (single-line import swap, same call site)**
  - Replace import:
    - From: `from rbidp.clients.textract_client import ask_textract`
    - To: `from rbidp.clients.tesseract_async_client import ask_tesseract`
  - Keep usage identical:
    - `ocr_result = ask_tesseract(str(saved_path), output_dir=str(ocr_dir), save_json=False)`
  - Keep downstream unchanged:
    - [filter_textract_response(ocr_result.get("raw_obj", {}), ...)](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/processors/filter_textract_response.py:2:0-61:19) still works because `raw_obj` now equals inner GET `result` object which has `data.pages`.

- **No changes required** to:
  - [filter_textract_response](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/processors/filter_textract_response.py:2:0-61:19) (it already prefers `obj.data.pages`).
  - Filenames/constants (`TEXTRACT_PAGES` etc.). They can remain as-is for a minimal diff.

# Step-by-step integration

1. Add sync wrapper in tesseract client
   - File: [rb-ocr/rbidp/clients/tesseract_async_client.py](cci:7://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/tesseract_async_client.py:0:0-0:0)
   - Implement `ask_tesseract(...)`:
     - Convert images to PDF using `convert_image_to_pdf(...)` (same logic as in `textract_client`).
     - Call [ask_tesseract_async(...)](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/tesseract_async_client.py:69:0-104:9) with `wait=True`.
     - Compose the returned dict to include `raw_obj = async_resp["result"].get("result", {})`.
     - Optionally persist raw JSON to `TEXTRACT_RAW` when `save_json=True`.

2. Swap the import in orchestrator
   - File: [rb-ocr/rbidp/orchestrator.py](cci:7://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/orchestrator.py:0:0-0:0)
   - Change:
     - `from rbidp.clients.textract_client import ask_textract`
     - To:
       `from rbidp.clients.tesseract_async_client import ask_tesseract`
   - Keep the call site the same:
     - `textract_result = ask_tesseract(str(saved_path), output_dir=str(ocr_dir), save_json=False)`

3. Configuration (optional but recommended)
   - File: [rb-ocr/rbidp/core/config.py](cci:7://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/core/config.py:0:0-0:0)
   - Add:
     - `OCR_BASE_URL = os.getenv("FB_OCR_BASE_URL", "https://dev-ocr.fortebank.com/v2")`
     - `OCR_VERIFY = bool(int(os.getenv("FB_OCR_VERIFY", "1")))`
     - `OCR_POLL_INTERVAL = float(os.getenv("FB_OCR_POLL_INTERVAL", "2.0"))`
     - `OCR_TIMEOUT = float(os.getenv("FB_OCR_TIMEOUT", "300.0"))`
     - `OCR_CLIENT_TIMEOUT = float(os.getenv("FB_OCR_CLIENT_TIMEOUT", "60.0"))`
   - Use these in `ask_tesseract(...)` defaults.
   - Note: Keep existing `TEXTRACT_*` filenames as-is to minimize code changes.

4. Optional cleanup (can be deferred)
   - Rename [filter_textract_response](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/processors/filter_textract_response.py:2:0-61:19) to `filter_ocr_response` and `TEXTRACT_*` filenames to generic `OCR_*` (update imports and references).
   - Update UI text in [rb-ocr/app.py](cci:7://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/app.py:0:0-0:0) to replace “Textract” with “OCR (Tesseract async)”.
   - Remove or archive [textract_client.py](cci:7://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/textract_client.py:0:0-0:0) once you confirm the pipeline runs stably with the new client.

# Interface contract mapping

- Old [ask_textract](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/textract_client.py:54:0-92:17) -> New `ask_tesseract` result mapping:
  - `success`: same semantic (True when OCR finished with usable result).
  - `error`: carry `result.error_message` (or HTTP error) when failed.
  - `raw_obj`: set to the inner GET payload’s `result` (so `raw_obj.data.pages` exists).
  - `raw_path`: only if `save_json=True`.
  - `converted_pdf`: path to converted file if any (preserves previous behavior).

- Filtering step (unchanged):
  - [filter_textract_response(raw_obj, ...)](cci:1://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/processors/filter_textract_response.py:2:0-61:19) reads `raw_obj.data.pages` and writes `TEXTRACT_PAGES` (you can keep the filename).

# Example usage patterns

- Client semantics already validated in info/test-async-tesseract:
  - Upload then optionally wait for completion and use the result.
  - The wrapper simply automates this and shapes the payload for the pipeline.

# Validation plan

- **Smoke test the client**
  - Run a one-off call to `ask_tesseract(...)` (with a PDF or image) and confirm:
    - `success == True`
    - `raw_obj.data.pages` exists and has `len > 0`.

- **End-to-end**
  - From the Streamlit app, upload a document.
  - Confirm:
    - `ocr_pages_filtered_path` is written.
    - `manifest.json` has timings; `ocr_seconds` is non-zero.
    - `final_result.json` and downstream GPT steps behave as before.

# Troubleshooting

- **TLS/SSL**: If the dev server uses self-signed certs, set `verify=False` in [TesseractAsyncClient](cci:2://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/info/test-async-tesseract/tesseract_async_client.py:7:0-61:46) or via `OCR_VERIFY=0`.
- **Timeouts**: For large files increase `OCR_TIMEOUT` and/or `OCR_CLIENT_TIMEOUT`.
- **Non-PDF inputs**: Ensure image-to-PDF conversion is applied (same logic as old client).
- **Error surfacing**: If GET returns `status=failed`, propagate `result.error_message` to the `error` field so the orchestrator reports `OCR_FAILED`.

# Future-proofing

- When the old Textract endpoint is fully removed, delete [textract_client.py](cci:7://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/textract_client.py:0:0-0:0) and consider renaming constants and function names to generic OCR naming.
- The wrapper’s shape matches your pipeline today, so no other parts need to change when Textract is gone.

# Recommended actions

- **[implement_wrapper]** Add `ask_tesseract` sync wrapper in [rbidp/clients/tesseract_async_client.py](cci:7://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/clients/tesseract_async_client.py:0:0-0:0) with image-to-PDF conversion and `raw_obj` mapping to `GET.result`.
- **[swap_import]** Update [rbidp/orchestrator.py](cci:7://file:///Users/aktilekishanov/Documents/career/forte/ds/main-from-server-slim/main/rb-ocr/rbidp/orchestrator.py:0:0-0:0) to import and call `ask_tesseract`.
- **[config]** Add optional `OCR_*` env-driven settings for base URL, verify, and timeouts.
- **[smoke_test]** Run one file through the pipeline and verify outputs and timings.
- **[cleanup_optional]** Update UI wording and, later, rename constants/functions to OCR-generic.

# Task status

- Read all provided info files and the relevant client and pipeline code.
- Produced a concise, actionable integration guide with minimal-diff steps.
- Ready to implement the wrapper and import swap upon your go-ahead.