FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[azure]"
ENV MATCHHEALTH_MOCK_LLM=0
# Unbuffered stdout: without this, print() output sits in an 8KB buffer and
# never reaches container logs until it fills or the process exits -- fatal
# for a 90-minute real-time job someone is trying to watch live.
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "matchhealth.run", "--speed", "1"]
