# Stage 1: Build React App with Material-UI & Vite
FROM node:18-alpine AS builder

WORKDIR /app

# VITE_ vars are passed as build args from CI/CD (GitHub Actions secrets)
ARG VITE_GOOGLE_CLIENT_ID
ARG VITE_MS_CLIENT_ID

COPY package.json ./
RUN npm install

COPY . .
RUN VITE_GOOGLE_CLIENT_ID="$VITE_GOOGLE_CLIENT_ID" \
    VITE_MS_CLIENT_ID="$VITE_MS_CLIENT_ID" \
    npm run build

# Stage 2: Serve compiled static bundle with Nginx
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
