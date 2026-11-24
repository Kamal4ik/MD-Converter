"""
Тексты интерфейса бота на двух языках: русский (по умолчанию) и English.

Переключение — команда /language. Выбранный язык хранится на чат.
"""

DEFAULT_LANG = "ru"

TEXTS = {
    "ru": {
        "start": (
            "Привет! Я конвертирую Markdown в DOCX и PDF.\n\n"
            "Отправьте мне файл .md, .markdown или .txt — я сохраню заголовки, "
            "списки, таблицы, код и LaTeX-формулы.\n\n"
            "Формулы: для PDF они рендерятся через XeLaTeX, "
            "а в DOCX становятся редактируемыми уравнениями Word.\n\n"
            "Команды:\n"
            "/language — выбрать язык интерфейса\n"
            "/help — эта справка"
        ),
        "unknown": (
            "Отправьте мне Markdown-файл (.md), и я сконвертирую его в DOCX или PDF."
        ),
        "unsupported": (
            "Похоже, это не Markdown-файл. Пришлите файл с расширением "
            ".md, .markdown или .txt."
        ),
        "too_big": (
            "Файл больше 20 МБ — Telegram не позволяет ботам скачивать файлы "
            "такого размера. Уменьшите объём (например, сожмите картинки) "
            "и пришлите файл снова."
        ),
        "download_failed": (
            "Не удалось скачать файл. Попробуйте отправить его ещё раз."
        ),
        "decode_error": (
            "Не удалось прочитать файл как текст (пробовал UTF-8 и Windows-1251). "
            "Пересохраните файл в UTF-8 и отправьте снова."
        ),
        "choose_format": (
            "Файл: {name} ({size})\n\n{report}\nВыберите формат конвертации:"
        ),
        "latex_found": (
            "Обнаружены LaTeX-формулы: {total} "
            "(строчных: {inline}, выносных: {display}).\n"
            "PDF — рендер формул через XeLaTeX; "
            "DOCX — формулы станут уравнениями Word."
        ),
        "latex_absent": "LaTeX-формулы не обнаружены — обычная Markdown-конвертация.",
        "converting": "Конвертирую в {fmt}. Обычно это секунды, максимум — пара минут.",
        "busy": "Уже конвертирую этот файл — подождите немного.",
        "stale_button": (
            "Эта кнопка уже недействительна: файл обработан или бот был "
            "перезапущен. Пришлите .md файл заново."
        ),
        "error": (
            "Не удалось сконвертировать документ.\n\n"
            "Причина:\n{details}\n\n"
            "Что проверить:\n"
            "— установлен ли LaTeX-движок для PDF (MiKTeX или tectonic);\n"
            "— валидный ли это Markdown;\n"
            "— синтаксис формул (закрыты ли все $ и фигурные скобки);\n"
            "— доступны ли картинки по своим ссылкам."
        ),
        "done_caption": "{name} · {secs:.1f} с · {engine}",
        "done_status": (
            "Готово. Файл {name} отправлен отдельным сообщением.\n"
            "Можно выбрать и другой формат."
        ),
        "lang_choose": "Выберите язык / Choose language:",
        "lang_set": "Язык интерфейса: русский.",
        "img_missing": "изображение недоступно: {path}",
        "btn_docx": "DOCX (Word)",
        "btn_pdf": "PDF (LaTeX)",
    },
    "en": {
        "start": (
            "Hi! I convert Markdown to DOCX and PDF.\n\n"
            "Send me a .md, .markdown or .txt file — I will keep headings, lists, "
            "tables, code and LaTeX math.\n\n"
            "Math: for PDF it is rendered via XeLaTeX; "
            "in DOCX formulas become editable Word equations.\n\n"
            "Commands:\n"
            "/language — switch interface language\n"
            "/help — this help"
        ),
        "unknown": (
            "Send me a Markdown file (.md) and I will convert it to DOCX or PDF."
        ),
        "unsupported": (
            "This does not look like a Markdown file. Please send a file with "
            ".md, .markdown or .txt extension."
        ),
        "too_big": (
            "The file is over 20 MB — Telegram does not let bots download files "
            "that big. Reduce its size (e.g. compress images) and send it again."
        ),
        "download_failed": "Could not download the file. Please try sending it again.",
        "decode_error": (
            "Could not read the file as text (tried UTF-8 and Windows-1251). "
            "Save it as UTF-8 and send it again."
        ),
        "choose_format": "File: {name} ({size})\n\n{report}\nChoose the output format:",
        "latex_found": (
            "LaTeX math detected: {total} formula(s) "
            "({inline} inline, {display} display).\n"
            "PDF — rendered via XeLaTeX; DOCX — formulas become editable "
            "Word equations."
        ),
        "latex_absent": "No LaTeX math found — plain Markdown conversion.",
        "converting": "Converting to {fmt}. Usually seconds, at most a couple of minutes.",
        "busy": "Already converting this file — please wait.",
        "stale_button": (
            "This button is no longer valid: the file was processed or the bot "
            "was restarted. Please send the .md file again."
        ),
        "error": (
            "Conversion failed.\n\n"
            "Reason:\n{details}\n\n"
            "Please check:\n"
            "— a LaTeX engine for PDF is installed (MiKTeX or tectonic);\n"
            "— the file is valid Markdown;\n"
            "— math syntax (all $ and braces are closed);\n"
            "— image links are reachable."
        ),
        "done_caption": "{name} · {secs:.1f} s · {engine}",
        "done_status": (
            "Done. {name} was sent as a separate message.\n"
            "You can also pick another format."
        ),
        "lang_choose": "Выберите язык / Choose language:",
        "lang_set": "Interface language: English.",
        "img_missing": "image unavailable: {path}",
        "btn_docx": "DOCX (Word)",
        "btn_pdf": "PDF (LaTeX)",
    },
}


def t(lang: str, key: str, **kwargs) -> str:
    """Получить текст по языку и ключу; при отсутствии — русский вариант."""
    template = TEXTS.get(lang, TEXTS[DEFAULT_LANG]).get(key)
    if template is None:
        template = TEXTS[DEFAULT_LANG][key]
    if kwargs:
        return template.format(**kwargs)
    return template
