FROM docker.io/library/docker:27-cli

# Build-time proxy for apk (runtime: x-proxy-guard, no net installs).
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ARG http_proxy
ARG https_proxy
ARG no_proxy

RUN apk add --no-cache inotify-tools
