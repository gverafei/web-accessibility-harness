FROM golang:1.27.1-alpine3.24 AS gosu-build
ENV CGO_ENABLED=0 GOBIN=/out
WORKDIR /src
RUN go mod init a11yharness.local/gosu-build && \
    go get github.com/tianon/gosu@1.19 golang.org/x/sys@v0.44.0 && \
    go build -trimpath -o /out/gosu github.com/tianon/gosu

FROM mysql:8.4.11
# Refresh distro patches; the app uses the server/client, not MySQL Shell's Python.
RUN microdnf update -y && microdnf clean all && \
    rm -rf /usr/lib/mysqlsh /usr/bin/mysqlsh /usr/local/bin/mysqlsh
COPY --from=gosu-build /out/gosu /usr/local/bin/gosu
RUN gosu mysql id
