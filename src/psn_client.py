import asyncio
import logging
import unicodedata
from datetime import datetime, timezone
from functools import partial
from typing import Dict, List, NewType, Tuple

from galaxy.api.errors import UnknownBackendResponse
from galaxy.api.types import Achievement, Game, LicenseInfo, UserInfo, UserPresence, PresenceState
from galaxy.api.consts import LicenseType
from http_client import paginate_url, paginate_store_url

# game_id_list is limited to 5 IDs per request
GAME_DETAILS_URL = "https://pl-tpy.np.community.playstation.net/trophy/v1/apps/trophyTitles" \
    "?npTitleIds={game_id_list}" \
    "&fields=@default" \
    "&npLanguage=en"

GAME_LIST_URL = "https://gamelist.api.playstation.com/v1/users/{user_id}/titles" \
    "?type=owned,played" \
    "&app=richProfile" \
    "&sort=-lastPlayedDate" \
    "&iw=240"\
    "&ih=240"\
    "&fields=@default"

INTERNAL_ENTITLEMENTS_URL = "https://commerce.api.np.km.playstation.net/commerce/api/v1/users/{user_id}/internal_entitlements" \
    "?fields=drm_def"

TROPHY_TITLES_URL = "https://pl-tpy.np.community.playstation.net/trophy/v1/trophyTitles" \
    "?fields=@default" \
    "&platform=PS4" \
    "&npLanguage=en"

EARNED_TROPHIES_PAGE = "https://pl-tpy.np.community.playstation.net/trophy/v1/" \
    "trophyTitles/{communication_id}/trophyGroups/{trophy_group_id}/trophies?" \
    "fields=@default,trophyRare,trophyEarnedRate,trophySmallIconUrl,groupId" \
    "&visibleType=1" \
    "&npLanguage=en"

USER_INFO_URL = "https://pl-prof.np.community.playstation.net/userProfile/v1/users/{user_id}/profile2" \
    "?fields=accountId,onlineId"

DEFAULT_AVATAR_SIZE = "l"
FRIENDS_URL = "https://us-prof.np.community.playstation.net/userProfile/v1/users/{user_id}/friends/profiles2" \
    "?fields=accountId,onlineId,avatarUrls&avatarSizes={avatar_size_list}"

FRIENDS_WITH_PRESENCE_URL = "https://us-prof.np.community.playstation.net/userProfile/v1/users/{user_id}/friends/profiles2" \
    "?fields=accountId,onlineId,primaryOnlineStatus,presences(@titleInfo,lastOnlineDate)"


ENTITLEMENT_DETAILS_URL = "https://store.playstation.com/valkyrie-api/en/{country}/19/resolve/{id}"

PS3_SEARCH_URL = "https://store.playstation.com/valkyrie-api/en/{country}/19/faceted-search/{query}" \
    "?query=&platform=ps3&game_content_type=games&size=30&bucket=games&start=0"

COUNTRIES = [
    # NA region country
    "US",
    # EU region country, a nod to daslight on Discord who helped test
    "RO"
]

VALID_CLASSIFICATIONS = [
    "GAME",
    "PS1_CLASSIC",
    "PS2_CLASSIC"
]

ENTITLEMENT_PLATFORM_IDS = [
    # PS3
    # 10000000000000000000000000000000
    2147483648,
    # Vita, downloadable to PS3
    # 10001000000000000000000000000000
    #2281701376,
    # Vita
    # 00001000000000000000000000000000
    # 134217728,
    # PS1_CLASSIC?
    # 11111000000100000000000000000000
    4161798144
]

DEFAULT_LIMIT = 100
MAX_TITLE_IDS_PER_REQUEST = 5
MAX_ENTITLEMENTS_PER_REQUEST = 450

CommunicationId = NewType("CommunicationId", str)
TitleId = NewType("TitleId", str)
Entitlement = NewType("Entitlement", dict)
GameInfo = NewType("GameInfo", dict)
EntitlementId = NewType("EntitlementId", str)
UnixTimestamp = NewType("UnixTimestamp", int)
TrophyTitles = Dict[CommunicationId, UnixTimestamp]

def parse_timestamp(earned_date) -> UnixTimestamp:
    dt = datetime.strptime(earned_date, "%Y-%m-%dT%H:%M:%SZ")
    dt = datetime.combine(dt.date(), dt.time(), timezone.utc)
    return UnixTimestamp(dt.timestamp())

def longest_common_prefix(s1, s2):
    out = ''
    s1test = s1.lstrip("The ")
    s2test = s2.lstrip("The ")
    s1test = unicodedata.normalize("NFKD", s1test.casefold())
    s2test = unicodedata.normalize("NFKD", s2test.casefold())
    for i, j, k in zip(s1test, s2test, s1):
        if i != j:
            break
        out += k
    return out


class PSNClient:
    def __init__(self, http_client, store_http_client):
        self._http_client = http_client
        self._store_http_client = store_http_client

    @staticmethod
    async def _async(method, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(method, *args, **kwargs))

    async def fetch_paginated_data(
        self,
        parser,
        url,
        counter_name,
        limit=DEFAULT_LIMIT,
        *args,
        **kwargs
    ):
        response = await self._http_client.get(paginate_url(url=url, limit=limit), *args, **kwargs)
        if not response:
            return []

        try:
            total = int(response.get(counter_name, 0))
        except ValueError:
            raise UnknownBackendResponse()

        responses = [response] + await asyncio.gather(*[
            self._http_client.get(paginate_url(url=url, limit=limit, offset=offset), *args, **kwargs)
            for offset in range(limit, total, limit)
        ])

        try:
            return [rec for res in responses for rec in parser(res)]
        except Exception:
            logging.exception("Cannot parse data")
            raise UnknownBackendResponse()

    async def fetch_data(self, parser, *args, **kwargs):
        response = await self._http_client.get(*args, **kwargs)

        try:
            return parser(response)
        except Exception:
            logging.exception("Cannot parse data")
            raise UnknownBackendResponse()

    async def fetch_paginated_store_data(
        self,
        parser,
        url,
        counter_name,
        limit=MAX_ENTITLEMENTS_PER_REQUEST,
        *args,
        **kwargs
    ):
        response = await self._store_http_client.get(paginate_store_url(url=url, size=limit), *args, **kwargs)
        if not response:
            return []

        try:
            total = int(response.get(counter_name, 0))
        except ValueError:
            raise UnknownBackendResponse()

        responses = [response] + await asyncio.gather(*[
            self._store_http_client.get(paginate_store_url(url=url, size=limit, start=offset), *args, **kwargs)
            for offset in range(limit, total, limit)
        ])

        try:
            return [rec for res in responses for rec in parser(res)]
        except Exception:
            logging.exception("Cannot parse data")
            raise UnknownBackendResponse()

    async def fetch_store_data(self, parser, *args, **kwargs):
        response = await self._store_http_client.get(*args, **kwargs)

        try:
            return parser(response)
        except Exception:
            logging.exception("Cannot parse data")
            raise UnknownBackendResponse()

    async def async_get_own_user_info(self):
        def user_info_parser(response):
            return response["profile"]["accountId"], response["profile"]["onlineId"]

        return await self.fetch_data(
            user_info_parser,
            USER_INFO_URL.format(user_id="me")
        )

    async def async_get_owned_games(self):
        def game_parser(title):
            return Game(
                game_id=title["titleId"],
                game_title=title["name"],
                dlcs=[],
                license_info=LicenseInfo(LicenseType.SinglePurchase, None)
            )

        def games_parser(response):
            return [
               game_parser(title) for title in response["titles"]
            ] if response else []

        return await self.fetch_paginated_data(
            games_parser,
            GAME_LIST_URL.format(user_id="me"),
            "totalResults"
        )

    async def async_get_game_communication_id_map(self, game_ids: List[TitleId]) \
            -> Dict[TitleId, List[CommunicationId]]:
        def communication_ids_parser(response):
            def get_comm_ids(trophy_titles):
                result = []
                for trophy_title in trophy_titles:
                    comm_id = trophy_title.get("npCommunicationId")
                    if comm_id is not None:
                        result.append(comm_id)
                return result

            try:
                return {
                    app["npTitleId"]: get_comm_ids(app["trophyTitles"])
                    for app in response["apps"]
                } if response else {}
            except (KeyError, IndexError):
                return {}

        mapping = await self.fetch_data(
            communication_ids_parser,
            GAME_DETAILS_URL.format(game_id_list=",".join(game_ids))
        )

        return {
            game_id: mapping.get(game_id, [])
            for game_id in game_ids
        }

    async def async_get_owned_ps3_entitlements(self):
        def ps3_entitlements(entitlement):
            return "drm_def" in entitlement \
                and entitlement["drm_def"]["drmContents"][0]["platformIds"] in ENTITLEMENT_PLATFORM_IDS \
                and entitlement["drm_def"]["drmContents"][0]["drmType"] != 3 \
                and "contentName" in entitlement["drm_def"] \
                and "entitlementId" in entitlement["drm_def"]

        def ps3_title_parser(title):
            return dict(
                content_name=title["drm_def"]["contentName"],
                id=title["drm_def"]["entitlementId"]
            )

        def entitlements_parser(response):
            return [
                ps3_title_parser(title) for title in filter(ps3_entitlements, response["entitlements"])
            ] if response and "entitlements" in response else []

        return await self.fetch_paginated_store_data(
            entitlements_parser,
            INTERNAL_ENTITLEMENTS_URL.format(user_id="me"),
            "total_results"
        )

    async def async_get_game_info(self, entitlement: Entitlement) -> GameInfo:
        def game_info_parser(response):
            try:
                if response:
                    main_info = response["data"]["relationships"]["children"]["data"][0]
                    if (main_info["type"] == "game") and (main_info["id"] == entitlement["id"]):
                        return dict(
                            classification=response["included"][0]["attributes"]["secondary-classification"],
                            title=longest_common_prefix(
                                response["included"][0]["attributes"]["name"],
                                entitlement["content_name"]
                            )
                        )
                return {}
            except (KeyError, IndexError):
                return {}

        def search_parser(response):
            try:
                if response and ("included" in response):
                    for i in response["included"]:
                        if (i["type"] == "game") and ("name" in i["attributes"]) and (i["attributes"]["name"] == entitlement["content_name"]):
                            return dict(
                                classification="GAME",
                                title=entitlement["content_name"]
                            )
                    return {}
                else:
                    return {}
            except (KeyError, IndexError):
                return {}

        result = None
        for country in COUNTRIES:
            try:
                name = " ".join(entitlement["content_name"].split(" ")[-3:])
                result = await self.fetch_store_data(
                    search_parser,
                    PS3_SEARCH_URL.format(query=name,country=country)
                )
                if not(result):
                    result = await self.fetch_store_data(
                        game_info_parser,
                        ENTITLEMENT_DETAILS_URL.format(id=entitlement["id"],country=country)
                    )
            except:
                continue
            break

        if result:
            result["title"] = result["title"] \
                .replace("Full Game Unlock", "") \
                .replace("- Full Game", "") \
                .replace("– Full Game", "") \
                .replace("Full Game", "") \
                .replace("full game", "") \
                .replace("Unlock", "") \
                .strip()

        return result

    async def get_trophy_titles(self) -> TrophyTitles:
        def title_parser(title) -> Tuple[CommunicationId, UnixTimestamp]:
            return (title["npCommunicationId"], parse_timestamp((title.get("fromUser") or {})["lastUpdateDate"]))

        def titles_parser(response) -> List[Tuple[CommunicationId, UnixTimestamp]]:
            return [
                title_parser(title) for title in response.get("trophyTitles", [])
            ] if response else []

        result = await self.fetch_paginated_data(
            parser=titles_parser,
            url=TROPHY_TITLES_URL,
            counter_name="totalResults"
        )
        return dict(result)

    async def async_get_earned_trophies(self, communication_id) -> List[Achievement]:
        def trophy_parser(trophy) -> Achievement:
            return Achievement(
                achievement_id="{}_{}".format(communication_id, trophy["trophyId"]),
                achievement_name=str(trophy["trophyName"]),
                unlock_time=parse_timestamp(trophy["fromUser"]["earnedDate"])
            )

        def trophies_parser(response) -> List[Achievement]:
            return [
                trophy_parser(trophy) for trophy in response.get("trophies", [])
                if trophy.get("fromUser") and trophy["fromUser"].get("earned")
            ] if response else []

        return await self.fetch_data(trophies_parser, EARNED_TROPHIES_PAGE.format(
            communication_id=communication_id,
            trophy_group_id="all"))

    async def async_get_friends(self):
        def friend_info_parser(profile):

            avatar_url = None
            for avatar in profile["avatarUrls"]:
                avatar_url = avatar["avatarUrl"]

            return UserInfo(
                user_id=str(profile["accountId"]),
                user_name=str(profile["onlineId"]),
                avatar_url=avatar_url,
                profile_url=f"https://my.playstation.com/profile/{str(profile['onlineId'])}"
            )

        def friend_list_parser(response):
            logging.info(response)
            return [
                friend_info_parser(profile) for profile in response.get("profiles", [])
            ] if response else []

        return await self.fetch_paginated_data(
            friend_list_parser,
            FRIENDS_URL.format(user_id="me", avatar_size_list=DEFAULT_AVATAR_SIZE),
            "totalResults"
        )

    async def async_get_friends_presences(self):
        def friend_info_parser(profile):

            if profile["primaryOnlineStatus"] == "online":
                presence_state = PresenceState.Online
            else:
                presence_state = PresenceState.Offline

            game_title = game_id = None

            if "presences" in profile:
                for presence in profile["presences"]:
                    try:
                        if presence["onlineStatus"] == "online" and presence["platform"] == "PS4":
                            game_title = presence["titleName"]
                            game_id = presence["npTitleId"]
                    except:
                        continue

            return {profile['accountId']: UserPresence(presence_state, game_id, game_title)}

        def friends_with_presence_parser(response):
            return [
                friend_info_parser(profile) for profile in response.get("profiles", [])
            ] if response else []

        return await self.fetch_paginated_data(
            friends_with_presence_parser,
            FRIENDS_WITH_PRESENCE_URL.format(user_id="me"),
            "totalResults"
        )
