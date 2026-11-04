package eu.freepod.keycloak;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Base64;
import java.util.Map;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.jboss.logging.Logger;
import org.keycloak.models.ClientModel;
import org.keycloak.models.KeycloakSession;
import org.keycloak.sessions.AuthenticationSessionModel;
import org.keycloak.util.JsonSerialization;

/**
 * The app a sign-in is for, as app-auth vouches for it.
 *
 * app-auth adds {@code freepod_app=<b64url(json)>.<b64url(hmac)>} to its
 * authorization and logout requests. Keycloak keeps an authorization request's
 * unrecognized parameters as client notes on the authentication session, so
 * the value lasts for every page and email of that flow; a logout keeps none,
 * so its value is taken from the request and noted here. Anyone can put the
 * parameter on a URL, so a value without a valid signature is ignored.
 *
 * The signing key is derived from the requesting client's secret, which
 * app-auth already holds: each environment's client signs with its own key,
 * and a public client can't vouch at all. app-auth signs the same way
 * (daemons/app-auth/brand.go); a shared vector pins the two together.
 */
public final class AppContext {
    public static final String PARAM = "freepod_app";
    static final String NOTE = "client_request_param_" + PARAM;
    static final String ATTRIBUTE = "freepodApp";
    private static final Logger LOG = Logger.getLogger(AppContext.class);
    private static final byte[] KEY_LABEL = "freepod-app-context:v1".getBytes(StandardCharsets.US_ASCII);

    private AppContext() {}

    /**
     * Exposed to templates as {@code freepodApp}. {@code name} is a catalog app's
     * own name; an app without one (custom) has only its {@code host}.
     * {@code label} is whichever of the two prose should use.
     */
    public static final class App {
        private final String name, host, icon;
        App(String name, String host, String icon) { this.name = name; this.host = host; this.icon = icon; }
        public String getName() { return name; }
        public String getHost() { return host; }
        public String getIcon() { return icon; }
        public String getLabel() { return name != null ? name : host; }
    }

    /** As {@link #from(AuthenticationSessionModel)}, noting a value on the request on the way. */
    static App from(KeycloakSession keycloak, AuthenticationSessionModel session) {
        if (session != null && session.getClientNote(NOTE) == null && keycloak.getContext().getUri() != null) {
            String value = keycloak.getContext().getUri().getQueryParameters().getFirst(PARAM);
            ClientModel client = session.getClient();
            if (value != null && client != null && !client.isPublicClient() && verify(client.getSecret(), value) != null) {
                session.setClientNote(NOTE, value);
            }
        }
        return from(session);
    }

    static App from(AuthenticationSessionModel session) {
        ClientModel client = session == null ? null : session.getClient();
        if (client == null || client.isPublicClient()) return null;
        String value = session.getClientNote(NOTE);
        return value == null ? null : verify(client.getSecret(), value);
    }

    /** The app {@code value} names, or null unless {@code clientSecret} signed it. */
    static App verify(String clientSecret, String value) {
        if (clientSecret == null || clientSecret.isEmpty()) return null;
        int dot = value.indexOf('.');
        if (dot < 1) return null;
        try {
            String payload = value.substring(0, dot);
            byte[] key = hmac(clientSecret.getBytes(StandardCharsets.UTF_8), KEY_LABEL);
            byte[] want = hmac(key, payload.getBytes(StandardCharsets.US_ASCII));
            byte[] got = Base64.getUrlDecoder().decode(value.substring(dot + 1));
            if (!MessageDigest.isEqual(want, got)) return null;
            Map<?, ?> m = JsonSerialization.readValue(Base64.getUrlDecoder().decode(payload), Map.class);
            String name = str(m.get("name")), host = str(m.get("host"));
            if (name == null && host == null) return null;
            return new App(name, host, name == null ? null : str(m.get("icon")));
        } catch (Exception e) {
            LOG.debugf("Ignoring malformed %s: %s", PARAM, e.getMessage());
            return null;
        }
    }

    private static byte[] hmac(byte[] key, byte[] data) throws Exception {
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(key, "HmacSHA256"));
        return mac.doFinal(data);
    }

    private static String str(Object o) {
        return o instanceof String s && !s.isBlank() ? s : null;
    }
}
