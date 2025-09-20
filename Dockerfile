FROM python:3.12-slim

WORKDIR /app

# 复制项目文件到容器
COPY requirements.txt ./
COPY app ./app

# 安装项目依赖
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# 暴露端口
EXPOSE 8501

# 设置容器启动命令
CMD ["streamlit", "run", "app/app.py", "--server.port=8501", "--server.address=0.0.0.0"]