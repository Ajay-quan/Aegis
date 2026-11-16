# syntax=docker/dockerfile:1.7
# SPDX-License-Identifier: FSL-1.1-ALv2
# Dashboard image. Build context: the AegisTrace directory (the dashboard
# depends on the local TypeScript SDK in packages/sdk-typescript).
FROM node:22.20.0-bookworm-slim AS build
WORKDIR /src
COPY packages/sdk-typescript packages/sdk-typescript
RUN cd packages/sdk-typescript && npm ci && npm run build
COPY apps/dashboard/package.json apps/dashboard/package-lock.json apps/dashboard/
RUN cd apps/dashboard && npm ci
COPY apps/dashboard apps/dashboard
RUN cd apps/dashboard && npm run build && npm prune --omit=dev

FROM node:22.20.0-bookworm-slim
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
WORKDIR /src
COPY --from=build --chown=node:node /src/packages/sdk-typescript packages/sdk-typescript
COPY --from=build --chown=node:node /src/apps/dashboard apps/dashboard
USER node
WORKDIR /src/apps/dashboard
EXPOSE 3000
HEALTHCHECK --interval=5s --retries=20 CMD node -e "fetch('http://127.0.0.1:3000/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["npx", "next", "start", "-p", "3000"]
