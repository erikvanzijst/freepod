package eu.freepod.keycloak;

import org.keycloak.forms.login.LoginFormsProvider;
import org.keycloak.forms.login.freemarker.FreeMarkerLoginFormsProviderFactory;
import org.keycloak.models.KeycloakSession;

public class AppLoginFormsProviderFactory extends FreeMarkerLoginFormsProviderFactory {
    @Override
    public LoginFormsProvider create(KeycloakSession session) {
        return new AppLoginFormsProvider(session);
    }

    @Override
    public String getId() {
        return "freepod";
    }
}
