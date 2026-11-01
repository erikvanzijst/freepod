# frozen_string_literal: true

# name: freepod-backchannel-logout
# about: Ends a user's forum sessions when Freepod sends an OpenID Connect back-channel logout token.
# version: 1.0
# authors: Freepod
# url: https://freepod.eu

after_initialize do
  module ::FreepodBackchannelLogout
    EVENT = "http://schemas.openid.net/event/backchannel-logout"
    JWKS_CACHE_KEY = "freepod-backchannel-logout-jwks"

    def self.subject_of(token)
      document = OpenIDConnectAuthenticator.new.discovery_document
      raise JWT::DecodeError, "no discovery document" if document.blank?

      claims, header =
        JWT.decode(
          token,
          nil,
          true,
          algorithms: ["RS256"],
          iss: document["issuer"],
          verify_iss: true,
          aud: SiteSetting.openid_connect_client_id,
          verify_aud: true,
          verify_iat: true,
          jwks: ->(options) { jwks(document["jwks_uri"], refresh: options[:kid_not_found]) },
        )

      valid =
        header["typ"] == "logout+jwt" && claims["sub"].present? && claims["nonce"].nil? &&
          claims["events"].is_a?(Hash) && claims["events"].key?(EVENT)
      raise JWT::DecodeError, "not a logout token" if !valid

      claims["sub"]
    end

    def self.jwks(uri, refresh:)
      # An unknown key ID means a rotation or a forged token, so at most once a minute.
      if refresh && Discourse.redis.set("#{JWKS_CACHE_KEY}-refreshed", 1, ex: 60, nx: true)
        Discourse.cache.delete(JWKS_CACHE_KEY)
      end
      Discourse
        .cache
        .fetch(JWKS_CACHE_KEY, expires_in: 10.minutes) do
          connection =
            Faraday.new(request: { timeout: 10 }) do |c|
              c.use Faraday::Response::RaiseError
              c.adapter FinalDestination::FaradayAdapter
            end
          JSON.parse(connection.get(uri).body)
        end
    end
  end

  class ::FreepodBackchannelLogoutController < ::ApplicationController
    skip_before_action :verify_authenticity_token,
                       :check_xhr,
                       :redirect_to_login_if_required,
                       :block_if_requires_login,
                       :preload_json

    # The provider's sids are not tied to a Discourse session, so a logout ends
    # all of the user's browser sessions. User API keys stay, like a phone's
    # session in any other app, and an unknown subject is not an error.
    def create
      subject = FreepodBackchannelLogout.subject_of(params.require(:logout_token).to_s)
      user = UserAssociatedAccount.find_by(provider_name: "oidc", provider_uid: subject)&.user
      if user
        user.user_auth_tokens.destroy_all
        user.log_out!
      end
      head :ok
    rescue JWT::DecodeError, Faraday::Error, ActionController::ParameterMissing => e
      Rails.logger.warn("Back-channel logout refused: #{e.class}: #{e.message}")
      head :bad_request
    end
  end

  Discourse::Application.routes.append do
    post "/freepod/backchannel-logout" => "freepod_backchannel_logout#create"
  end
end
