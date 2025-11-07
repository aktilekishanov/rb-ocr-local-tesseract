from rbidp.clients.gpt_client import ask_gpt
from rbidp.clients.textract_client import ask_textract
from rapidfuzz import fuzz  
 
def main():

    # # Textract (three-line caller)
    # # work pc path: "C:/Users/AIshanov/personal/ds/rb-ocr/ocr-local/ocr-local-main/data/Приказ о выходе в декретный отпуск/3. Приказ о выходе в декретный отпуск.pdf"
    # pdf_path = "C:/Users/AIshanov/personal/ds/rb-ocr/ocr-local/ocr-local-main/data/Приказ о выходе в декретный отпуск/3. Приказ о выходе в декретный отпуск.pdf"
    # text = ask_textract(pdf_path, output_dir="output", save_json=True, save_filtered_json=True)
    # print(text)
    
    # # GPT (three-line caller)
    # prompt = "when is christmas in the states?"
    # response = ask_gpt(prompt)
    # print(response)



#     # TEST GPT
#     prompt = """
#     You are an expert in multilingual document information extraction and normalization.
#     Your task is to analyze a noisy OCR text that may contain both Kazakh and Russian fragments.

#     Follow these steps precisely before producing the final JSON:

#     STEP 1 — UNDERSTAND THE TASK
#     You must extract the following information:
#     - fio: full name of the person (e.g. **Иванов Иван Иванович**)
#     - doc_type: if document matches one of the known templates, classify it as one of:
#     -- "Лист временной нетрудоспособности (больничный лист)"
#     -- "Приказ о выходе в декретный отпуск по уходу за ребенком"
#     -- "Справка о выходе в декретный отпуск по уходу за ребенком"
#     -- "Выписка из стационара (выписной эпикриз)"
#     -- "Больничный лист на сопровождающего (если предусмотрено)"
#     -- "Заключение врачебно-консультативной комиссии (ВКК)"
#     -- "Справка об инвалидности"
#     -- "Справка о степени утраты общей трудоспособности"
#     -- "Приказ/Справка о расторжении трудового договора"
#     -- "Справка о регистрации в качестве безработного"
#     -- "Приказ работодателя о предоставлении отпуска без сохранения заработной платы"
#     -- "Справка о неполучении доходов"
#     -- "Уведомление о регистрации в качестве лица, ищущего работу"
#     -- "Лица, зарегистрированные в качестве безработных"
#     -- null
#     - doc_date: main issuance date (convert to format DD.MM.YYYY)
#     - single_doc_type: true | false,
#     - single_doc_type_confidence: 0-100,

#     STEP 2 — EXTRACTION RULES
#     - If several dates exist, choose the main *issuance* date (usually near header or "№").
#     - Ignore duplicates or minor typos.
#     - When the value is missing, set it strictly to `null`.
#     - Do not invent or assume missing data.
#     - If both Russian and Kazakh versions exist, output result in Russian.

#     STEP 3 — THINK BEFORE ANSWERING
#     **Double-check**:
#     - Is fio complete (Фамилия Имя Отчество)?
#     - Is doc_date formatted as DD.MM.YYYY?
#     - Are there exactly 3 keys in the final JSON?
#     - Is doc_type one of the allowed options or null?

#     STEP 4 — OUTPUT STRICTLY IN THIS JSON FORMAT (no explanations, no extra text, no Markdown formatting, and **no ```json** formatting)
#     {{
#     "fio": string | null,
#     "doc_type": string | null,
#     "doc_date": string | null,
#     }}

#     Text for analysis:
#     {{
#   "pages": [
#     {
#       "page_number": 1,
#       "text": "«SMART SOLUTION\nТоварищество c ограниченной\nPERSONAL» (CMAPT\nsmart\nответственностью\nСОЛЮШН ПЕРСОНАЛ)»\nsolutions\n«SMART SOLUTION\nжауапкершілігі шектеулі cepiKTecTiΓi\nPERSONAL» (CMAPT\nСОЛЮШН ПЕРСОНАЛ)»\nБУЙРЫҚ\nПРИКАЗ\n2024 жылғы 01 караша\n№ 3481-ЛC\nАлматы каласы\nгород Алматы\nЕнбек шартын бузу туралы\nБУЙЫРАМЫН:\n1. Сакарияева Наргиз Кайратовна, Лореаль Ka3axcTaH - Lux белімінін Сулулык\nжөніндегі кенесші 2024 ЖЫЛҒЫ 26 наурыз № 00343 енбек шарты 2024 ЖЫЛҒЫ 01\nкараша бастап Ka3aKcTaH Республикасы Енбек кодексінін 49-6. 5) TT. сәйкес,\nкызметкердін бастамасы бойынша БУЗЫЛСЫН.\n2. 2024 ЖЫЛҒЫ 26 наурыз бастап 2024 ЖЫЛҒЫ 01 караша дейінгі жүмыс Ke3eHi үшін\nкунтізбелік 8 (ceri3) күн мөлшерінде пайдаланылмаган жыл сайынғы акы\nтеленетін енбек дамалысы өтемакы теленсін.\nНегіздеме: 01.11.2024 Сакарияева H.K. өтініші.\nГоварищество\nSmart Solution\nОперациялык менеджер ersonal\nB. Мукуёва\n(Chapt\nПерсонал)\n*\nБүйрыкпен таныстым:\nСакарияева H.K\nCaronf\n01.11.2024\n(колы)"
#     },
#     {
#       "page_number": 2,
#       "text": "«SMART SOLUTION\nТоварищество C ограниченной\nPERSONAL» (CMAPT\nsmart\nответственностью\nСОЛЮШН ПЕРСОНАЛ)»\nsolutions\n«SMART SOLUTION\nжауапкершілігі шектеулі cepiKTecTiΓi\nPERSONAL» (CMAPT\nСОЛЮШН ПЕРСОНАЛ)»\nБУЙРЫҚ\nПРИКАЗ\n01 ноября 2024 года\n№ 3481-JC\nАлматы каласы\nгород Алматы\no расторжении трудового договора\nПРИКАЗЫВАЮ:\n1. РАСТОРГНУТЬ трудовой договор oT 26 MapTa 2024 года № 00343 c\nСакарияевой Наргиз Кайратовной, Консультантом красоты отдела Лореаль\nKa3axcTaH Lux 01 ноября 2024 года B соответствии c пп. 5 cT. 49 Трудового\nкодекса PK. Расторжение трудового договора по инициативе работника.\n2. Выплатить компенсацию 3a неиспользованный оплачиваемый ежегодный\nтрудовой отпуск B количестве 8 (восемь) календарных дней 3a период работы c\n26 MapTa 2024 года по 01 ноября 2024 года.\nОснование:\nЗаявление Сакарияева H.K. OT 01.11.2024.\nSmart Solution\nОперационный менеджер Personal\nСолюши\nB. Мукуёва\nПерсонал)\n/\nJ\n*\nC приказом ознакомлен(а):\nСакарияева H.K.\nCamel\n01.11.2024"
#     }
#   ]
# }}
#     """
#     response = ask_gpt(prompt)
#     print(response)

    score = fuzz.token_sort_ratio("Катубаева Жанара Канатовна", "Катубаева Жанара Ханатовна")
    print(score)
 
if __name__ == "__main__":
    main()

 