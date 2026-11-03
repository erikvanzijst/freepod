package eu.freepod.keycloak;

/**
 * Run at image build: the provider must accept exactly what app-auth signs.
 * The vectors are app-auth's (daemons/app-auth/brand_test.go); change both together.
 */
public final class VectorCheck {
    static final String SECRET = "vector-client-secret";
    static final String CATALOG = "eyJuYW1lIjoiSW1taWNoIiwiaG9zdCI6InBob3Rvcy1hbGljZS5mcmVlcG9kLmFwcCIsImljb24iOiJodHRwczovL2ZyZWVwb2QuZXUvYXBpL3N0YXRpYy9pY29ucy8yOTYxLnBuZyJ9.R5CfhT9TzIAYJiTcNZVsCxaIoS22uIPtkrrfUvvIDdQ";
    static final String HOST_ONLY = "eyJob3N0Ijoid2lraS1hbGljZS5mcmVlcG9kLmFwcCJ9.w_3fbkNO3n_vW3T1Q9voJJP-NZOKEZ8_ORG5Sr5fX8I";

    public static void main(String[] args) {
        AppContext.App app = AppContext.verify(SECRET, CATALOG);
        check(app != null && "Immich".equals(app.getName()) && "photos-alice.freepod.app".equals(app.getHost())
                && "https://freepod.eu/api/static/icons/2961.png".equals(app.getIcon()), "catalog vector");
        app = AppContext.verify(SECRET, HOST_ONLY);
        check(app != null && app.getName() == null && "wiki-alice.freepod.app".equals(app.getLabel()), "host-only vector");
        check(AppContext.verify("another-secret", CATALOG) == null, "another client's secret");
        check(AppContext.verify(SECRET, CATALOG.substring(0, CATALOG.length() - 2) + "AA") == null, "a forged signature");
        check(AppContext.verify(SECRET, "garbage") == null, "garbage");
        System.out.println("app context vectors: ok");
    }

    private static void check(boolean ok, String what) {
        if (!ok) throw new AssertionError("app context vector failed: " + what);
    }
}
