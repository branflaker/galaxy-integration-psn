import itertools
import json

import pytest
from galaxy.api.jsonrpc import InvalidParams

from plugin import COMMUNICATION_IDS_CACHE_KEY, GAME_INFO_CACHE_KEY
from psn_client import GAME_DETAILS_URL
from tests.async_mock import AsyncMock
from tests.test_data import GAMES, TITLE_TO_COMMUNICATION_ID, ENTITLEMENT_TO_GAME_INFO, TITLES, PS3_ENTITLEMENTS, ALL_GAMES, UNLOCKED_ACHIEVEMENTS

GAME_ID = GAMES[0].game_id


@pytest.fixture
def mock_client_get_owned_games(mocker):
    mocked = mocker.patch(
        "plugin.PSNClient.async_get_owned_games",
        new_callable=AsyncMock,
        return_value=TITLES
    )
    yield mocked
    mocked.assert_called_once_with()

@pytest.fixture
def mock_client_get_owned_ps3_entitlements(mocker):
    mocked = mocker.patch(
        "plugin.PSNClient.async_get_owned_ps3_entitlements",
        new_callable=AsyncMock,
        return_value=PS3_ENTITLEMENTS
    )
    yield mocked
    mocked.assert_called_once_with()


@pytest.fixture
def mock_get_game_communication_id_map(mocker):
    mocked = mocker.patch(
        "plugin.PSNClient.async_get_game_communication_id_map",
        new_callable=AsyncMock
    )
    yield mocked


@pytest.fixture
def mock_get_game_info(mocker):
    mocked = mocker.patch(
        "plugin.PSNClient.async_get_game_info",
        new_callable=AsyncMock
    )
    yield mocked


@pytest.fixture
def mock_client_get_earned_trophies(mocker):
    return mocker.patch(
        "plugin.PSNClient.async_get_earned_trophies",
        new_callable=AsyncMock,
    )

@pytest.fixture
def mock_persistent_cache(authenticated_plugin, mocker):
    return mocker.patch.object(type(authenticated_plugin), "persistent_cache", new_callable=mocker.PropertyMock)

def comm_id_getter():
    for x in [
        dict(itertools.islice(TITLE_TO_COMMUNICATION_ID.items(), 5, 10)),
        dict(itertools.islice(TITLE_TO_COMMUNICATION_ID.items(), 0, 5)),
        dict(itertools.islice(TITLE_TO_COMMUNICATION_ID.items(), 10, 11)),
    ]:
        yield x

def game_info_getter(entitlement):
    return ENTITLEMENT_TO_GAME_INFO[entitlement["entitlement_id"]]


@pytest.mark.asyncio
async def test_empty_cache_on_games_retrieval(
    authenticated_plugin,
    mock_client_get_owned_games,
    mock_get_game_communication_id_map,
    mock_client_get_owned_ps3_entitlements,
    mock_get_game_info
):
    mock_get_game_communication_id_map.side_effect = comm_id_getter()
    mock_get_game_info.side_effect = game_info_getter

    assert COMMUNICATION_IDS_CACHE_KEY not in authenticated_plugin.persistent_cache
    assert ALL_GAMES == await authenticated_plugin.get_owned_games()
    assert TITLE_TO_COMMUNICATION_ID == authenticated_plugin.persistent_cache[COMMUNICATION_IDS_CACHE_KEY]
    assert ENTITLEMENT_TO_GAME_INFO == authenticated_plugin.persistent_cache[GAME_INFO_CACHE_KEY]

    mock_calls_args = []
    for mock_call in mock_get_game_communication_id_map.call_args_list:
        args, kwargs = mock_call
        for a in args:
            mock_calls_args += a

    assert set(g.game_id for g in TITLES) == set(mock_calls_args)

    mock_info_calls_args = []
    for mock_call in mock_get_game_info.call_args_list:
        args, kwargs = mock_call
        for a in args:
            mock_info_calls_args.append(a)

    assert PS3_ENTITLEMENTS == mock_info_calls_args


@pytest.mark.asyncio
async def test_full_cache_on_games_retrieval(
    authenticated_plugin,
    mock_client_get_owned_games,
    mock_get_game_communication_id_map,
    mock_client_get_owned_ps3_entitlements,
    mock_get_game_info,
    mock_persistent_cache
):
    mock_persistent_cache.return_value = {
        COMMUNICATION_IDS_CACHE_KEY: TITLE_TO_COMMUNICATION_ID.copy(),
        GAME_INFO_CACHE_KEY: ENTITLEMENT_TO_GAME_INFO.copy()
    }
    assert ALL_GAMES == await authenticated_plugin.get_owned_games()
    assert TITLE_TO_COMMUNICATION_ID == authenticated_plugin.persistent_cache[COMMUNICATION_IDS_CACHE_KEY]
    assert ENTITLEMENT_TO_GAME_INFO == authenticated_plugin.persistent_cache[GAME_INFO_CACHE_KEY]
    assert not mock_get_game_communication_id_map.called
    assert not mock_get_game_info.called


@pytest.mark.asyncio
async def test_cache_miss_on_games_retrieval(
    authenticated_plugin,
    mock_client_get_owned_games,
    mock_get_game_communication_id_map,
    mock_client_get_owned_ps3_entitlements,
    mock_get_game_info,
    mock_persistent_cache
):
    border = int(len(TITLE_TO_COMMUNICATION_ID) / 2)
    info_border = int(len(ENTITLEMENT_TO_GAME_INFO) / 2)
    mock_persistent_cache.return_value = {
        COMMUNICATION_IDS_CACHE_KEY: dict(itertools.islice(TITLE_TO_COMMUNICATION_ID.items(), border)),
        GAME_INFO_CACHE_KEY: dict(itertools.islice(ENTITLEMENT_TO_GAME_INFO.items(), info_border))
    }
    not_cached = dict(itertools.islice(TITLE_TO_COMMUNICATION_ID.items(), border, len(TITLE_TO_COMMUNICATION_ID)))
    info_not_cached = dict(itertools.islice(ENTITLEMENT_TO_GAME_INFO.items(), info_border, len(ENTITLEMENT_TO_GAME_INFO)))

    mock_get_game_communication_id_map.return_value = {
        game_id: TITLE_TO_COMMUNICATION_ID[game_id] for game_id in not_cached
    }

    mock_get_game_info.side_effect = lambda entitlement: info_not_cached[entitlement["entitlement_id"]]

    assert ALL_GAMES == await authenticated_plugin.get_owned_games()
    assert TITLE_TO_COMMUNICATION_ID == authenticated_plugin.persistent_cache[COMMUNICATION_IDS_CACHE_KEY]
    assert ENTITLEMENT_TO_GAME_INFO == authenticated_plugin.persistent_cache[GAME_INFO_CACHE_KEY]

    mock_calls_args = []
    for mock_call in mock_get_game_communication_id_map.call_args_list:
        args, kwargs = mock_call
        for a in args:
            mock_calls_args += a

    assert set(not_cached) == set(mock_calls_args)

    mock_info_calls_args = []
    for mock_call in mock_get_game_info.call_args_list:
        args, kwargs = mock_call
        for a in args:
            mock_info_calls_args.append(a)

    assert set(info_not_cached) == set([e["entitlement_id"] for e in mock_info_calls_args])


@pytest.mark.asyncio
async def test_cache_miss_on_dlc_achievements_retrieval(
    authenticated_plugin,
    mock_client_get_earned_trophies,
    mock_get_game_communication_id_map
):
    dlc_id = "some_dlc_id"
    mapping = {dlc_id: []}
    mock_get_game_communication_id_map.return_value = mapping

    assert COMMUNICATION_IDS_CACHE_KEY not in authenticated_plugin.persistent_cache
    with pytest.raises(InvalidParams):
        await authenticated_plugin.get_unlocked_achievements(dlc_id)

    assert mapping == authenticated_plugin.persistent_cache[COMMUNICATION_IDS_CACHE_KEY]

    assert not mock_client_get_earned_trophies.called
    mock_get_game_communication_id_map.assert_called_once_with([dlc_id])


@pytest.mark.asyncio
async def test_cache_miss_on_game_achievements_retrieval(
    authenticated_plugin,
    mock_client_get_earned_trophies,
    mock_get_game_communication_id_map
):
    comm_ids = TITLE_TO_COMMUNICATION_ID[GAME_ID]
    mapping = {GAME_ID: comm_ids}
    mock_get_game_communication_id_map.return_value = mapping
    mock_client_get_earned_trophies.return_value = UNLOCKED_ACHIEVEMENTS

    assert "communication_ids" not in authenticated_plugin.persistent_cache

    assert UNLOCKED_ACHIEVEMENTS == await authenticated_plugin.get_unlocked_achievements(GAME_ID)

    assert mapping == authenticated_plugin.persistent_cache[COMMUNICATION_IDS_CACHE_KEY]

    mock_client_get_earned_trophies.assert_called_once_with(comm_ids[0])
    mock_get_game_communication_id_map.assert_called_once_with([GAME_ID])


@pytest.mark.asyncio
async def test_cached_on_dlc_achievements_retrieval(
    authenticated_plugin,
    mock_client_get_earned_trophies,
    mock_get_game_communication_id_map,
    mock_persistent_cache
):
    dlc_id = "some_dlc_id"
    mapping = {dlc_id: []}

    mock_persistent_cache.return_value = {COMMUNICATION_IDS_CACHE_KEY: mapping}
    with pytest.raises(InvalidParams):
        await authenticated_plugin.get_unlocked_achievements(dlc_id)

    assert mapping == authenticated_plugin.persistent_cache[COMMUNICATION_IDS_CACHE_KEY]

    assert not mock_get_game_communication_id_map.called
    assert not mock_client_get_earned_trophies.called


@pytest.mark.asyncio
async def test_cached_on_game_achievements_retrieval(
    authenticated_plugin,
    mock_client_get_earned_trophies,
    mock_get_game_communication_id_map,
    mock_persistent_cache
):
    comm_ids = TITLE_TO_COMMUNICATION_ID[GAME_ID]
    mapping = {GAME_ID: comm_ids}

    mock_client_get_earned_trophies.return_value = UNLOCKED_ACHIEVEMENTS
    mock_persistent_cache.return_value = {COMMUNICATION_IDS_CACHE_KEY: mapping.copy()}

    assert UNLOCKED_ACHIEVEMENTS == await authenticated_plugin.get_unlocked_achievements(GAME_ID)

    assert not mock_get_game_communication_id_map.called
    assert mapping == authenticated_plugin.persistent_cache[COMMUNICATION_IDS_CACHE_KEY]

    mock_client_get_earned_trophies.assert_called_once_with(comm_ids[0])


@pytest.mark.asyncio
async def test_cache_parsing(authenticated_plugin, mock_persistent_cache):
    mock_persistent_cache.return_value = {COMMUNICATION_IDS_CACHE_KEY: json.dumps(TITLE_TO_COMMUNICATION_ID)}
    authenticated_plugin.handshake_complete()
    assert authenticated_plugin.persistent_cache == {COMMUNICATION_IDS_CACHE_KEY: TITLE_TO_COMMUNICATION_ID}


@pytest.mark.asyncio
async def test_empty_cache_parsing(authenticated_plugin):
    authenticated_plugin.handshake_complete()
    assert authenticated_plugin.persistent_cache == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_response, mapping", [
    ({}, {GAME_ID: []}),
    ({"apps": []}, {GAME_ID: []}),
    ({"apps": [{"npTitleId": GAME_ID}]}, {GAME_ID: []}),
    ({"apps": [{"npTitleId": GAME_ID, "trophyTitles": []}]}, {GAME_ID: []}),
    ({"apps": [{"npTitleId": GAME_ID, "trophyTitles": [{}]}]}, {GAME_ID: []}),
    (
        {"apps": [{"trophyTitles": [{"npCommunicationId": "NPWR12345_00"}]}]},
        {GAME_ID: []}
    ),
    (
        {"apps": [{"npTitleId": None, "trophyTitles": [{"npCommunicationId": "NPWR23456_00"}]}]},
        {GAME_ID: []}
    ),
    (
        {"apps": [{"npTitleId": GAME_ID, "trophyTitles": [{"npCommunicationId": "NPWR34567_00"}]}]},
        {GAME_ID: ["NPWR34567_00"]}
    ),
    (
        {"apps": [
            {"npTitleId": "CUSA07917_00", "trophyTitles": [{"npCommunicationId": "NPWR12784_00"}]},
            {"npTitleId": "CUSA07719_00", "trophyTitles": []},
            {"npTitleId": "CUSA02000_00", "trophyTitles": [{"npCommunicationId": "NPWR10584_00"}]}
        ]},
        {
            "CUSA07917_00": ["NPWR12784_00"],
            "CUSA07719_00": [],
            "CUSA02000_00": ["NPWR10584_00"]
        }
    ),
    (
            {"apps": [{"npTitleId": GAME_ID, "trophyTitles": [
                {"npCommunicationId": "NPWR34567_00"},
                {"npCommunicationId": "NPWR10584_00"}
            ]}]},
            {GAME_ID: ["NPWR34567_00", "NPWR10584_00"]}
    )
])
async def test_get_game_communication_id(
    http_get,
    authenticated_psn_client,
    backend_response,
    mapping
):
    http_get.return_value = backend_response
    assert mapping == await authenticated_psn_client.async_get_game_communication_id_map(mapping.keys())
    http_get.assert_called_once_with(GAME_DETAILS_URL.format(game_id_list=",".join(mapping.keys())))
