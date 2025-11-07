from typing import Optional, Dict

# Minimal, stable error codes for MVP
ERROR_MESSAGES_RU: Dict[str, str] = {
    # Acquisition/UI
    "PDF_TOO_MANY_PAGES": "PDF должен содержать не более 3 страниц",
    "FILE_SAVE_FAILED": "Не удалось сохранить файл",

    # OCR
    "OCR_FAILED": "Ошибка распознавания OCR",
    "OCR_FILTER_FAILED": "Ошибка обработки страниц OCR",
    "OCR_EMPTY_PAGES": "Не удалось получить текст страниц из OCR",

    # Doc-type check (GPT)
    "DTC_FAILED": "Ошибка проверки типа документа",
    "MULTIPLE_DOCUMENTS": "Файл содержит несколько типов документов",
    "DTC_PARSE_ERROR": "Некорректный ответ проверки типа документа",

    # Extraction (GPT)
    "EXTRACT_FAILED": "Ошибка извлечения данных GPT",
    "GPT_FILTER_PARSE_ERROR": "Ошибка фильтрации ответа GPT",
    "EXTRACT_SCHEMA_INVALID": "Некорректная схема данных извлечения",

    # Merge/Validation
    "MERGE_FAILED": "Ошибка при формировании итогового JSON",
    "VALIDATION_FAILED": "Ошибка валидации",

    # Check-derived
    "FIO_MISMATCH": "ФИО не совпадает",
    "FIO_MISSING": "Не удалось извлечь ФИО из документа",
    "DOC_TYPE_MISMATCH": "Неверный тип документа",
    "DOC_TYPE_MISSING": "Не удалось определить тип документа",
    "DOC_DATE_TOO_OLD": "Устаревшая дата документа",
    "DOC_DATE_MISSING": "Не удалось распознать дату документа",
    "SINGLE_DOC_TYPE_INVALID": "Файл содержит несколько типов документов",
    
    # Stamp detector derived
    "STAMP_NOT_PRESENT": "Печать не обнаружена",
    "STAMP_CHECK_MISSING": "Не удалось выполнить проверку печати",
}


def message_for(code: str) -> Optional[str]:
    return ERROR_MESSAGES_RU.get(code)


def make_error(code: str, message: Optional[str] = None, details: Optional[str] = None) -> Dict[str, Optional[str]]:
    return {
        "code": code,
        "message": message,
        "details": details,
    }