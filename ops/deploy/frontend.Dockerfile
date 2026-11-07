# The Studio's static site. Vite writes the VITE_ settings into the files at build time, so a change
# to any of them means a new image.
FROM node:22.21.1-alpine3.22@sha256:b2358485e3e33bc3a33114d2b1bdb18cdbe4df01bd2b257198eb51beb1f026c5 AS build

ARG VITE_FLINT_GRAPH_AUTH_MODE=oidc
ARG VITE_FLINT_GRAPH_OIDC_AUTHORITY
ARG VITE_FLINT_GRAPH_OIDC_CLIENT_ID
ARG VITE_FLINT_GRAPH_OIDC_BEARER
ARG VITE_FLINT_GRAPH_OIDC_LOGOUT_URL
ARG VITE_FLINT_GRAPH_PREVIEW_ORIGIN

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:1.29.3-alpine@sha256:b3c656d55d7ad751196f21b7fd2e8d4da9cb430e32f646adcf92441b72f82b14

COPY ops/deploy/frontend.nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
