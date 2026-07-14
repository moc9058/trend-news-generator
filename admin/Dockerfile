FROM node:24-slim AS build
WORKDIR /srv
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY . .
RUN npm run build

FROM node:24-slim
WORKDIR /srv
ENV NODE_ENV=production PORT=8080 HOSTNAME=0.0.0.0
COPY --from=build /srv/.next/standalone ./
COPY --from=build /srv/.next/static ./.next/static
COPY --from=build /srv/public ./public
EXPOSE 8080
CMD ["node", "server.js"]
