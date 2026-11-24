"""
Telegram-бот: Markdown -> DOCX / PDF (pandoc + XeLaTeX).

Логика работы:

1. Пользователь присылает файл .md / .markdown / .txt.
2. Бот скачивает файл, определяет наличие LaTeX-формул и показывает
   inline-кнопки «DOCX» и «PDF».
3. По нажатию кнопки документ конвертируется через pandoc
   (DOCX — уравнения Word / OMML; PDF — XeLaTeX, при его отсутствии
   tectonic) и отправляется обратно с исходным именем файла.
4. Интерфейс — русский по умолчанию, переключается командой /language.

Запуск: python bot.py  (токен — в .env или переменной TELEGRAM_BOT_TOKEN)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

from converter import (
    ConverterError,
    detect_latex,
    human_size,
    md_to_docx,
    md_to_pdf,
    normalize_math,
    pick_pdf_engine,
    sanitize_missing_images,
    strip_frontmatter_lang,
)
from i18n import DEFAULT_LANG, t

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN", "")
DEFAULT_LANG_ENV = os.getenv("BOT_DEFAULT_LANG", DEFAULT_LANG)
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
WORK_ROOT = Path(os.getenv("WORK_DIR", str(DATA_DIR / "tmp" / "jobs")))

MAX_INPUT_BYTES = 20 * 1024 * 1024   # лимит Bot API на скачивание файлов
DOC_EXTS = {".md", ".markdown", ".txt"}
JOB_TTL_SECONDS = 3600               # файлы/кнопки живут 1 час
CLEANUP_INTERVAL = 600

logger = logging.getLogger("md-converter-bot")
router = Router()

JOBS: dict = {}


# --------------------------------------------------------------------------
# Хранилище языков (простой JSON-файл, переживает перезапуск)
# --------------------------------------------------------------------------

class LangStore:
    def __init__(self, path: Path, default: str):
        self._path = path
        self._default = default
        self._data: dict = {}
        try:
            if path.exists():
                self._data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            self._data = {}

    def get(self, chat_id: int) -> str:
        return self._data.get(str(chat_id), self._default)

    def set(self, chat_id: int, lang: str) -> None:
        self._data[str(chat_id)] = lang
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        except Exception:
            logger.warning("Не удалось сохранить выбор языка", exc_info=True)


LANGS = LangStore(DATA_DIR / "langs.json", DEFAULT_LANG_ENV)


# --------------------------------------------------------------------------
# Мелкие помощники
# --------------------------------------------------------------------------

def sanitize_stem(file_name: str) -> str:
    """Безопасное имя без расширения для сохранения результата."""
    stem = Path(file_name).stem
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", stem).strip().rstrip(".")
    return (stem[:64] or "document")


def format_latex_report(lang: str, report) -> str:
    if report.has_latex:
        return t(lang, "latex_found",
                 total=report.total, inline=report.inline, display=report.display)
    return t(lang, "latex_absent")


async def safe_edit(cb: CallbackQuery, text: str, kb=None) -> None:
    try:
        if cb.message is not None:
            await cb.message.edit_text(text, reply_markup=kb)
    except Exception:
        logger.debug("edit_text failed", exc_info=True)


async def safe_answer(cb: CallbackQuery, text: "str | None" = None,
                      show_alert: bool = False) -> None:
    """cb.answer, который не роняет хендлер.

    Telegram отвечает 'query is too old and response timeout expired or
    query ID is invalid', если кнопка была нажата слишком давно — это
    не должно прерывать обработку (раньше из-за этого падал весь хендлер).
    """
    try:
        await cb.answer(text=text, show_alert=show_alert)
    except Exception:
        logger.debug("cb.answer failed (stale query?)", exc_info=True)


async def send_upload_actions(bot: Bot, chat_id: int, times: int = 10) -> None:
    """Показывать 'отправляет документ', пока идёт конвертация."""
    for _ in range(times):
        try:
            await bot.send_chat_action(chat_id, ChatAction.UPLOAD_DOCUMENT)
        except Exception:
            return
        await asyncio.sleep(4)


def prepare_md_file(job: dict, lang: str) -> Path:
    """Готовый к pandoc markdown: фронт-матер, картинки, нормализация формул."""
    text = strip_frontmatter_lang(job["md_text"])
    text = sanitize_missing_images(text, job["dir"], t(lang, "img_missing"))
    text = normalize_math(text)
    prepared = job["dir"] / "prepared.md"
    prepared.write_text(text, encoding="utf-8")
    return prepared


def cleanup_job(token: str) -> None:
    job = JOBS.pop(token, None)
    if job:
        shutil.rmtree(job["dir"], ignore_errors=True)


async def cleanup_loop() -> None:
    """Раз в CLEANUP_INTERVAL удалять забытые файлы старше JOB_TTL."""
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL)
        now = time.time()
        for token, job in list(JOBS.items()):
            if now - job["created"] > JOB_TTL_SECONDS:
                JOBS.pop(token, None)
                shutil.rmtree(job["dir"], ignore_errors=True)
        if WORK_ROOT.exists():
            for d in WORK_ROOT.iterdir():
                try:
                    if d.is_dir() and now - d.stat().st_mtime > JOB_TTL_SECONDS:
                        shutil.rmtree(d, ignore_errors=True)
                except Exception:
                    pass


# --------------------------------------------------------------------------
# Команды
# --------------------------------------------------------------------------

@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(m: Message) -> None:
    await m.answer(t(LANGS.get(m.chat.id), "start"))


@router.message(Command("language"))
async def cmd_language(m: Message) -> None:
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Русский", callback_data="lang:ru"),
        InlineKeyboardButton(text="English", callback_data="lang:en"),
    ]])
    await m.answer(t(LANGS.get(m.chat.id), "lang_choose"), reply_markup=kb)


@router.callback_query(F.data.startswith("lang:"))
async def cb_set_language(cb: CallbackQuery) -> None:
    lang = cb.data.split(":", 1)[1]
    if lang not in ("ru", "en"):
        await cb.answer()
        return
    chat_id = cb.message.chat.id if cb.message is not None else cb.from_user.id
    LANGS.set(chat_id, lang)
    await cb.answer(t(lang, "lang_set"), show_alert=True)


# --------------------------------------------------------------------------
# Приём .md файла и выбор формата
# --------------------------------------------------------------------------

@router.message(F.document)
async def on_document(m: Message, bot: Bot) -> None:
    lang = LANGS.get(m.chat.id)
    doc = m.document
    name = doc.file_name or "document.md"
    ext = Path(name).suffix.lower()

    if ext not in DOC_EXTS:
        await m.answer(t(lang, "unsupported"))
        return
    if (doc.file_size or 0) > MAX_INPUT_BYTES:
        await m.answer(t(lang, "too_big"))
        return

    job_dir = WORK_ROOT / uuid.uuid4().hex
    raw = job_dir / "input.md"
    try:
        job_dir.mkdir(parents=True, exist_ok=True)
        await bot.download(doc, destination=raw)
    except Exception:
        logger.warning("download failed for %s", name, exc_info=True)
        shutil.rmtree(job_dir, ignore_errors=True)
        # при превышении лимита Telegram отвечает "file is too big"
        await m.answer(t(lang, "download_failed"))
        return

    data = raw.read_bytes()
    text = None
    for enc in ("utf-8-sig", "cp1251"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        shutil.rmtree(job_dir, ignore_errors=True)
        await m.answer(t(lang, "decode_error"))
        return

    md_text = strip_frontmatter_lang(text)
    report = detect_latex(md_text)

    token = uuid.uuid4().hex[:12]
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(lang, "btn_docx"),
                             callback_data=f"cv:docx:{token}"),
        InlineKeyboardButton(text=t(lang, "btn_pdf"),
                             callback_data=f"cv:pdf:{token}"),
    ]])
    JOBS[token] = {
        "dir": job_dir,
        "chat_id": m.chat.id,
        "md_text": md_text,
        "stem": sanitize_stem(name),
        "created": time.time(),
        "busy": False,
        "kb": kb,
    }
    await m.answer(
        t(lang, "choose_format",
          name=name,
          size=human_size(doc.file_size or 0),
          report=format_latex_report(lang, report) + "\n"),
        reply_markup=kb,
    )


# --------------------------------------------------------------------------
# Конвертация по кнопке
# --------------------------------------------------------------------------

@router.callback_query(F.data.startswith("cv:"))
async def cb_convert(cb: CallbackQuery, bot: Bot) -> None:
    try:
        fmt, token = cb.data[3:].split(":", 1)
    except ValueError:
        await safe_answer(cb)
        return
    fmt = fmt.lower()
    chat_id = cb.message.chat.id if cb.message is not None else cb.from_user.id
    lang = LANGS.get(chat_id)

    job = JOBS.get(token)
    if job is None or fmt not in ("docx", "pdf"):
        await safe_answer(cb)
        await safe_edit(cb, t(lang, "stale_button"))
        return
    if job.get("busy"):
        await safe_answer(cb, t(lang, "busy"))
        return
    await safe_answer(cb)
    job["busy"] = True

    fmt_name = "DOCX" if fmt == "docx" else "PDF"
    await safe_edit(cb, t(lang, "converting", fmt=fmt_name), kb=job["kb"])
    asyncio.create_task(send_upload_actions(bot, job["chat_id"]))

    started = time.time()
    try:
        prepared = prepare_md_file(job, lang)
        out_path = job["dir"] / f"{job['stem']}.{fmt}"
        if fmt == "docx":
            # pandoc/LaTeX — синхронные subprocess-вызовы: гоняем их в
            # отдельном потоке, чтобы не блокировать весь event loop бота
            # (иначе бот замирает, а клики получают 'query is too old')
            await asyncio.to_thread(md_to_docx, prepared, out_path)
            engine = "pandoc (OMML)"
        else:
            engine = pick_pdf_engine()
            await asyncio.to_thread(md_to_pdf, prepared, out_path, engine=engine)
            engine = f"pandoc + {engine}"

        secs = time.time() - started
        await bot.send_document(
            job["chat_id"],
            FSInputFile(out_path, filename=out_path.name),
            caption=t(lang, "done_caption", name=out_path.name, secs=secs, engine=engine),
        )
        await safe_edit(cb, t(lang, "done_status", name=out_path.name), kb=job["kb"])
    except ConverterError as e:
        logger.warning("conversion failed (%s): %s", fmt, str(e)[:500])
        await safe_edit(cb, t(lang, "error", details=str(e)[:900]), kb=job["kb"])
    except Exception as e:  # noqa: BLE001
        logger.exception("unexpected error during conversion")
        details = f"{type(e).__name__}: {e}"[:900]
        await safe_edit(cb, t(lang, "error", details=details), kb=job["kb"])
    finally:
        job["busy"] = False


# --------------------------------------------------------------------------
# Всё остальное
# --------------------------------------------------------------------------

@router.message()
async def fallback(m: Message) -> None:
    await m.answer(t(LANGS.get(m.chat.id), "unknown"))


# --------------------------------------------------------------------------
# Точка входа
# --------------------------------------------------------------------------

async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not TOKEN:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN не задан.\n"
            "Создайте .env рядом с bot.py (см. .env.example) или экспортируйте "
            "переменную окружения, затем запустите бота снова."
        )
    WORK_ROOT.mkdir(parents=True, exist_ok=True)

    bot = Bot(TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    asyncio.create_task(cleanup_loop())

    logger.info("Бот запущен, рабочая папка: %s", WORK_ROOT)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
