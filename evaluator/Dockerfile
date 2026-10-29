FROM node:24.21.0-alpine3.24

WORKDIR /evaluator
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
RUN apk upgrade --no-cache && apk add --no-cache chromium font-noto-cjk && \
    npm install --global npm@12.2.0 --ignore-scripts --no-audit --no-fund

COPY package.json package-lock.json /evaluator/
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund && \
    rm -rf /root/.npm /usr/local/lib/node_modules/npm \
           /usr/local/lib/node_modules/corepack /opt/yarn-* && \
    rm -f /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack \
          /usr/local/bin/yarn /usr/local/bin/yarnpkg
COPY . /evaluator/

EXPOSE 3000
CMD ["node", "server.js"]
