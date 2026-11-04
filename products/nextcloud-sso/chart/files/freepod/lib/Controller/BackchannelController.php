<?php

declare(strict_types=1);

namespace OCA\Freepod\Controller;

use OCA\UserOIDC\Controller\LoginController;
use OCP\AppFramework\Controller;
use OCP\AppFramework\Http;
use OCP\AppFramework\Http\Attribute\FrontpageRoute;
use OCP\AppFramework\Http\Attribute\NoCSRFRequired;
use OCP\AppFramework\Http\Attribute\PublicPage;
use OCP\AppFramework\Http\Response;
use OCP\Authentication\Token\IProvider;
use OCP\IConfig;
use OCP\IRequest;
use OCP\IUserManager;
use Psr\Log\LoggerInterface;

/**
 * The deployment's back-channel logout endpoint. user_oidc verifies every token
 * and ends the sessions it names. A token that also carries
 * `freepod_access: revoked` means the person lost access to the deployment, so
 * their app passwords and remembered logins go too. Their account and files
 * stay, so being given access again is enough to sign in again.
 */
class BackchannelController extends Controller {
	private const PROVIDER = 'freepod';

	public function __construct(
		string $appName,
		IRequest $request,
		private LoginController $login,
		private IUserManager $users,
		private IProvider $tokens,
		private IConfig $config,
		private LoggerInterface $logger,
	) {
		parent::__construct($appName, $request);
	}

	#[PublicPage]
	#[NoCSRFRequired]
	#[FrontpageRoute(verb: 'POST', url: '/backchannel-logout')]
	public function logout(string $logout_token = ''): Response {
		$response = $this->login->backChannelLogout(self::PROVIDER, $logout_token);
		if ($response->getStatus() !== Http::STATUS_OK) {
			return $response;
		}

		// user_oidc answers 200 only for a token it verified.
		$claims = self::payload($logout_token);
		if (($claims['freepod_access'] ?? null) !== 'revoked' || !is_string($claims['sub'] ?? null)) {
			return $response;
		}

		// The provider is pinned to unique-uid 0, so the user ID is the subject.
		$user = $this->users->get($claims['sub']);
		if ($user === null || $user->getBackendClassName() !== 'user_oidc') {
			return $response;
		}
		$uid = $user->getUID();
		$this->tokens->invalidateTokensOfUser($uid, null);
		foreach ($this->config->getUserKeys($uid, 'login_token') as $rememberMe) {
			$this->config->deleteUserValue($uid, 'login_token', $rememberMe);
		}
		$this->logger->info('Freepod revoked access: ended every sign-in of {uid}', ['uid' => $uid]);
		return $response;
	}

	private static function payload(string $jwt): array {
		$parts = explode('.', $jwt);
		$json = base64_decode(strtr($parts[1] ?? '', '-_', '+/'), true);
		$claims = $json === false ? null : json_decode($json, true);
		return is_array($claims) ? $claims : [];
	}
}
