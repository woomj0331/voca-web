# 2026-11-25 - voca-web - 학교 서버 배포용 이미지 (R-01~R-10, 규칙 근거는 docs/ 의 설계서 참고)
# 파일 위치: Dockerfile
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/voca.db

# UID 10001 사용자를 만들고, SQLite 가 쓸 /data 의 소유자를 10001 로 한다 (R-05, R-06)
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser \
    && mkdir /data \
    && chown 10001:10001 /data

WORKDIR /app

# 의존성 파일을 먼저 복사해 설치한다 — 소스만 바뀌면 이 층은 캐시를 쓴다 (R-13)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py db.py store.py exam.py study_plan.py ./
COPY templates ./templates
COPY static ./static

USER 10001
EXPOSE 8080

# 운영용 서버, 0.0.0.0:8080, exec 형식 (R-03, R-14, R-15)
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "app:app"]
