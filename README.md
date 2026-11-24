# md-converter-bot

Telegram-бот, который превращает присланный **Markdown-файл** в **DOCX** или
**PDF**. LaTeX-формулы, если они есть в документе, конвертируются честно:
для PDF — рендер через **XeLaTeX**, для DOCX — **редактируемые уравнения
Word** (OMML). Исходное имя файла сохраняется: `report.md` → `report.pdf` /
`report.docx`.

## Возможности

- Формат выбирается inline-кнопками **DOCX** и **PDF** сразу после отправки файла;
- автоматическое определение LaTeX-формул с отчётом:
  «Обнаружены LaTeX-формулы: 13 (строчных: 10, выносных: 3)»;
- формулы: `$...$`, `$$...$$`, `\(..\)`, `\[%..%]`, окружения
  `equation`, `align`, `alignat`, `gather`, `multline`, `eqnarray`
  (и звёздные варианты);
- таблицы, картинки (по URL или рядом с файлом), код-блоки, ссылки, списки;
- два языка интерфейса — русский (по умолчанию) и English, переключение `/language`;
- один и тот же файл можно сконвертировать в оба формата с одних кнопок;
- временные файлы удаляются автоматически через час.

## Быстрый старт (Docker, рекомендую)

1. Получите токен у [@BotFather](https://t.me/BotFather): `/newbot` →
   скопируйте токен вида `1234567890:AA...`.
2. Соберите и запустите:

```bash
cp .env.example .env
nano .env                 # вставьте токен в TELEGRAM_BOT_TOKEN
docker compose up -d --build
```

3. Отправьте боту любой `.md` файл (для пробы есть `samples/demo_ru.md`).

Образ содержит pandoc, XeLaTeX (texlive), шрифты с кириллицей —
ничего доустанавливать не нужно. Сборка образа занимает несколько минут
(texlive весит ~1 ГБ).

## Запуск без Docker

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install -y pandoc texlive-xetex texlive-latex-base \
     texlive-latex-recommended texlive-latex-extra \
     texlive-fonts-recommended lmodern fonts-liberation fontconfig

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # вставьте токен
python bot.py
```

### macOS

```bash
brew install pandoc basictex        # basictex можно заменить на mactex-no-gui
sudo tlmgr install unicode-math lm collection-latexextra
# укажите в .env PDF_MAINFONT, например: PDF_MAINFONT=Times New Roman
pip install -r requirements.txt && python bot.py
```

### Windows

1. Установите [pandoc](https://github.com/jgm/pandoc/releases)
   (`winget install JohnMacFarlane.Pandoc` или инсталлятор с сайта).
2. Установите LaTeX-движок — любой из вариантов:
   - **MiKTeX** (https://miktex.org/download): при установке выберите
     «Install missing packages on-the-fly: Yes» — в PATH появится `xelatex`;
   - **tectonic** (проще всего): скачайте zip со страницы
     https://github.com/tectonic-typesetting/tectonic/releases,
     распакуйте `tectonic.exe` в папку из PATH (или
     `scoop install tectonic` / `choco install tectonic`).
     Пакеты докачиваются сами при первой конвертации.
3. `pip install -r requirements.txt`, создайте `.env`, вставьте токен.
   Для красивого шрифта с кириллицей добавьте в `.env`:
   `PDF_MAINFONT=Times New Roman`.
4. Запустите `python bot.py` **заново** — чтобы новый движок появился в PATH,
   процесс бота нужно перезапустить.

Первая конвертация PDF скачивает пакеты LaTeX и может занять пару минут —
при медленном интернете задайте в `.env` `CONVERT_TIMEOUT=600`.

## Команды бота

| Команда    | Действие                                        |
|------------|-------------------------------------------------|
| `/start`   | приветствие и краткая инструкция                |
| `/help`    | то же самое                                     |
| `/language`| выбор языка интерфейса (Русский / English)      |

## Как это работает

Конвейер конвертации (`converter.py`):

1. **Детект LaTeX** — считается число строчных и выносных формул
   (содержимое код-блоков игнорируется, «цена $5, а доставка $10»
   формулой не считается).
2. **Подготовка** — удаляется `lang:` из YAML front matter (чтобы pandoc
   не требовал polyglossia), несуществующие локальные картинки заменяются
   плейсхолдером, все формы записи формул приводятся к `$..$` / `$$..$$`,
   из формул убираются `\label{}`, `\nonumber`, `\notag`.
3. **pandoc**:
   - DOCX: `pandoc -t docx` — формулы становятся уравнениями Word (OMML),
     их можно редактировать прямо в Word/LibreOffice;
   - PDF: `pandoc --pdf-engine=xelatex` (если xelatex нет — автоматически
     используется tectonic). Шрифт с кириллицей подбирается автоматически:
     Liberation Serif → DejaVu Serif → Noto Serif; можно задать свой через
     `PDF_MAINFONT`.

## Картинки

- `![alt](https://example.com/img.png)` — скачивает pandoc; контейнеру
  нужен доступ в интернет (у Docker он есть по умолчанию).
- `![alt](plot.png)` — локальный файл: бот получает от Telegram только сам
  `.md`, без картинок из соседних папок, поэтому **локальные относительные
  пути работать не будут**: такие ссылки заменяются плейсхолдером
  «изображение недоступно», и конвертация не падает.
  Используйте абсолютные URL (например, ссылку на картинку из репозитория
  raw.githubusercontent.com).
- Если картинка недоступна, остальной документ всё равно конвертируется.

## Ограничения

- Вход: до 20 МБ (ограничение Bot API на скачивание файлов).
- Выход: до 50 МБ (ограничение на отправку документов ботом).
- Кнопки действуют 1 час; после перезапуска бота старые кнопки становятся
  недействительными (просто пришлите файл заново).
- Сложный LaTeX (tikz, пользовательские макросы `\newcommand`) не
  поддерживается pandoc-математикой — в PDF это прошло бы как raw-вставка,
  в DOCX будет потеряно.
- Код-блоки в PDF подсвечиваются стандартным списком pandoc (`.py`→Python и т.п.).

## Структура проекта

```
md-converter-bot/
├── bot.py            # Telegram-бот (aiogram 3): команды, кнопки, очередь задач
├── converter.py      # детект LaTeX, нормализация, pandoc → DOCX/PDF
├── i18n.py           # тексты интерфейса RU/EN
├── requirements.txt  # aiogram, python-dotenv
├── Dockerfile        # образ с pandoc + texlive-xetex + шрифтами
├── docker-compose.yml
├── .env.example      # шаблон конфигурации (скопировать в .env)
├── .gitignore
└── samples/
    ├── demo_ru.md    # образец с формулами, таблицей и картинкой
    ├── demo_en.md    # короткий образец на английском
    └── plot.png      # картинка для demo_ru.md
```

## Устранение неполадок

| Проблема | Решение |
|----------|---------|
| `TELEGRAM_BOT_TOKEN не задан` при старте | заполните `.env` (или экспортируйте переменную) |
| `PDF engine not found: LaTeX is not installed` | не установлен LaTeX: на Windows — MiKTeX или tectonic, на Linux — `sudo apt install texlive-xetex`. После установки перезапустите бота |
| Первая конвертация PDF идёт долго | движок скачивает пакеты LaTeX — это нормально; при таймауте увеличьте `CONVERT_TIMEOUT` |
| `query is too old` в логах | нажали очень старую кнопку — пришлите файл заново (на работу бота не влияет) |
| `pandoc not found in PATH` | установите pandoc (в Docker-образе он уже есть) |
| `PDF engine not found` | поставьте `texlive-xetex` (или tectonic, см. `PDF_ENGINE`) |
| `File 'unicode-math.sty' not found` | поставьте `texlive-latex-extra` (или в MiKTeX включите автоустановку пакетов) |
| Русские буквы в PDF квадратиками | задайте `PDF_MAINFONT` со шрифтом, у которого есть кириллица |
| Бот молчит после запуска | проверьте токен; 409 Conflict = запущен второй экземпляр или висит webhook |
| `pandoc exceeded ... timeout` | увеличьте `CONVERT_TIMEOUT` или разбейте документ |

Конфиденциальность: файлы сохраняются только в локальную папку
`data/tmp/jobs` и удаляются через час; выбор языка — единственное, что
хранится постоянно (`data/langs.json`).
