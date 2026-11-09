FROM postgres:17-alpine
COPY infra/init.sql /docker-entrypoint-initdb.d/01-litellm.sql
