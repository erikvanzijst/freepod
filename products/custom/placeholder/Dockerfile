# Placeholder page for a `custom` deployment that has no image yet.
#
# `freepod init` creates the deployment — and claims and routes its hostname —
# before any build exists. Without something to serve, the tenant's own domain
# would answer with a Traefik 503 from the moment they registered it. This image
# is what the chart runs instead, until `image` is set.
#
# It is referenced by the chart's `placeholderImage` system value, never by a
# user-supplied one: a second tenant-settable image reference would bypass the
# ownership assertion in templates/_helpers.tpl entirely.
#
# Build and publish: see products/custom/README.md.
FROM nginx:1.31.9-alpine

# Listen on the chart's containerPort rather than nginx's default 80, so the
# placeholder and a real user image are reachable through the same Service
# target.
#
# Tenant images bind $PORT, which the chart injects; nginx will not read it
# without templating, so this one is pinned to the chart's default (8080). If
# that default ever moves, rebuild this image and default.conf with it.
COPY default.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html

EXPOSE 8080
