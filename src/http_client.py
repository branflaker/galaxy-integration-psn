import aiohttp
import logging

from urllib.parse import parse_qsl, urlsplit

from galaxy.api.errors import (
    AuthenticationRequired,
    BackendError,
    BackendNotAvailable,
    BackendTimeout,
    NetworkError,
    InvalidCredentials,
    UnknownBackendResponse
)
from galaxy.http import HttpClient

OAUTH_LOGIN_REDIRECT_URL = "https://my.playstation.com/auth/response.html"
OAUTH_STORE_REDIRECT_URL = "https://store.playstation.com/html/webIframeRedirect.html"

# TODO: we probably do not need all these scopes
LOGIN_SCOPE = "capone:report_submission"

NETWORK_SCOPE = "capone:report_submission" \
    ",kamaji:game_list" \
    ",kamaji:get_account_hash" \
    ",user:account.get" \
    ",user:account.profile.get" \
    ",kamaji:social_get_graph" \
    ",kamaji:ugc:distributor" \
    ",user:account.identityMapper" \
    ",kamaji:music_views" \
    ",kamaji:activity_feed_get_feed_privacy" \
    ",kamaji:activity_feed_get_news_feed" \
    ",kamaji:activity_feed_submit_feed_story" \
    ",kamaji:activity_feed_internal_feed_submit_story" \
    ",kamaji:account_link_token_web" \
    ",kamaji:ugc:distributor_web" \
    ",kamaji:url_preview"

STORE_SCOPE = "kamaji:get_vu_mylibrary" \
    ",kamaji:get_recs" \
    ",kamaji:get_internal_entitlements" \
    ",genome:gene_get" \
    ",wallets:instrument.get"

CLIENT_ID = "656ace0b-d627-47e6-915c-13b259cd06b2"

STORE_CLIENT_ID = "d932d31d-e8fc-4058-bd22-16d474938353"

OAUTH_URL = "https://auth.api.sonyentertainmentnetwork.com/2.0/oauth/authorize"

# TODO: generate random request ID
OAUTH_URL_BASE = \
    "https://auth.api.sonyentertainmentnetwork.com/2.0/oauth/authorize" \
    "?response_type=token" \
    "&scope={scope}" \
    "&client_id={client_id}" \
    "&redirect_uri={redirect}"

OAUTH_LOGIN_URL = OAUTH_URL_BASE.format(scope=LOGIN_SCOPE, redirect=OAUTH_LOGIN_REDIRECT_URL, client_id=CLIENT_ID) + \
    "?requestID=external_request_e0002664-7e12-474b-ba44-495683d32d3c" \
    "&baseUrl=/" \
    "&returnRoute=/" \
    "&targetOrigin=https://my.playstation.com" \
    "&excludeQueryParams=true" \
    "&prompt=login" \
    "&tp_console=true" \
    "&ui=pr"

OAUTH_TOKEN_URL = OAUTH_URL_BASE.format(scope=NETWORK_SCOPE, redirect=OAUTH_LOGIN_REDIRECT_URL, client_id=CLIENT_ID) + \
    "?requestID=iframe_request_c37ac45d-d6f2-4585-b93f-da014fe87579" \
    "&baseUrl=/" \
    "&targetOrigin=https://my.playstation.com" \
    "&prompt=none"

OAUTH_STORE_TOKEN_URL = OAUTH_URL_BASE.format(scope=STORE_SCOPE, redirect=OAUTH_STORE_REDIRECT_URL, client_id=STORE_CLIENT_ID) + \
    "?requestId=6dd8d96b-4a45-4f2a-8480-88434c56d57a"

DEFAULT_TIMEOUT = 30
CONNECTION_LIMIT = 20


def paginate_url(url, limit, offset=0):
    return url + "&limit={limit}&offset={offset}".format(limit=limit, offset=offset)


class AuthenticatedHttpClient(HttpClient):
    def __init__(self, token_url, auth_lost_callback):
        self._access_token = None
        self._refresh_token = None
        self._token_url = token_url
        self._auth_lost_callback = auth_lost_callback
        super().__init__(limit=CONNECTION_LIMIT, timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT))

    @property
    def is_authenticated(self):
        return self._access_token is not None

    def _auth_lost(self):
        self._access_token = None
        self._refresh_token = None
        if self._auth_lost_callback:
            self._auth_lost_callback()

    async def get_access_token(self, refresh_token):
        response = None
        try:
            response = await super().request(
                "GET",
                url=self._token_url,
                cookies={"npsso": refresh_token},
                allow_redirects=False
            )
            return dict(parse_qsl(urlsplit(response.headers["Location"]).fragment))["access_token"]
        except AuthenticationRequired:
            raise InvalidCredentials()
        except (KeyError, IndexError):
            raise UnknownBackendResponse()
        finally:
            if response:
                response.close()

    async def authenticate(self, refresh_token):
        self._refresh_token = refresh_token
        self._access_token = await self.get_access_token(self._refresh_token)
        if not self._access_token:
            raise UnknownBackendResponse("Empty access token")

    async def _refresh_access_token(self):
        try:
            self._access_token = await self.get_access_token(self._refresh_token)
            if not self._access_token:
                raise UnknownBackendResponse("Empty access token")
        except (BackendNotAvailable, BackendTimeout, BackendError, NetworkError):
            logging.warning("Failed to refresh token for independent reasons")
            raise
        except Exception:
            logging.exception("Failed to refresh token")
            if self._auth_lost_callback:
                self._auth_lost_callback()
            raise AuthenticationRequired()

    async def request(self, method, *args, **kwargs):
        if not self._access_token:
            raise AuthenticationRequired()

        try:
            return await self._request(method, *args, **kwargs)
        except AuthenticationRequired:
            await self._refresh_access_token()
            return await self._request(method, *args, **kwargs)

    async def _request(self, method, *args, **kwargs):
        headers = kwargs.setdefault("headers", {})
        headers["authorization"] = "Bearer " + self._access_token
        return await super().request(method, *args, **kwargs)

    async def get(self, url, *args, **kwargs):
        response = await self.request("GET", *args, url=url, **kwargs)
        try:
            logging.debug("Response for:\n{url}\n{data}".format(url=url, data=await response.text()))
            return await response.json()
        except ValueError:
            logging.exception("Invalid response data for:\n{url}".format(url=url))
            raise UnknownBackendResponse()

    async def post(self, url, *args, **kwargs):
        logging.debug("Sending data:\n{url}".format(url=url))
        return await self.request("POST", *args, url=url, **kwargs)

    async def logout(self):
        await self._session.close()
