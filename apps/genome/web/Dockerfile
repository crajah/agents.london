FROM node:20-alpine AS builder
WORKDIR /app
ARG VITE_GENOME_API
COPY package.json ./
RUN npm install
COPY . .
RUN VITE_GENOME_API="$VITE_GENOME_API" npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
