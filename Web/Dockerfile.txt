# 使用 Nginx 作為靜態網站伺服器
FROM nginx:alpine

# 刪除預設設定並複製自訂設定
RUN rm /etc/nginx/conf.d/default.conf
COPY web /usr/share/nginx/html
COPY web/nginx.conf /etc/nginx/conf.d/default.conf

# 設定工作目錄與權限
WORKDIR /usr/share/nginx/html
RUN chmod -R 755 /usr/share/nginx/html

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
