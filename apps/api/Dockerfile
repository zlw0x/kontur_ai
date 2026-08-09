FROM python:3.13-slim
RUN groupadd --system cad && useradd --system --gid cad --home-dir /app cad
WORKDIR /app
COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=cad:cad apps/api/app ./app
COPY --chown=cad:cad packages/cad-ir/cad_ir ./cad_ir
COPY --chown=cad:cad schemas/cad-ir.schema.json /schemas/cad-ir.schema.json

# The decoder, and the only place Pillow is allowed to be.
#
# It was not here at all, and the secure-input path therefore could not work in this
# image: `python -m image_sanitizer` had nothing to import, so every upload came back
# 503 in a deployment and green in every test, because the tests run from a
# repository checkout where the package is a sibling directory.
#
# `pillow` is installed for the *sanitizer's* sake and the API still must not import
# it. That is not a wish — the decoder runs in a child process with an environment
# this side builds, and the whole package exists so that a decoder failure is a dead
# child rather than a dead API. A container of its own is stronger and is what
# `SANITIZER_IMAGE` selects; this is the fallback that has to work.
COPY --chown=cad:cad packages/image-sanitizer/image_sanitizer ./image_sanitizer
COPY packages/image-sanitizer/requirements.txt ./sanitizer-requirements.txt
RUN pip install --no-cache-dir -r sanitizer-requirements.txt
# Both, and `/data` itself.
#
# `/data/artifacts` was created and chowned; `/data` was not, and the secure-input
# work put quarantine beside it as `/data/quarantine`. So the API could not create
# its own quarantine directory and **crashed on import** — the container never
# served a request. Nothing in the suite could see it: the tests point quarantine
# at a `tmp_path`, and the Dockerfile is not something they run.
#
# Quarantine is deliberately *not* a mounted volume. It holds a stranger's raw
# upload for the length of one request, and the addendum's central invariant is
# that the raw upload never reaches the directory the worker downloads from — so
# the two must not share a volume, and this one is thrown away with the container.
RUN mkdir -p /data/artifacts /data/quarantine && chown -R cad:cad /data
USER cad
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
