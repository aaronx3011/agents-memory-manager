FROM pgvector/pgvector:pg17@sha256:ac08538c6f8b9904c33c8224c5e5706dbe760aca29db1d096972b4052c22a75d
COPY docker/initdb.sh /docker-entrypoint-initdb.d/010-memory.sh
RUN chmod 0644 /docker-entrypoint-initdb.d/010-memory.sh
