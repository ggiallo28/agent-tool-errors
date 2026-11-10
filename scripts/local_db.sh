#!/usr/bin/env bash
# Start or remove the local PostgreSQL container used by the tests and the experiments.
#   scripts/local_db.sh up     recreate the container; prints only the export line on success
#   scripts/local_db.sh down   remove the container
# Use: eval "$(scripts/local_db.sh up)"
set -u

NAME=opsmem-pg
PORT=55432
READY_LINE="PostgreSQL init process complete; ready for start up."
TIMEOUT="${OPSMEM_READY_TIMEOUT:-60}"

usage() {
  echo "usage: $0 up|down" >&2
  exit 2
}

pg_ready() {
  if command -v pg_isready >/dev/null 2>&1; then
    pg_isready -q -h localhost -p "$PORT"
  else
    docker exec "$NAME" pg_isready -q -h localhost -p 5432
  fi
}

up() {
  docker rm -f "$NAME" >/dev/null 2>&1
  local started
  if ! started=$(docker run -d --name "$NAME" -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=opsmemory \
      -p "$PORT:5432" postgres:16 2>&1); then
    echo "cannot start the container $NAME: $started" >&2
    docker rm -f "$NAME" >/dev/null 2>&1
    exit 1
  fi
  local begin=$SECONDS phase=log
  while (( SECONDS - begin < TIMEOUT )); do
    if [ "$phase" = log ]; then
      if docker logs "$NAME" 2>&1 | grep -qF "$READY_LINE"; then phase=tcp; continue; fi
    elif pg_ready; then
      echo "export OPSMEM_LOCAL_PG=localhost:$PORT"
      exit 0
    fi
    sleep 1
  done
  echo "readiness timeout: $NAME is not ready after ${TIMEOUT}s; the container is left in place, see: docker logs $NAME" >&2
  exit 1
}

[ "$#" -eq 1 ] || usage
case "$1" in
  up) up ;;
  down) docker rm -f "$NAME" >/dev/null 2>&1; exit 0 ;;
  *) usage ;;
esac
