# Telegram-бот: Markdown -> DOCX / PDF (pandoc + XeLaTeX)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# pandoc + XeLaTeX со всем необходимым для формул и кириллицы:
#  - texlive-latex-extra: unicode-math, вёрстка
#  - lmodern: шрифты Latin Modern (в т.ч. математический OTF)
#  - fonts-liberation / fonts-dejavu-core: системные шрифты с кириллицей
#    (converter.py автоматически выбирает Liberation Serif -> DejaVu Serif)
RUN apt-get update && apt-get install -y --no-install-recommends \
        pandoc \
        texlive-xetex \
        texlive-latex-base \
        texlive-latex-recommended \
        texlive-latex-extra \
        texlive-fonts-recommended \
        texlive-plain-generic \
        lmodern \
        fonts-liberation \
        fonts-dejavu-core \
        fontconfig \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DATA_DIR=/app/data
VOLUME ["/app/data"]

CMD ["python", "bot.py"]
