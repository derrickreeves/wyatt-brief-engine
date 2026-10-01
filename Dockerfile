FROM python:3.12-slim
RUN pip install --no-cache-dir reportlab==4.2.5 pypdf==5.1.0
WORKDIR /app
COPY renderer/ /app/renderer/
COPY service/ /app/service/
ENV RENDERER_DIR=/app/renderer PORT=8080
EXPOSE 8080
CMD ["python", "/app/service/server.py"]
