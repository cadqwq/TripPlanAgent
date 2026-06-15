# ============================================================
# TripPlanAgent 前端 Dockerfile
# ============================================================
FROM node:20-slim

# 设置工作目录
WORKDIR /app

# 先复制依赖文件（利用 Docker 层缓存）
COPY package.json package-lock.json ./

# 安装依赖
RUN npm install

# 复制源代码
COPY . .

# 暴露端口
EXPOSE 5173

# 启动 Vite 开发服务器（--host 让外部可以访问）
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
