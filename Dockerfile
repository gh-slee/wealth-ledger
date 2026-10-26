FROM node:24-bookworm-slim@sha256:a5f4366e834695d5f363b920c104953a535d3a9864d1bdf74566a0ebe01daee5 AS browser-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/tsconfig.json frontend/vite.config.ts frontend/index.html ./
COPY frontend/src ./src
COPY frontend/public ./public
RUN npm run build

FROM python:3.12.15-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src \
    WEALTH_LEDGER_DATA_ROOT=/data MPLCONFIGDIR=/data/cache/matplotlib \
    XDG_CACHE_HOME=/data/cache/system
WORKDIR /app
COPY requirements.lock requirements-web.lock requirements-pg.lock /app/
ARG WEALTH_LEDGER_POSTGRES=0
RUN python -m pip install --no-cache-dir -r requirements-web.lock \
    && case "$WEALTH_LEDGER_POSTGRES" in 0) ;; 1) python -m pip install --no-cache-dir -r requirements-pg.lock ;; *) exit 2 ;; esac \
    && groupadd --gid 10001 ledger \
    && useradd --uid 10001 --gid ledger --no-create-home --home-dir /nonexistent ledger \
    && mkdir /data && chown 10001:10001 /data && chmod 0700 /data
COPY src/wealth_ledger /app/src/wealth_ledger
COPY scripts/web.py /app/scripts/web.py
COPY config/company-aliases.json /app/config/company-aliases.json
COPY assets/fonts /app/assets/fonts
COPY LICENSE THIRD_PARTY_NOTICES.md /app/
COPY --from=browser-build /build/dist /app/frontend/dist
RUN find /app -type d -exec chmod 0555 {} + \
    && find /app -type f -exec chmod 0444 {} +
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["python", "/app/scripts/web.py"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
