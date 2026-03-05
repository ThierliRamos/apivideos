FROM python:3.10-slim

# Instala ffmpeg e aria2c para downloads rápidos
RUN apt-get update && apt-get install -y ffmpeg aria2 && apt-get clean

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

# Expõe a porta que o FastAPI usa
EXPOSE 8000

# Comando para rodar a API
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]