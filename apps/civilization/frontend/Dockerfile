# Stage 1: Build React App with Material-UI & Vite
FROM node:18-alpine AS builder

WORKDIR /app

# VITE_ vars are passed as build args from CI/CD (GitHub Actions secrets)
ARG VITE_GOOGLE_CLIENT_ID
ARG VITE_MS_CLIENT_ID

COPY package.json ./
RUN npm install

COPY . .
# built for the /civilization/ subpath (GCE ingress never rewrites)
RUN VITE_GOOGLE_CLIENT_ID="$VITE_GOOGLE_CLIENT_ID" \
    VITE_MS_CLIENT_ID="$VITE_MS_CLIENT_ID" \
    npm run build -- --base=/civilization/

# Stage 2: Serve compiled static bundle with Nginx
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html/civilization
RUN printf 'server {\n  listen 80;\n  root /usr/share/nginx/html;\n  location = / { return 302 /civilization/; }\n  location /civilization/ { try_files $uri $uri/ /civilization/index.html; }\n}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
