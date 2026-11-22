FROM python:3.13.16-alpine3.24

# This service uses only the standard library; omit the package installer.
RUN apk upgrade --no-cache && python -m pip uninstall -y pip setuptools && rm -rf /root/.cache
WORKDIR /server
COPY server.py /server/server.py

EXPOSE 8080
CMD ["python", "/server/server.py"]
