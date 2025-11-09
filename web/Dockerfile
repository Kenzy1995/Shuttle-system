FROM nginx:alpine

RUN rm /etc/nginx/conf.d/default.conf
COPY . /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

WORKDIR /usr/share/nginx/html
RUN chmod -R 755 /usr/share/nginx/html

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
