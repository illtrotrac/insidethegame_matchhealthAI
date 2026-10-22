FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[azure]"
ENV MATCHHEALTH_MOCK_LLM=0
CMD ["python", "-m", "matchhealth.run", "--speed", "1"]
