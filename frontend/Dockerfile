# Frontend image: build the SPA, then serve the static build behind nginx.
#
# The SPA always calls the API through a relative path (/api/v1/...), so the
# build needs no API URL and therefore no build argument.

# ---- stage 1: build --------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /app

# Corepack downloads the pnpm version pinned by package.json, without prompting.
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable

# Dependencies first, so the layer is cached until the lockfile changes.
# Build tooling lives in devDependencies, so nothing may be pruned here.
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build

# ---- stage 2: serve --------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
