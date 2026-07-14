FROM golang:1.22 AS build

WORKDIR /src
COPY go.mod ./
COPY cmd ./cmd
COPY internal ./internal

RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w" -o /out/mutt ./cmd/router

FROM gcr.io/distroless/static-debian12:nonroot

WORKDIR /app
COPY --from=build /out/mutt /usr/local/bin/mutt
COPY config ./config

EXPOSE 8080 8081

ENTRYPOINT ["/usr/local/bin/mutt"]
CMD ["-config", "/app/config/router.example.json"]
