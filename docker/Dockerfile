# EDA Agent 网站版容器镜像
FROM python:3.12-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝源码
COPY backend ./backend
COPY frontend ./frontend
COPY run.py .

# 暴露端口
EXPOSE 8000

# 输出目录挂载点
VOLUME ["/app/output"]

# 启动（监听 0.0.0.0 供容器外部访问）
CMD ["python", "run.py", "--host", "0.0.0.0", "--port", "8000"]
