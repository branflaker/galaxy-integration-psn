import pytest
from galaxy.api.errors import AuthenticationRequired, UnknownBackendResponse
from http_client import paginate_url
from psn_client import DEFAULT_LIMIT, GAME_LIST_URL, INTERNAL_ENTITLEMENTS_URL
from tests.async_mock import AsyncMock
from tests.test_data import COMMUNICATION_ID, GAME_INFO
from tests.test_data import GAMES, PS3_GAMES, BACKEND_GAME_TITLES_WITHOUT_DLC, BACKEND_ENTITLEMENTS_WITHOUT_DLC


@pytest.mark.asyncio
async def test_not_authenticated(psn_plugin):
    with pytest.raises(AuthenticationRequired):
        await psn_plugin.get_owned_games()


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_response, entitlement_response, games, ps3_games", [
    ({}, {}, [], []),
    ({"titles": []}, {"entitlements": []}, [], []),
    (BACKEND_GAME_TITLES_WITHOUT_DLC, BACKEND_ENTITLEMENTS_WITHOUT_DLC, GAMES, PS3_GAMES)
])
async def test_get_owned_games(
    http_get,
    authenticated_plugin,
    backend_response,
    entitlement_response,
    games,
    ps3_games,
    mocker
):
    http_get.side_effect = [backend_response, entitlement_response]
    get_game_communication_id = mocker.patch(
        "plugin.PSNPlugin.get_game_communication_ids",
        new_callable=AsyncMock,
        return_value={game.game_id: COMMUNICATION_ID for game in GAMES}
    )
    get_ps3_game_info = mocker.patch(
        "plugin.PSNPlugin.get_ps3_game_info",
        new_callable=AsyncMock,
        return_value={game.game_id: {**GAME_INFO, "title": game.game_title} for game in PS3_GAMES }
    )

    assert (games + ps3_games) == await authenticated_plugin.get_owned_games()
    http_get.assert_any_call(
        paginate_url(GAME_LIST_URL.format(user_id="me"), DEFAULT_LIMIT))
    http_get.assert_any_call(INTERNAL_ENTITLEMENTS_URL.format(user_id="me"))
    assert 2 == http_get.call_count
    get_game_communication_id.assert_called_once_with([game.game_id for game in games])
    args = get_ps3_game_info.call_args
    assert [game.game_id for game in ps3_games] == [e["id"] for e in args[0][0]]


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_response, entitlement_response", [
    ({"titles": "bad_format"}, {"entitlements": "bad_format"}),
    ({"titles": {"titleId": "CUSA07917_00"}}, {"entitlements": {"id": "UP0101-NPUB31633_00-MGS4MAINGAME0000"}}),
    ({"titles": {"name": "Tooth and Tail"}}, {"entitlements": {"name": "Tooth and Tail"}})
])
async def test_bad_format(
    http_get,
    authenticated_plugin,
    backend_response,
    entitlement_response
):
    http_get.side_effect = [backend_response, entitlement_response]
    with pytest.raises(UnknownBackendResponse):
        await authenticated_plugin.get_owned_games()

    http_get.assert_any_call(
        paginate_url(GAME_LIST_URL.format(user_id="me"), DEFAULT_LIMIT))
    http_get.assert_any_call(INTERNAL_ENTITLEMENTS_URL.format(user_id="me"))
    assert 2 == http_get.call_count
