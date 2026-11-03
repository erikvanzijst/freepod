# Keycloak with the Freepod theme and login provider baked in.
#
# The custom login/account/email theme (theme/freepod/) is ~22 files / ~400KB
# of CSS, fonts, logo and FreeMarker templates — too much to ride along in a
# ConfigMap mount, so we bake it into the image instead. Themes are read from
# /opt/keycloak/themes at runtime, so a plain COPY is all that's needed.
#
# The provider (provider/) shows the app a sign-in is for on the login pages
# and in that flow's emails. It extends Keycloak's internal FreeMarker login
# and email providers, so it is compiled against this exact base image's jars:
# a Keycloak upgrade that changes what it overrides fails this build.
#
# Build + push with: ./scripts/build-images.sh <version>-<build> --keycloak
# (see keycloak_image in variables.tf for the tag scheme).

ARG KEYCLOAK=quay.io/keycloak/keycloak:26.8.1

FROM ${KEYCLOAK} AS keycloak

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

# The base image runs Java 21, so the provider targets 21. VectorCheck pins
# the signature to app-auth's and is left out of the jar.
FROM eclipse-temurin:21-jdk AS provider
COPY --from=keycloak /opt/keycloak/lib/lib /kc-lib
COPY provider /provider
WORKDIR /provider
RUN set -eu; \
    cp='/kc-lib/main/*:/kc-lib/boot/*'; \
    javac --release 21 -Xlint:all -Werror -cp "$cp" -d out $(find src -name '*.java'); \
    javac --release 21 -cp "$cp:out" -d test-out $(find test -name '*.java'); \
    java -cp "$cp:out:test-out" eu.freepod.keycloak.VectorCheck; \
    cp -r src/META-INF out/; \
    jar --create --file /freepod-keycloak.jar -C out .

FROM keycloak

COPY --from=theme /theme /opt/keycloak/themes/freepod
COPY --from=provider /freepod-keycloak.jar /opt/keycloak/providers/
# Our providers replace Keycloak's own; build-time options, applied as the
# server augments on start.
ENV KC_SPI_LOGIN__PROVIDER=freepod \
    KC_SPI_EMAIL_TEMPLATE__PROVIDER=freepod
