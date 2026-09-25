FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /out/gateflow ./cmd/gateway && go build -o /out/mock-upstream ./cmd/mockupstream

FROM alpine:3.20
RUN apk add --no-cache wget
RUN adduser -D -u 10001 app
WORKDIR /app/backend
COPY --from=build /out/gateflow /usr/local/bin/gateflow
COPY --from=build /out/mock-upstream /usr/local/bin/mock-upstream
COPY migrations ./migrations
USER app
EXPOSE 8080 9090
CMD ["/usr/local/bin/gateflow"]
