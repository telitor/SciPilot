# syntax=docker/dockerfile:1.7
ARG NODE_IMAGE=node:20.20.2-bookworm-slim
ARG NGINX_IMAGE=nginx:1.28.3-alpine3.23

FROM ${NODE_IMAGE} AS build
WORKDIR /src

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

FROM ${NGINX_IMAGE}

COPY frontend/nginx.conf /etc/nginx/nginx.conf
COPY --from=build --chown=nginx:nginx /src/dist/ /usr/share/nginx/html/

# The custom configuration uses only /tmp for mutable nginx state, so the
# runtime can be non-root and the root filesystem can be read-only.
USER 101:101
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=5 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/healthz"]

ENTRYPOINT []
CMD ["nginx", "-g", "daemon off;"]
