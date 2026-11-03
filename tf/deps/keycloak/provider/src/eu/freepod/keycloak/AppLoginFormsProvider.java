package eu.freepod.keycloak;

import jakarta.ws.rs.core.UriBuilder;
import java.util.Locale;
import java.util.Properties;
import org.keycloak.forms.login.LoginFormsPages;
import org.keycloak.forms.login.freemarker.FreeMarkerLoginFormsProvider;
import org.keycloak.models.KeycloakSession;
import org.keycloak.theme.Theme;

/** Keycloak's login forms, plus {@code freepodApp} when app-auth vouched for one. */
public class AppLoginFormsProvider extends FreeMarkerLoginFormsProvider {
    public AppLoginFormsProvider(KeycloakSession session) {
        super(session);
    }

    @Override
    protected void createCommonAttributes(Theme theme, Locale locale, Properties messagesBundle,
            UriBuilder baseUriBuilder, LoginFormsPages page) {
        super.createCommonAttributes(theme, locale, messagesBundle, baseUriBuilder, page);
        AppContext.App app = AppContext.from(authenticationSession);
        if (app != null) attributes.put(AppContext.ATTRIBUTE, app);
    }
}
