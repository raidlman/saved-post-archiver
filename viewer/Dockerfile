ARG CADDY_VERSION=2.8.4
ARG VIEWER_VERSION=0.1.0

FROM caddy:${CADDY_VERSION}-alpine

# Contains ${VIEWER_BASIC_AUTH_*} placeholders - rendered into /etc/caddy/Caddyfile
# by an initContainer at pod start (see deployment-viewer.yaml), since the
# credentials are per-deployment secrets, not known at image build time.
COPY Caddyfile /etc/caddy-template/Caddyfile
