FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY news_collector/requirements.txt /tmp/news-requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/news-requirements.txt \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin newsbot

COPY --chown=newsbot:newsbot news_collector/ /app/news_collector/
COPY --chown=newsbot:newsbot ops/news-stack/start-news-worker.sh /app/start-news-worker.sh
RUN chmod 0555 /app/start-news-worker.sh \
    && mkdir -p /app/news_collector/data /app/news_collector/chatgpt_inbox \
    && chown -R newsbot:newsbot /app/news_collector

USER newsbot
CMD ["/app/start-news-worker.sh"]
