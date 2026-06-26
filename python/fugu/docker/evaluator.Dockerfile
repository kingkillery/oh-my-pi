FROM python:3.12-slim
WORKDIR /app
COPY . /app
RUN pip install -e .[dev]
CMD ["fmh", "run-eval", "--suite", "evals/search/tasks.jsonl", "--limit", "1"]
