FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn pydantic
COPY backend/apps/agents/jira_agent /app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
