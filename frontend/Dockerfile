# EvalShield 前端镜像：Node 构建 Vite 产物 → nginx 托管 + /api 反代
# 阶段 1：构建
FROM node:22-alpine AS builder

WORKDIR /build
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY . .
RUN npm run build

# 阶段 2：运行
FROM nginx:1.27-alpine

COPY --from=builder /build/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]