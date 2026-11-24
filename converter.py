r"""
Конвертер Markdown -> DOCX / PDF на базе pandoc.

Ключевая задача модуля — корректная обработка LaTeX-формул:

* обнаружение формул ($...$, $$...$$, \(..\), \[..\] и окружений
  equation / align / gather / multline / eqnarray и т.п.) с отчётом;
* нормализация записи: окружения и \[..\] приводятся к виду $$..$$,
  \(..\) к виду $..$ (pandoc так надёжнее всего конвертирует и в OMML
  для DOCX, и в LaTeX для PDF);
* из формул удаляются \label{...}, \nonumber, \notag (они не влияют на
  внешний вид, но ломают конвертацию в Word-уравнения);
* картинки: внешние URL скачивает сам pandoc; локальные пути, которых
  нет рядом с файлом, заменяются плейсхолдером, чтобы конвертация не
  падала целиком.

PDF рендерится через XeLaTeX; если xelatex не установлен, но есть
tectonic (тоже XeTeX-движок), используется он.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ConverterError",
    "LatexReport",
    "detect_latex",
    "normalize_math",
    "strip_frontmatter_lang",
    "sanitize_missing_images",
    "md_to_docx",
    "md_to_pdf",
    "pick_pdf_engine",
    "pick_fonts",
    "human_size",
]


class ConverterError(RuntimeError):
    """Ошибка конвертации с человекочитаемым сообщением."""


# --------------------------------------------------------------------------
# 1. Детект LaTeX-формул
# --------------------------------------------------------------------------

# Строчная формула $...$: открывающий $ не экранирован другим $, после него
# не пробел; перед закрывающим $ не пробел, после него не цифра (эвристика
# как в pandoc, чтобы не считать деньги "цена $5, а доставка $10" формулой).
INLINE_DOLLAR_RE = re.compile(r"(?<!\$)\$(?!\s)((?:\\.|[^$\\])+?)(?<!\s)\$(?!\d)")
DISPLAY_DOLLAR_RE = re.compile(r"\$\$(.+?)\$\$", re.S)
PAREN_RE = re.compile(r"\\\((.+?)\\\)", re.S)      # \( ... \)
BRACKET_RE = re.compile(r"\\\[(.+?)\\\]", re.S)    # \[ ... \]

# Выносные окружения: имя -> (открывающая обёртка, закрывающая обёртка).
_ENV_ALIGNED = ("$$\\begin{aligned}", "\\end{aligned}$$")
_ENV_GATHERED = ("$$\\begin{gathered}", "\\end{gathered}$$")
ENV_MAP = {
    "equation":    ("$$", "$$"),
    "equation*":   ("$$", "$$"),
    "displaymath": ("$$", "$$"),
    "align":       _ENV_ALIGNED,
    "align*":      _ENV_ALIGNED,
    "flalign":     _ENV_ALIGNED,
    "flalign*":    _ENV_ALIGNED,
    "eqnarray":    _ENV_ALIGNED,
    "eqnarray*":   _ENV_ALIGNED,
    "alignat":     _ENV_ALIGNED,
    "alignat*":    _ENV_ALIGNED,
    "gather":      _ENV_GATHERED,
    "gather*":     _ENV_GATHERED,
    "multline":    _ENV_GATHERED,
    "multline*":   _ENV_GATHERED,
}
ENV_NAMES_RE = "|".join(re.escape(name) for name in ENV_MAP)
ENV_SPAN_RE = re.compile(
    r"\\begin\{(" + ENV_NAMES_RE + r")\}(\{\d+\}[ \t]*\r?\n?)?(.*?)\\end\{\1\}",
    re.S,
)

# Блоки кода: fenced (``` / ~~~) и инлайн-коды. Внутри них формулы не ищем.
CODE_SPLIT_RE = re.compile(r"(```.*?```|~~~.*?~~~|`[^`\n]*`)", re.S)


@dataclass
class LatexReport:
    """Результат детекта формул: сколько строчных и сколько выносных."""

    inline: int = 0
    display: int = 0

    @property
    def total(self) -> int:
        return self.inline + self.display

    @property
    def has_latex(self) -> bool:
        return self.total > 0


def _non_code_text(md_text: str) -> str:
    """Текст без содержимого код-блоков и инлайн-кодов."""
    parts = CODE_SPLIT_RE.split(md_text)
    return "".join(p for i, p in enumerate(parts) if i % 2 == 0)


def detect_latex(md_text: str) -> LatexReport:
    """Посчитать формулы в markdown (игнорируя содержимое блоков кода)."""
    text = _non_code_text(md_text)

    display = len(DISPLAY_DOLLAR_RE.findall(text))
    display += len(BRACKET_RE.findall(text))
    display += len(ENV_SPAN_RE.findall(text))

    t = DISPLAY_DOLLAR_RE.sub(" ", text)
    t = BRACKET_RE.sub(" ", t)
    t = ENV_SPAN_RE.sub(" ", t)
    inline = len(INLINE_DOLLAR_RE.findall(t))
    inline += len(PAREN_RE.findall(t))

    return LatexReport(inline=inline, display=display)


# --------------------------------------------------------------------------
# 2. Нормализация математики перед pandoc
# --------------------------------------------------------------------------

def _strip_math_noise(body: str) -> str:
    """Убрать из формулы то, что не влияет на вид, но ломает OMML."""
    body = re.sub(r"\\label\{[^{}]*\}\s*", "", body)
    body = re.sub(r"\\(?:nonumber|notag)\b\s*", "", body)
    return body


def _env_repl(m: re.Match) -> str:
    env, body = m.group(1), m.group(3) or ""
    if env.startswith("eqnarray"):
        # eqnarray выравнивает по &=& ; для aligned нужен одиночный &=
        body = re.sub(r"&(?:=+)", "&=", body)
    body = _strip_math_noise(body)
    opener, closer = ENV_MAP[env]
    return opener + body.strip("\r\n") + closer


def normalize_math(md_text: str) -> str:
    r"""Привести всю математику к $..$ / $$..$$ (вне код-блоков).

    \begin{equation}..\end{equation}  -> $$..$$
    \begin{align}..                  -> $$\begin{aligned}..\end{aligned}$$
    \[..\]                            -> $$..$$
    \(..\)                            -> $..$
    """
    def conv(seg: str) -> str:
        seg = ENV_SPAN_RE.sub(_env_repl, seg)
        seg = BRACKET_RE.sub(lambda m: "$$" + m.group(1).strip("\r\n") + "$$", seg)
        seg = PAREN_RE.sub(lambda m: "$" + m.group(1).strip() + "$", seg)
        return seg

    parts = CODE_SPLIT_RE.split(md_text)
    return "".join(
        p if i % 2 == 1 else conv(p) for i, p in enumerate(parts)
    )


# --------------------------------------------------------------------------
# 3. Front matter и картинки
# --------------------------------------------------------------------------

_YAML_BLOCK_RE = re.compile(r"^(---[ \t]*\r?\n)(.*?)(\r?\n---[ \t]*(?:\r?\n|$))", re.S)
_YAML_LANG_RE = re.compile(r"(?m)^lang:[ \t]*\S.*\r?\n?")


def strip_frontmatter_lang(md_text: str) -> str:
    """Удалить ключ `lang:` из YAML front matter.

    Если pandoc увидит lang, он подключит polyglossia/babel, которых может
    не быть в минимальной установке TeX — кириллице они не нужны.
    """
    m = _YAML_BLOCK_RE.match(md_text)
    if not m:
        return md_text
    fm = _YAML_LANG_RE.sub("", m.group(2))
    return md_text[: m.start(2)] + fm + md_text[m.end(2) :]


_IMG_RE = re.compile(r"!\[([^\]]*)\]\(\s*(<[^>]*>|[^)\s]+(?:[ \t]+[^)\s]+)*?)\s*\)")


def sanitize_missing_images(
    md_text: str, workdir: Path, placeholder_tpl: str
) -> str:
    """Обработать ссылки на локальные картинки.

    * URL (http/https/data:) не трогаются;
    * существующий локальный файл заменяется на АБСОЛЮТНЫЙ путь —
      pandoc для PDF передаёт путь в xelatex как есть, и относительный
      путь может не найтись в зависимости от рабочего каталога;
    * несуществующий локальный путь заменяется плейсхолдером, чтобы
      конвертация всего документа не падала.
    """
    workdir = Path(workdir)

    def repl(m: re.Match) -> str:
        alt, target = m.group(1), m.group(2).strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1].strip()
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", target) or target.startswith("data:"):
            return m.group(0)
        local = (workdir / target)
        if not local.exists():
            return "*" + placeholder_tpl.format(path=target) + "*"
        absolute = str(local.resolve())
        if " " in absolute:
            absolute = f"<{absolute}>"
        return f"![{alt}]({absolute})"

    return _IMG_RE.sub(repl, md_text)


# --------------------------------------------------------------------------
# 4. Выбор движка и шрифтов
# --------------------------------------------------------------------------

FONT_SETS = [
    ("Liberation Serif", "Liberation Sans", "DejaVu Sans Mono"),
    ("DejaVu Serif", "DejaVu Sans", "DejaVu Sans Mono"),
    ("Noto Serif", "Noto Sans", "DejaVu Sans Mono"),
    ("Times New Roman", "Arial", "Courier New"),
]


def _fc_families() -> "set[str] | None":
    """Список семейств fontconfig (или None, если fc-list недоступен)."""
    if shutil.which("fc-list") is None:
        return None
    try:
        out = subprocess.run(
            ["fc-list", ":", "family"],
            capture_output=True,
            text=True,
            encoding="utf-8",     # fc-list пишет UTF-8, а не локаль Windows
            errors="replace",
            timeout=20,
        )
        fams: set[str] = set()
        for line in out.stdout.splitlines():
            for fam in line.split(","):
                fam = fam.strip()
                if fam:
                    fams.add(fam)
        return fams
    except Exception:
        return None


def pick_fonts(mainfont: "str | None" = None) -> "tuple[str, str, str] | None":
    """Подобрать (основной, без засечек, моно) шрифт с поддержкой кириллицы."""
    mainfont = (mainfont or os.getenv("PDF_MAINFONT", "")).strip() or None
    if mainfont:
        return (
            mainfont,
            os.getenv("PDF_SANSFONT", "").strip() or mainfont,
            os.getenv("PDF_MONOFONT", "").strip() or "DejaVu Sans Mono",
        )
    fams = _fc_families()
    if not fams:
        return None
    for s in FONT_SETS:
        if s[0] in fams:
            return s
    return None


def pick_pdf_engine(explicit: "str | None" = None) -> str:
    """Выбрать PDF-движок: xelatex (предпочтительно) или tectonic."""
    eng = (explicit or os.getenv("PDF_ENGINE", "")).strip()
    if eng:
        return eng
    if shutil.which("xelatex"):
        return "xelatex"
    if shutil.which("tectonic"):
        return "tectonic"
    raise ConverterError(
        "PDF engine not found: LaTeX is not installed.\n"
        "Fix (choose one):\n"
        "- Windows: install MiKTeX https://miktex.org/download "
        "(xelatex) or tectonic "
        "https://github.com/tectonic-typesetting/tectonic/releases - "
        "then RESTART the bot;\n"
        "- Linux: sudo apt install texlive-xetex;\n"
        "- macOS: brew install basictex;\n"
        "- or run the bot in Docker (everything is preinstalled)."
    )


# --------------------------------------------------------------------------
# 5. Запуск pandoc
# --------------------------------------------------------------------------

def _timeout_default() -> int:
    try:
        return int(os.getenv("CONVERT_TIMEOUT", "180"))
    except ValueError:
        return 180


def _run_pandoc(args: list, timeout: int) -> None:
    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise ConverterError(
            "pandoc not found in PATH. Install it: https://pandoc.org/installing.html"
        )
    try:
        proc = subprocess.run(
            [pandoc, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",     # pandoc/xelatex всегда пишут UTF-8; без этого
            errors="replace",     # на Windows с локалью cp1251 читающий поток
            timeout=timeout,      # падал с UnicodeDecodeError (и причина терялась)
        )
    except subprocess.TimeoutExpired:
        raise ConverterError(
            f"pandoc exceeded {timeout}s timeout - document is too big or complex."
        )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise ConverterError(err[-1200:] if err else "pandoc failed without details.")


def _check_output(dst: Path) -> Path:
    if not dst.exists() or dst.stat().st_size == 0:
        raise ConverterError("pandoc finished but produced no output file.")
    return dst


def md_to_docx(src: Path, dst: Path, timeout: "int | None" = None) -> Path:
    """Markdown -> DOCX (формулы превращаются в уравнения Word / OMML)."""
    src, dst = Path(src), Path(dst)
    timeout = timeout or _timeout_default()
    _run_pandoc(
        [
            str(src),
            "-f", "markdown+tex_math_dollars",
            "-t", "docx",
            "--resource-path", str(src.parent),
            "-o", str(dst),
        ],
        timeout,
    )
    return _check_output(dst)


def md_to_pdf(
    src: Path,
    dst: Path,
    *,
    engine: "str | None" = None,
    mainfont: "str | None" = None,
    fontsize: "str | None" = None,
    margin: "str | None" = None,
    timeout: "int | None" = None,
) -> tuple:
    """Markdown -> PDF через XeLaTeX (или tectonic).

    Возвращает (путь к pdf, имя использованного движка).
    """
    src, dst = Path(src), Path(dst)
    timeout = timeout or _timeout_default()
    eng = pick_pdf_engine(engine)
    fontsize = (fontsize or os.getenv("PDF_FONTSIZE", "")).strip() or "11pt"
    margin = (margin or os.getenv("PDF_MARGIN", "")).strip() or "2.2cm"

    args = [
        str(src),
        "-f", "markdown+tex_math_dollars",
        "-o", str(dst),
        "--pdf-engine", eng,
        "--resource-path", str(src.parent),
        "-V", f"fontsize={fontsize}",
        "-V", f"geometry:margin={margin}",
        "-V", "colorlinks=true",
        "-V", "urlcolor=blue",
    ]
    fonts = pick_fonts(mainfont)
    if fonts:
        args += [
            "-V", f"mainfont={fonts[0]}",
            "-V", f"sansfont={fonts[1]}",
            "-V", f"monofont={fonts[2]}",
        ]
    _run_pandoc(args, timeout)
    _check_output(dst)
    return dst, eng


# --------------------------------------------------------------------------
# 6. Утилиты
# --------------------------------------------------------------------------

def human_size(num_bytes: int) -> str:
    """0 -> '0 Б', 1536 -> '1.5 КБ' (единицы русские, но понятны всем)."""
    size = float(num_bytes or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return f"{int(size)} {unit}" if unit == "Б" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} ГБ"
