# Tesseract Integration – Implementation Guide (Phased)

This guide outlines a safe, incremental plan to integrate the async Tesseract OCR provider into the existing rb-ocr pipeline without disrupting production.

## Phase 0 — Baseline & Inputs

- **Current pipeline contract**
  - Orchestrator expects OCR result shape: `{ success: bool, error: Optional[str], raw_path: Optional[str], raw_obj: dict, converted_pdf: Optional[str] }`.
  - `filter_textract_response` prefers `raw_obj.data.pages` (list of `{ page_number, text }`).
- **Async service responses (confirmed)**
  - POST /pdf: `{ id, filename, status: "uploaded", created_at, message }`
  - GET /result/{id}: `{ id, filename, status: "completed", result: { data: { text: "..." } } }`
- **Normalization requirement**
  - If only `result.data.text` is provided, map to `raw_obj = { "data": { "pages": [{ "page_number": 1, "text": data.text or "" }] } }`.

## Phase 1 — Client Readiness (no integration)

- **Finalize async client** (`rbidp/clients/tesseract_async_client.py`)
  - Methods: `upload`, `get_result`, `wait_for_result` with polling.
  - TLS control: `verify` flag for self-signed endpoints.
  - Status handling: treat `{completed, done, success, finished, ready}` as terminal-success states.
- **Quick checks**
  - Smoke-test against examples; verify timeout/poll interval behavior and error propagation.

## Phase 2 — Shared Preprocessing (image→PDF)

- **New utility**: `rbidp/processors/input_preprocess.py`
  - `preprocess_input_to_pdf(source_path) -> Tuple[work_pdf_path: str, converted_pdf: Optional[str]]`.
  - Same logic as in `ask_textract` (mimetype/extension-based detection) to keep providers consistent.

## Phase 3 — Provider Abstraction

- **New Protocol**: `rbidp/clients/ocr_provider.py`
  - `class OCRProvider(Protocol):
      def process(self, source_path: str, output_dir: str, save_json: bool) -> dict: ...`
  - Return dict must include: `success, error, raw_path, raw_obj, converted_pdf`.

## Phase 4 — Adapters

- **TextractAdapter**
  - Thin wrapper over existing `ask_textract(...)` for compatibility.
  - Optionally refactor to use `preprocess_input_to_pdf` before calling lower-level request.

- **TesseractAsyncAdapter**
  - Steps inside `process(...)`:
    - Run `preprocess_input_to_pdf` and choose `work_pdf_path`.
    - Use `TesseractAsyncClient` to `upload(work_pdf_path)` and `wait_for_result(id)` with configured timeouts.
    - Read `status` and `result` (per examples, `result.data.text`).
    - Normalize to `raw_obj.data.pages` (wrap text if pages not provided).
    - Set `success` if status is terminal-success and pages/text exist; else set `error` from `message`/`error`.
    - If `save_json`, write normalized JSON to `output_dir/TEXTRACT_RAW` and set `raw_path`.
  - **Async-in-sync safety**: If an event loop is already running, execute in a background thread with a fresh loop; else use `asyncio.run(...)`.

## Phase 5 — Config & Factory

- **Config keys** (non-breaking defaults):
  - `OCR_PROVIDER=textract | tesseract_async` (default: `textract`).
  - `TESSERACT_BASE_URL` (default: `https://dev-ocr.fortebank.com/v2`).
  - `TESSERACT_CLIENT_TIMEOUT_SEC` (e.g., 60–120).
  - `TESSERACT_POLL_INTERVAL_SEC` (e.g., 2.0).
  - `TESSERACT_WAIT_TIMEOUT_SEC` (e.g., 300).
  - `TESSERACT_VERIFY_TLS=true|false`.
- **Factory**: `rbidp/clients/ocr_factory.py`
  - `make_ocr_provider_from_env() -> OCRProvider` returns configured TextractAdapter or TesseractAsyncAdapter.

## Phase 6 — Orchestrator Wiring (minimal)

- **Replace only the OCR call**
  - Before: `textract_result = ask_textract(str(saved_path), output_dir=str(ocr_dir), save_json=False)`.
  - After: `provider = make_ocr_provider_from_env(); textract_result = provider.process(str(saved_path), output_dir=str(ocr_dir), save_json=False)`.
- **Keep everything else unchanged**
  - PDF page limit guard remains before OCR.
  - `t_ocr` timing remains accurate around provider call.
  - Stamp detection deferral and GPT stages remain unchanged.
  - Optionally write `ocr_provider` into `metadata.json` for traceability.

## Phase 7 — Testing Strategy

- **Unit tests**
  - TextractAdapter/TesseractAsyncAdapter: success, failure, timeout, and image→PDF path.
  - Contract test: ensure adapters always return required dict keys and normalized `raw_obj.data.pages`.
- **Integration tests**
  - End-to-end on small fixtures; verify `filter_textract_response` receives expected structure.
  - Golden outputs for `textract_response_filtered.json`.

## Phase 8 — Packaging & Deployment

- **Dependencies**
  - Ensure `httpx` (and deps) are in the server venv or wheelhouse.
- **Dev-first rollout**
  - Enable `OCR_PROVIDER=tesseract_async` on the dev service (e.g., `streamlit-dev.service` on port 8006).
  - Validate outputs and timings; compare with current Textract.
- **Prod toggle**
  - Keep default `textract`. Switch via env only after acceptance.

## Phase 9 — Observability & Logging

- **Manifest/metadata**
  - Include `ocr_provider`, timing (`ocr_seconds`), and normalized file paths when saved.
- **Error surfaces**
  - Uniform error codes in orchestrator paths (`OCR_FAILED`, `OCR_EMPTY_PAGES`, etc.).
  - Adapter returns clear `error` messages on HTTP/JSON exceptions.

## Phase 10 — Rollout & Rollback

- **Canary**
  - Run a subset through dev with `tesseract_async`; compare accuracy/latency.
- **Fallback**
  - Immediate rollback: set `OCR_PROVIDER=textract` and restart service.
- **No-downtime**
  - Since it’s a toggle, no code revert is required for rollback.

## Phase 11 — Risks & Mitigations

- **TLS verification**: Use `TESSERACT_VERIFY_TLS=false` for self-signed certs in dev; true in prod.
- **Event loop conflicts**: Use background thread runner when a loop is active.
- **Status vocabulary drift**: Treat presence of `result` as a secondary success signal; log unknown statuses.
- **Oversized text**: If `data.text` is very large, consider optional paging heuristics (not required initially).

## Phase 12 — Acceptance Criteria

- **Functional**
  - With `OCR_PROVIDER=tesseract_async`, pipeline produces valid `textract_response_filtered.json` and proceeds identically to Textract path.
- **Non-functional**
  - No regressions when `OCR_PROVIDER=textract` (default).
  - Clear logs, accurate `t_ocr`, and manifest fields populated.
- **Operational**
  - Easy toggle via env; rollback is immediate.
