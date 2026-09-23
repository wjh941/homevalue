FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 代码 + 预训练产物(models/)+ 预计算分析缓存(reports/),克隆即可部署
COPY homevalue ./homevalue
COPY api ./api
COPY sql ./sql
COPY models ./models
COPY reports ./reports

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
