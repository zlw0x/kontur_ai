# The decoder, in a container that owns nothing.
#
# `docs/SECURE-INPUT-ADDENDUM.md` §2.2 asks for this and it had not been built: the
# argv was assembled and asserted by a test, and what actually ran was the process
# mode — a child with `RLIMIT_AS`, `RLIMIT_CPU` and a wall clock, sharing the
# API's kernel namespace.
#
# What this adds over that is the namespace. A decoder is the largest attack
# surface in the service and it is fed bytes a stranger chose; the process mode
# bounds how much it can *spend*, and only a container bounds what it can *see*.
#
# Deliberately not the API's image. That one has the database URL in its
# environment and SQLAlchemy on its path, and the whole point of the package is
# that neither is reachable from the thing doing the decoding.
FROM python:3.13-slim-bookworm

# Pillow and nothing else. The API must not have it, and this must not have
# anything the API has -- `requirements.txt` says so in one line and this is the
# only place it is installed.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Read-only at runtime (`--read-only`), so nothing here is written to. The code
# goes in as root-owned and is executed by nobody.
COPY image_sanitizer /app/image_sanitizer
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 65534:65534 — `nobody`, which is the user `Sanitizer._command` passes on the
# command line. Named in both places rather than defaulted, because a container
# that silently ran as root would look identical from outside.
USER 65534:65534

# One file in, one file out, and the limits on the command line. No shell form:
# the argv is fixed and asserted by `test_the_container_mode_drops_everything_it_can`,
# and a shell between here and the decoder is a place for a filename to be a
# command.
ENTRYPOINT ["python", "-m", "image_sanitizer"]
