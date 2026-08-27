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
ENV VITE_REFRESH_DASHBOARD_MS=$VITE_REFRESH_DASHBOARD_MS
ENV VITE_REFRESH_ANALYSIS_JOBS_MS=$VITE_REFRESH_ANALYSIS_JOBS_MS
ENV VITE_REFRESH_ANALYSIS_DETAIL_MS=$VITE_REFRESH_ANALYSIS_DETAIL_MS

RUN npm run build

# ---- Serve Stage ----
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]