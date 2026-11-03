package eu.freepod.keycloak;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import org.keycloak.email.EmailException;
import org.keycloak.email.freemarker.FreeMarkerEmailTemplateProvider;
import org.keycloak.models.KeycloakSession;

/**
 * Keycloak's emails, plus {@code freepodApp} for those sent during an app's
 * sign-in (verification, password reset). A subject key with an {@code App}
 * suffix, when the theme has one, replaces the plain subject and gets the
 * app's name as its first argument.
 */
public class AppEmailTemplateProvider extends FreeMarkerEmailTemplateProvider {
    public AppEmailTemplateProvider(KeycloakSession session) {
        super(session);
    }

    @Override
    protected EmailTemplate processTemplate(String subjectKey, List<Object> subjectAttributes,
            String template, Map<String, Object> attributes) throws EmailException {
        AppContext.App app = AppContext.from(authenticationSession);
        if (app != null) {
            attributes.put(AppContext.ATTRIBUTE, app);
            String appKey = subjectKey + "App";
            try {
                Locale locale = session.getContext().resolveLocale(user);
                if (getTheme().getEnhancedMessages(realm, locale).containsKey(appKey)) {
                    List<Object> args = new ArrayList<>();
                    args.add(app.getLabel());
                    args.addAll(subjectAttributes);
                    return super.processTemplate(appKey, args, template, attributes);
                }
            } catch (java.io.IOException e) {
                throw new EmailException("Failed to load the email theme", e);
            }
        }
        return super.processTemplate(subjectKey, subjectAttributes, template, attributes);
    }
}
