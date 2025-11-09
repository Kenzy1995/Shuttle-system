FROM nginx:alpine

# 移除預設站台
RUN rm /etc/nginx/conf.d/default.conf

# 複製自訂 Nginx 設定
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 複製網站內容
COPY . /usr/share/nginx/html

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
