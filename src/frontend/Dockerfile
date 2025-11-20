FROM node:18-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
#default port of react
EXPOSE 3000
CMD ["npm", "start"]
