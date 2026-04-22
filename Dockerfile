FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY setup.py .
COPY showshow/ ./showshow/
RUN pip install -e . --no-cache-dir

# 配置目录
RUN mkdir -p /root/.showshow
COPY config.yaml.example /root/.showshow/config.yaml

ENTRYPOINT ["showshow"]
CMD ["--help"]
