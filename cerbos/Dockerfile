FROM ghcr.io/cerbos/cerbos:0.57.0@sha256:e5e3b150b3cb0090975605254f255164567d67e233634199fb20972e3eaff300
COPY config.yaml /config/config.yaml
# The shipped policies. In the demo stack a named volume is mounted over /policies and
# holds the live, editable copy; the test stack uses these baked files unchanged.
# Owned by the API's uid so the API can write to a volume Docker seeds from this image.
COPY --chown=10001:10001 policies /policies
