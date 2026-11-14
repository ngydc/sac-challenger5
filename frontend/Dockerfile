# ---- deps: install node_modules once (shared by dev and build) ----
FROM node:24-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ---- dev: ng serve with live reload (source is bind-mounted by docker-compose) ----
FROM deps AS dev
COPY . .
EXPOSE 4200
# --poll is needed because file change events don't reach the container from a Windows bind mount
CMD ["npx", "ng", "serve", "--host", "0.0.0.0", "--port", "4200", "--poll", "1000"]

# ---- build: production bundle ----
FROM deps AS build
COPY . .
RUN npm run build

# ---- prod: static files served by nginx ----
FROM nginx:1.28-alpine AS prod
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/frontend/browser /usr/share/nginx/html
EXPOSE 80
