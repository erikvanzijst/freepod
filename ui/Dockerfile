FROM node:24-alpine AS docs

WORKDIR /docs

COPY docs/package*.json ./
RUN npm ci

COPY docs/ ./
RUN npm run build

FROM node:24-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:alpine

ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}

COPY --from=builder /app/dist /usr/share/nginx/html
COPY --from=docs /docs/build /usr/share/nginx/html/docs
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
