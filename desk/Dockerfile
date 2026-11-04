FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DESK_HOST=0.0.0.0 DESK_PORT=8004
WORKDIR /app
COPY requirements-bridge.txt requirements-desk.txt ./
RUN python -m pip install --no-cache-dir -r requirements-desk.txt
COPY bridge/ ./bridge/
COPY scripts/ ./scripts/
COPY desk/ ./desk/
RUN mkdir /data && useradd -r -u 10001 -m desk && chown -R desk:desk /data /app
USER desk
EXPOSE 8004
CMD ["python","-m","desk.app"]
