FROM node:20-alpine AS builder
WORKDIR /app
ARG VITE_GENOME_API=/genome-api
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN VITE_GENOME_API="$VITE_GENOME_API" VITE_BASE=/genome/ npm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY landing/index.html /usr/share/nginx/html/index.html
COPY --from=builder /app/dist /usr/share/nginx/html/genome
EXPOSE 80
