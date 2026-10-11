FROM node:22-slim
WORKDIR /app/caller
COPY caller/package*.json ./
RUN npm ci --omit=dev
COPY caller/src ./src
COPY caller/examples ./examples
COPY lib /app/lib
ENV HOST=0.0.0.0 PORT=8787 CALLER_DATA_DIR=/data
RUN mkdir /data && chown node:node /data
USER node
EXPOSE 8787
CMD ["npm", "start"]
