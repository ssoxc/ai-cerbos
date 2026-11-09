FROM ghcr.io/cerbos/cerbos:0.57.0@sha256:e5e3b150b3cb0090975605254f255164567d67e233634199fb20972e3eaff300
COPY config.yaml /config/config.yaml
# The shipped policies. In the demo stack a named volume is mounted over /policies and
# holds the live, editable copy; the test stack uses these baked files unchanged.
# Owned by the API's uid so the API can write to a volume Docker seeds from this image.
COPY --chown=10001:10001 policies /policies
# Cerbos's decision log directory, also a shared volume (read-only for the API).
COPY --chown=10001:10001 audit /audit
# Run unprivileged, as the same uid as the API, so the API can read the decision log.
USER 10001:10001
