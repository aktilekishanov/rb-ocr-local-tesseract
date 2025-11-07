# Centralized filenames and constants used across the pipeline

# OCR outputs
OCR_RAW = "ocr_response_raw.json"
OCR_PAGES = "ocr_response_filtered.json"

# GPT: doc type checker
GPT_DOC_TYPE_RAW = "gpt_doc_type_check_raw.json"
GPT_DOC_TYPE_FILTERED = "gpt_doc_type_check_filtered.json"

# GPT: extractor
GPT_EXTRACTOR_RAW = "gpt_extractor_response_raw.json"
GPT_EXTRACTOR_FILTERED = "gpt_extractor_response_filtered.json"

# Merge and validation
MERGED_FILENAME = "merged.json"
VALIDATION_FILENAME = "validation.json"

# User-provided metadata
METADATA_FILENAME = "metadata.json"

# Global settings
MAX_PDF_PAGES = 3
UTC_OFFSET_HOURS = 5