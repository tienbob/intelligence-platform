# ---- Build Stage ----
FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .

# Auto-refresh intervals (milliseconds). Set to 0 to disable.
ARG VITE_REFRESH_DASHBOARD_MS=30000
ARG VITE_REFRESH_ANALYSIS_JOBS_MS=5000
ARG VITE_REFRESH_ANALYSIS_DETAIL_MS=5000
# Public origin of the app (scheme + host[:port]) — exposed as APP_URL from
# src/config.js. Sourced from the root APP_URL by docker-compose.
ARG VITE_APP_URL=http://localhost:3000
ENV VITE_REFRESH_DASHBOARD_MS=$VITE_REFRESH_DASHBOARD_MS
ENV VITE_REFRESH_ANALYSIS_JOBS_MS=$VITE_REFRESH_ANALYSIS_JOBS_MS
ENV VITE_REFRESH_ANALYSIS_DETAIL_MS=$VITE_REFRESH_ANALYSIS_DETAIL_MS
ENV VITE_APP_URL=$VITE_APP_URL

RUN npm run build

# ---- Serve Stage ----
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
# server_name comes from APP_DOMAIN via the image entrypoint's envsubst run
# over /etc/nginx/templates/*.template. The filter pins substitution to
# APP_DOMAIN so nginx's own $host/$uri variables are never rewritten.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
ENV NGINX_ENVSUBST_FILTER=^APP_DOMAIN$
ENV APP_DOMAIN=localhost:3000
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]