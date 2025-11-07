from rbidp.clients.gpt_client import ask_gpt
import json

PROMPT = """
You are an expert in multilingual document information extraction and normalization.
Your task is to analyze a noisy OCR text that may contain both Kazakh and Russian fragments.

Follow these steps precisely before producing the final JSON:

STEP 1 — UNDERSTAND THE TASK
You must extract the following information:
- fio: full name of the person (e.g. **Иванов Иван Иванович**)
- doc_type: if document matches one of the known templates, classify it as one of:
  - "Лист временной нетрудоспособности (больничный лист)"
  - "Приказ о выходе в декретный отпуск по уходу за ребенком"
  - "Справка о выходе в декретный отпуск по уходу за ребенком"
  - "Выписка из стационара (выписной эпикриз)"
  - "Больничный лист на сопровождающего (если предусмотрено)"
  - "Заключение врачебно-консультативной комиссии (ВКК)"
  - "Справка об инвалидности"
  - "Справка о степени утраты общей трудоспособности"
  - "Приказ о расторжении трудового договора"
  - "Справка о расторжении трудового договора"
  - "Справка о регистрации в качестве безработного"
  - "Приказ работодателя о предоставлении отпуска без сохранения заработной платы"
  - "Справка о неполучении доходов"
  - "Уведомление о регистрации в качестве лица, ищущего работу"
  - "Лица, зарегистрированные в качестве безработных"
  - null
- doc_date: main issuance date (convert to format DD.MM.YYYY)
- valid_until: string | null — for "Приказ о выходе в декретный отпуск по уходу за ребенком" extract the end date (DD.MM.YYYY) if the document states a period like «с DD.MM.YYYY … по DD.MM.YYYY»; otherwise null. For all other document types, set null.

STEP 2 — EXTRACTION RULES
- If several dates exist, choose the main issuance date (usually near header or "№").
- For the decree order, if a validity period is stated, set valid_until to the last date of that period; otherwise null.
- Ignore duplicates or minor typos.
- When the value is missing, set it strictly to `null`.
- Do not invent or assume missing data.
- If both Russian and Kazakh versions exist, output result in Russian.
- Always include surname, given name, and patronymic (if available).
- If the name appears in oblique case (e.g. Ивановой Марине Олеговне), convert it to nominative form (e.g. Иванова Марина Олеговна).
- If the text contains both a full and abbreviated form (e.g. "Аметовой М.М." and "Аметовой Мереке Маратовне"),
  **always select the full explicit version**.


STEP 3 — THINK BEFORE ANSWERING
Double-check:
- Is fio complete (Фамилия Имя Отчество)?
- Is doc_date formatted as DD.MM.YYYY?
- Is valid_until either DD.MM.YYYY or null?
- Are there exactly 4 keys in the final JSON?
- Is doc_type one of the allowed options or null?

STEP 4 — OUTPUT STRICTLY IN THIS JSON FORMAT (no explanations, no extra text, no Markdown formatting, and no ```json formatting)
{
  "fio": string | null,
  "doc_type": string | null,
  "doc_date": string | null,
  "valid_until": string | null,
}

Text for analysis:
{}
"""

def extract_doc_data(pages_obj: dict) -> str:
    pages_json_str = json.dumps(pages_obj, ensure_ascii=False)
    if not pages_json_str:
        return ""
    prompt = PROMPT.replace("{}", pages_json_str, 1)
    return ask_gpt(prompt)