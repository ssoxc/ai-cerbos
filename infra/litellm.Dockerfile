FROM ghcr.io/berriai/litellm@sha256:37e2dafb088a7723beb998590682957386dfc83ffea1848486f8e0e5cfac0b06
COPY infra/litellm.yaml /app/config.yaml
# LiteLLM resolves "cerbos_guard.proxy_handler_instance" relative to the config file.
COPY infra/cerbos_guard.py /app/cerbos_guard.py
