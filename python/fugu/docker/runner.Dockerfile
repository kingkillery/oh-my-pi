FROM python:3.12-slim
WORKDIR /app
COPY . /app
RUN pip install -e .[dev]
CMD ["fmh", "--help"]
