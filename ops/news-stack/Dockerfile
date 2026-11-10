FROM node:22-bookworm-slim AS codex-cli
RUN npm install -g @openai/codex@0.167.0

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=codex-cli /usr/local/bin/node /usr/local/bin/node
COPY --from=codex-cli /usr/local/lib/node_modules/@openai /usr/local/lib/node_modules/@openai
RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex

COPY news_collector/requirements.txt /tmp/news-requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/news-requirements.txt \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin newsbot

COPY --chown=newsbot:newsbot schema/stock-signals.schema.json /app/schema/stock-signals.schema.json
COPY --chown=newsbot:newsbot news_collector/ /app/news_collector/
COPY --chown=newsbot:newsbot ops/news-stack/start-news-worker.sh /app/start-news-worker.sh
RUN chmod 0555 /app/start-news-worker.sh \
    && mkdir -p /app/news_collector/data /app/news_collector/chatgpt_inbox \
    && chown -R newsbot:newsbot /app/news_collector \
    && install -d -m 700 -o newsbot -g newsbot /home/newsbot/.news-codex /app/cli-inbox

USER newsbot
ENTRYPOINT ["/app/start-news-worker.sh"]
CMD ["--archive", "--once"]
