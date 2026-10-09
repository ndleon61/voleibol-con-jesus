FROM python:3.12-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/usr/lib/postgresql/18/bin:$PATH" SSL_CERT_FILE="/etc/ssl/certs/ca-certificates.crt" HOME="/home/voli"
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl --fail --silent --show-error --location https://www.postgresql.org/media/keys/ACCC4CF8.asc \
       --output /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && printf '%s\n' 'Types: deb' 'URIs: https://apt.postgresql.org/pub/repos/apt' \
       'Suites: trixie-pgdg' 'Components: main' \
       'Signed-By: /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc' \
       > /etc/apt/sources.list.d/pgdg.sources \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-18 \
    && /usr/lib/postgresql/18/bin/pg_dump --version \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 voli && useradd --uid 10001 --gid voli --home-dir /home/voli --no-create-home voli \
    && install -d -m 700 -o 10001 -g 10001 /home/voli
COPY server-flask/requirements-production.txt /app/server-flask/requirements-production.txt
RUN pip install --no-cache-dir -r server-flask/requirements-production.txt
COPY server-flask/*.py /app/server-flask/
COPY server-flask/migrations /app/server-flask/migrations
COPY *.html *.css *.js /app/
COPY media /app/media
COPY licenses /app/licenses
COPY scripts/container_start.py /app/scripts/container_start.py
ENTRYPOINT ["python", "/app/scripts/container_start.py"]
CMD ["gunicorn", "--chdir", "/app/server-flask", "--config", "/app/server-flask/gunicorn.conf.py", "app:app"]
