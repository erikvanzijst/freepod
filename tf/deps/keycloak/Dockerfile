# Keycloak with the Freepod theme baked in.
#
# The custom login/account/email theme (theme/freepod/) is ~22 files / ~400KB
# of CSS, fonts, logo and FreeMarker templates — too much to ride along in a
# ConfigMap mount, so we bake it into the image instead. Themes are read from
# /opt/keycloak/themes at runtime, so a plain COPY is all that's needed (no
# `kc.sh build` required, and build-time DB/feature options stay untouched).
#
# Build + push with: ./scripts/build-images.sh --keycloak

# Cache busting. Keycloak serves theme resources under /resources/<v>/ with a
# 30-day max-age, and <v> derives from the Keycloak version, not the theme, so
# browsers keep a stale stylesheet for a month after a theme change. Each of our
# stylesheets gets `?v=<content hash>` appended in its theme.properties `styles`
# entry; Keycloak ignores the query when serving the file.
FROM alpine:3.22 AS theme
COPY theme/freepod /theme
RUN set -eu; \
    for css in /theme/*/resources/css/*.css; do \
      props="${css%/resources/css/*}/theme.properties"; \
      name=$(basename "$css"); \
      hash=$(sha256sum "$css" | cut -c1-12); \
      sed -i -E "/^styles=/ s#(css/${name})( |\$)#\1?v=${hash}\2#" "$props"; \
      grep -q "^styles=.*css/${name}?v=${hash}" "$props" \
        || { echo "css/${name} is not listed in the styles of ${props}" >&2; exit 1; }; \
    done

FROM quay.io/keycloak/keycloak:24.0

COPY --from=theme /theme /opt/keycloak/themes/freepod
