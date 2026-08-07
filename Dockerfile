FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY core ./core
COPY addons ./addons
COPY main.py cli.py ./

RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
