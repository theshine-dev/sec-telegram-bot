# Dockerfile

# 1. 베이스 이미지: 파이썬 3.12 슬림 버전이 설치된 리눅스에서 시작
FROM python:3.13-slim

# 2. 작업 디렉토리: 컨테이너 안의 /app 이라는 폴더에서 작업
WORKDIR /app

# 3. (중요) 의존성 설치 (캐시 활용을 위해 코드 복사보다 먼저 수행)
# 부품 목록(requirements.txt)만 먼저 복사
COPY requirements.txt .
# 부품 목록을 보고 모든 라이브러리 설치
RUN pip install --no-cache-dir -r requirements.txt

# 4. 코드 복사: 현재 폴더(.)의 모든 코드(.py, config.py 등)를
# 컨테이너 안의 /app 폴더로 복사
COPY . .

# 5. 실행 명령어: 이 컨테이너가 시작될 때 "python main.py"를 실행
CMD ["python", "main.py"]