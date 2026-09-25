FROM node:20-alpine AS build
WORKDIR /app

RUN npm install -g npm@10.9.8

COPY package*.json ./
RUN npm ci
# npm 10 can omit Rollup's platform-specific optional package from a lockfile
# generated on Windows; install the exact locked Rollup musl binary for Alpine.
RUN ROLLUP_VERSION=$(node -p "require('./node_modules/rollup/package.json').version") \
	&& npm install --no-save --package-lock=false --ignore-scripts "@rollup/rollup-linux-x64-musl@$ROLLUP_VERSION"
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80