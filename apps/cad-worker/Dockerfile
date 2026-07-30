# The CAD worker: build123d on OpenCascade, in a Linux container (ADR-023).
#
# Pinned Python, pinned engine. A build that produced a different part after an
# unattended upgrade would be indistinguishable from a build that produced a
# different part because the document changed, and only one of those is a bug in
# the document.
FROM python:3.12-slim-bookworm AS base

# OpenCascade needs a handful of X and GL shared objects even for a headless
# build: the wheels link against them whether or not anything is drawn. Listed
# explicitly rather than pulled in by a meta-package so an image that grows knows
# why it grew.
RUN apt-get update && apt-get install --no-install-recommends -y \
      libgl1 \
      libglu1-mesa \
      libxi6 \
      libxmu6 \
      libsm6 \
      libice6 \
      libx11-6 \
      libexpat1 \
      libfontconfig1 \
      fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY apps/cad-worker/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# The contract and the engine, as source. Two packages rather than one because
# the contract is shared with the API and the engine is not.
COPY packages/cad-ir ./packages/cad-ir
COPY packages/build123d-adapter ./packages/build123d-adapter
COPY apps/cad-worker/cad_worker ./cad_worker
ENV PYTHONPATH=/app:/app/packages/cad-ir:/app/packages/build123d-adapter
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# A read-only root means nothing may write to a home directory. One of the
# engine's transitive dependencies wants a cache there and warns on every run
# when it cannot have one; pointing it at the tmpfs keeps the warning out of the
# output without giving the process anywhere durable to write.
ENV XDG_CACHE_HOME=/tmp/cache

# Not root, and not able to write anywhere but the job directory it is given.
# The container is expected to run with `--read-only`, `--network none` and a
# writable mount at /work; the entrypoint does not assume it, so a
# misconfiguration fails on the first write rather than silently running
# privileged.
RUN useradd --create-home --uid 10001 cad
USER cad

ENTRYPOINT ["python", "-m", "cad_worker"]
CMD ["describe"]
