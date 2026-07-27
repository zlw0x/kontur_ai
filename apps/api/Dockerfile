FROM python:3.13-slim
RUN groupadd --system cad && useradd --system --gid cad --home-dir /app cad
WORKDIR /app
COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=cad:cad apps/api/app ./app
COPY --chown=cad:cad packages/cad-ir/cad_ir ./cad_ir
COPY --chown=cad:cad schemas/cad-ir.schema.json /schemas/cad-ir.schema.json
RUN mkdir -p /data/artifacts && chown cad:cad /data/artifacts
USER cad
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
