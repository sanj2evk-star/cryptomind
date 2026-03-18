###############################################################################
# Frontend Dockerfile — React app served by nginx
#
# Multi-stage build:
#   Stage 1: Build the React app with Vite
#   Stage 2: Serve static files with nginx
#
# Usage:
#   docker build -t btc-trader-ui frontend/
#   docker run -p 3000:80 btc-trader-ui
###############################################################################

# ---------------------------------------------------------------------------
# Stage 1: Build
# ---------------------------------------------------------------------------
FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

# Build arg for API URL (set at build time)
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: Serve
# ---------------------------------------------------------------------------
FROM nginx:alpine AS runtime

# Copy built files
COPY --from=build /app/dist /usr/share/nginx/html

# Custom nginx config for SPA routing + API proxy
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
