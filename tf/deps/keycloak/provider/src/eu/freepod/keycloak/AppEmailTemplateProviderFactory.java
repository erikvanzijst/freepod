package eu.freepod.keycloak;

import org.keycloak.email.EmailTemplateProvider;
import org.keycloak.email.freemarker.FreeMarkerEmailTemplateProviderFactory;
import org.keycloak.models.KeycloakSession;

public class AppEmailTemplateProviderFactory extends FreeMarkerEmailTemplateProviderFactory {
    @Override
    public EmailTemplateProvider create(KeycloakSession session) {
        return new AppEmailTemplateProvider(session);
    }

    @Override
    public String getId() {
        return "freepod";
    }
}
