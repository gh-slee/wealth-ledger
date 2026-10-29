ARG SOURCE_BASE
FROM ${SOURCE_BASE}
COPY --chown=0:0 worker.py fake_api.py /opt/source-test/
USER 10001:10001
ENTRYPOINT ["/usr/bin/env", "-i", "PATH=/usr/local/bin:/usr/bin:/bin", "PYTHONPATH=/app/src", "PYTHONDONTWRITEBYTECODE=1", "PYTHONUNBUFFERED=1", "LANG=C.UTF-8", "LC_ALL=C.UTF-8", "TZ=UTC", "HOME=/nonexistent", "/usr/local/bin/python", "/opt/source-test/worker.py"]
CMD []
