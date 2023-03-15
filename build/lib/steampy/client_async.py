import json
import urllib.parse as urlparse
from datetime import time, datetime
from typing import Optional, List

import aiohttp

from steampy.client import login_required
from steampy.exceptions import ApiException, InvalidApiKey, SevenDaysHoldException, LoginRequired, InvalidSteamTradeURL, \
    SteamInventoryNotPublic, SteamTradeError, SteamCookieNotAlive, SteamCannotTrade, AnotherSteamCannotTrade
from steampy.models import SteamUrl, GameOptions, TradeOfferState, Asset
from steampy.utils import merge_items_with_descriptions_from_inventory, merge_items_with_descriptions_from_offers, \
    get_description_key, merge_items_with_descriptions_from_offer, text_between, steam_id_to_account_id, \
    get_key_value_from_url, account_id_to_steam_id, check_trade_url, create_trade_offer_header, \
    create_trade_offer_params, create_offer_dict, find_trade_url


class SteamAsyncClient:
    _cookies: Optional[dict] = None
    _headers: dict = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": ""
    }

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self.was_login_executed = False

    async def login_by_cookies(self, cookie: dict) -> None:
        cookie[
            'webTradeEligibility'] = "%7B%22allowed%22%3A1%2C%22allowed_at_time%22%3A0%2C%22steamguard_required_days%22%3A15%2C%22new_device_cooldown_days%22%3A7%2C%22time_checked%22%3A" + str(
            datetime.now().timestamp()) + "000%7D"
        self._cookies = cookie
        self._cookies['Steam_Language'] = 'english'
        self.was_login_executed = True

    @login_required
    async def is_cookies_alive(self):
        async with aiohttp.ClientSession(cookies=self._cookies, headers=self._headers, connector=aiohttp.TCPConnector(ssl=False)) as sess:
            async with sess.get(SteamUrl.COMMUNITY_URL) as resp:
                res_text = await resp.text()
                if 'javascript:Logout()' not in res_text:
                    raise SteamCookieNotAlive()

    @login_required
    async def check_trade_url(self, steam_id: str, steam_trade_url: str) -> None:
        if not check_trade_url(steam_id, steam_trade_url):
            raise InvalidSteamTradeURL()

        async with aiohttp.ClientSession(cookies=self._cookies, headers=self._headers,connector=aiohttp.TCPConnector(ssl=False)) as sess:
            async with sess.get(steam_trade_url) as resp:
                res_text = await resp.text()
                if "inventory privacy is set to \"Private\"" in res_text:
                    raise SteamInventoryNotPublic()

                if "This Trade URL is no longer valid for sending a trade offer to" in res_text:
                    raise InvalidSteamTradeURL()

                if "You must have had Steam Guard enabled for at least 15 days before you can participate in a trade." in res_text:
                    raise SteamCannotTrade()

                if "This person has a limited account" in res_text:
                    raise AnotherSteamCannotTrade()

                if "Sorry, some kind of error has occurred:" in res_text:
                    raise SteamTradeError()

    @login_required
    async def check_our_trade_url(self, steam_id: str, steam_trade_url: str) -> str:
        # if not check_trade_url(steam_id, steam_trade_url):
        #     raise InvalidSteamTradeURL()

        async with aiohttp.ClientSession(cookies=self._cookies, headers=self._headers,connector=aiohttp.TCPConnector(ssl=False) ) as sess:
            url = "%s/profiles/%s/tradeoffers/privacy/" % (SteamUrl.COMMUNITY_URL, steam_id)
            async with sess.get(url) as resp:
                res_text = await resp.text()

                if 'javascript:Logout()' not in res_text:
                    raise SteamCookieNotAlive()

                new_trade_url = find_trade_url(res_text, steam_id)

                return new_trade_url

    async def api_call(self, request_method: str, interface: str, api_method: str, version: str,
                       params: dict = None) -> dict:
        url = '/'.join([SteamUrl.API_URL, interface, api_method, version])
        async with aiohttp.ClientSession(cookies=self._cookies, headers=self._headers, connector=aiohttp.TCPConnector(ssl=False)) as sess:
            if request_method == 'GET':
                resp = await sess.get(url, params=params)
            else:
                resp = await sess.post(url, data=params)

            if await self.is_invalid_api_key(await resp.text()):
                raise InvalidApiKey

            response = await resp.json()

            if not response:
                return {}

            return response

    @staticmethod
    async def is_invalid_api_key(response: str) -> bool:
        msg = 'Access is denied. Retrying will not help. Please verify your <pre>key=</pre> parameter'
        return msg in response

    @login_required
    async def get_partner_inventory(
            self,
            partner_steam_id: str,
            game: GameOptions,
            tradable: Optional[int] = None,
            count: int = 1000,
            language: str = "english",
            merge: bool = False,
    ) -> dict:
        url = '/'.join([SteamUrl.COMMUNITY_URL, 'inventory', partner_steam_id, game.app_id, game.context_id])
        params = {'l': language, 'count': count}

        if tradable:
            params["trading"] = tradable

        async with aiohttp.ClientSession(cookies=self._cookies, connector=aiohttp.TCPConnector(ssl=False)) as sess:
            async with sess.get(url, params=params) as resp:
                if resp.status == 403:
                    raise SteamInventoryNotPublic()
                response_dict = await resp.json()
        if 'success' in response_dict and response_dict['success'] != 1:
            raise ApiException('Success value should be 1.')
        if merge:
            return merge_items_with_descriptions_from_inventory(response_dict, game)
        return response_dict

    def _get_session_id(self) -> str:
        if 'sessionid' not in self._cookies:
            raise LoginRequired()

        return self._cookies['sessionid']

    async def get_trade_offers_summary(self) -> dict:
        params = {'key': self._api_key}
        return await self.api_call('GET', 'IEconService', 'GetTradeOffersSummary', 'v1', params)

    async def cancel_trade_offer_by_api(self, trade_offer_id: str):
        params = {'key': self._api_key,
                  "tradeofferid": trade_offer_id,
                  "format": "json"}
        await self.api_call('POST', 'IEconService', 'CancelTradeOffer', 'v1', params)

    async def decline_trade_offer_by_api(self, trade_offer_id: str):
        params = {'key': self._api_key,
                  "tradeofferid": trade_offer_id,
                  "format": "json"}
        await self.api_call('POST', 'IEconService', 'DeclineTradeOffer', 'v1', params)

    async def get_trade_offers_by_api(self, *, get_sent_offers: int = 0, get_received_offers: int = 0,
                                      get_descriptions: int = 0, active_only: int = 0,
                                      historical_only: int = 0, time_historical_cutoff: int) -> List[dict]:
        params = {
            "key": self._api_key,
            "get_sent_offers": get_sent_offers,
            "get_received_offers": get_received_offers,
            "get_descriptions": get_descriptions,
            "language": "english",
            "active_only": active_only,
            "historical_only": historical_only,
            "time_historical_cutoff": time_historical_cutoff
        }

        response = await self.api_call('GET', 'IEconService', 'GetTradeOffers', 'v1', params)

        result = []
        if "response" not in response:
            return result

        trade_offers_sent = response["response"].get("trade_offers_sent", [])
        result.extend(trade_offers_sent)

        trade_offers_received = response["response"].get("trade_offers_received", [])
        result.extend(trade_offers_received)

        return result

    async def get_trade_offers(self, merge: bool = True) -> dict:
        params = {'key': self._api_key,
                  'get_sent_offers': 1,
                  'get_received_offers': 1,
                  'get_descriptions': 1,
                  'language': 'english',
                  'active_only': 1,
                  'historical_only': 0,
                  'time_historical_cutoff': ''}
        response = await self.api_call('GET', 'IEconService', 'GetTradeOffers', 'v1', params)
        response = self._filter_non_active_offers(response)
        if merge:
            response = merge_items_with_descriptions_from_offers(response)
        return response

    @staticmethod
    def _filter_non_active_offers(offers_response):
        offers_received = offers_response['response'].get('trade_offers_received', [])
        offers_sent = offers_response['response'].get('trade_offers_sent', [])
        offers_response['response']['trade_offers_received'] = list(
            filter(lambda offer: offer['trade_offer_state'] == TradeOfferState.Active, offers_received))
        offers_response['response']['trade_offers_sent'] = list(
            filter(lambda offer: offer['trade_offer_state'] == TradeOfferState.Active, offers_sent))
        return offers_response

    async def get_trade_offer(self, trade_offer_id: str, merge: bool = True) -> dict:
        params = {'key': self._api_key,
                  'tradeofferid': trade_offer_id,
                  'language': 'english'}
        response = await self.api_call('GET', 'IEconService', 'GetTradeOffer', 'v1', params)

        if merge and "descriptions" in response['response']:
            descriptions = {get_description_key(offer): offer for offer in response['response']['descriptions']}
            offer = response['response']['offer']
            response['response']['offer'] = merge_items_with_descriptions_from_offer(offer, descriptions)
        return response

    async def get_trade_history(self,
                                max_trades=100,
                                start_after_time=None,
                                start_after_tradeid=None,
                                get_descriptions=True,
                                navigating_back=True,
                                include_failed=True,
                                include_total=True) -> dict:
        params = {
            'key': self._api_key,
            'max_trades': max_trades,
            'start_after_time': start_after_time,
            'start_after_tradeid': start_after_tradeid,
            'get_descriptions': get_descriptions,
            'navigating_back': navigating_back,
            'include_failed': include_failed,
            'include_total': include_total
        }
        response = await self.api_call('GET', 'IEconService', 'GetTradeHistory', 'v1', params)
        return response

    @login_required
    async def accept_trade_offer(self, trade_offer_id: str) -> dict:
        trade = await self.get_trade_offer(trade_offer_id)
        trade_offer_state = TradeOfferState(trade['response']['offer']['trade_offer_state'])
        if trade_offer_state is not TradeOfferState.Active:
            raise ApiException("Invalid trade offer state: {} ({})".format(trade_offer_state.name,
                                                                           trade_offer_state.value))
        partner = self._fetch_trade_partner_id(trade_offer_id)
        session_id = self._get_session_id()
        accept_url = SteamUrl.COMMUNITY_URL + '/tradeoffer/' + trade_offer_id + '/accept'
        params = {'sessionid': session_id,
                  'tradeofferid': trade_offer_id,
                  'serverid': '1',
                  'partner': partner,
                  'captcha': ''}
        headers = {'Referer': self._get_trade_offer_url(trade_offer_id)}
        async with aiohttp.ClientSession(cookies=self._cookies, connector=aiohttp.TCPConnector(ssl=False)) as sess:
            async with sess.post(accept_url, data=params, headers=headers) as resp:
                response = await resp.json()
        # if response.get('needs_mobile_confirmation', False):
        #     return self._confirm_transaction(trade_offer_id)
        return response

    # def _confirm_transaction(self, trade_offer_id: str) -> dict:
    #     confirmation_executor = ConfirmationExecutor(self.steam_guard['identity_secret'], self.steam_guard['steamid'],
    #                                                  self._session)
    #     return confirmation_executor.send_trade_allow_request(trade_offer_id)

    async def _fetch_trade_partner_id(self, trade_offer_id: str) -> str:
        url = self._get_trade_offer_url(trade_offer_id)
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as sess:
            async with sess.get(url) as resp:
                offer_response_text = await resp.text()

        if 'You have logged in from a new device. In order to protect the items' in offer_response_text:
            raise SevenDaysHoldException("Account has logged in a new device and can't trade for 7 days")
        return text_between(offer_response_text, "var g_ulTradePartnerSteamID = '", "';")

    @staticmethod
    def _get_trade_offer_url(trade_offer_id: str) -> str:
        return SteamUrl.COMMUNITY_URL + '/tradeoffer/' + trade_offer_id

    @login_required
    async def decline_trade_offer(self, trade_offer_id: str) -> dict:
        url = 'https://steamcommunity.com/tradeoffer/' + trade_offer_id + '/decline'
        async with aiohttp.ClientSession(cookies=self._cookies, connector=aiohttp.TCPConnector(ssl=False)) as sess:
            async with sess.post(url, data={'sessionid': self._get_session_id()}) as resp:
                response = await resp.json()

        return response

    @login_required
    async def cancel_trade_offer(self, trade_offer_id: str) -> dict:
        url = 'https://steamcommunity.com/tradeoffer/' + trade_offer_id + '/cancel'
        async with aiohttp.ClientSession(cookies=self._cookies, connector=aiohttp.TCPConnector(ssl=False)) as sess:
            async with sess.post(url, data={'sessionid': self._get_session_id()}) as resp:
                response = await resp.json()

        return response

    @login_required
    async def make_offer(self, items_from_me: List[Asset], items_from_them: List[Asset], partner_steam_id: str,
                         message: str = '') -> dict:
        offer = create_offer_dict(items_from_me, items_from_them, 2)
        session_id = self._get_session_id()
        url = SteamUrl.COMMUNITY_URL + '/tradeoffer/new/send'
        server_id = 1
        params = {
            'sessionid': session_id,
            'serverid': server_id,
            'partner': partner_steam_id,
            'tradeoffermessage': message,
            'json_tradeoffer': json.dumps(offer),
            'captcha': '',
            'trade_offer_create_params': '{}'
        }
        partner_account_id = steam_id_to_account_id(partner_steam_id)
        headers = {'Referer': SteamUrl.COMMUNITY_URL + '/tradeoffer/new/?partner=' + partner_account_id,
                   'Origin': SteamUrl.COMMUNITY_URL}
        async with aiohttp.ClientSession(cookies=self._cookies, connector=aiohttp.TCPConnector(ssl=False)) as sess:
            async with sess.post(url, data=params, headers=headers) as resp:
                response = await resp.json()

        # if response.get('needs_mobile_confirmation'):
        #     response.update(self._confirm_transaction(response['tradeofferid']))
        return response

    async def get_profile(self, steam_id: str) -> dict:
        params = {'steamids': steam_id, 'key': self._api_key}
        data = await self.api_call('GET', 'ISteamUser', 'GetPlayerSummaries', 'v0002', params)

        if 'response' in data and 'players' in data['response'] and len(data['response']['players']) > 0:
            return data['response']['players'][0]

        return {}

    async def get_friend_list(self, steam_id: str, relationship_filter: str = "all") -> dict:
        params = {
            'key': self._api_key,
            'steamid': steam_id,
            'relationship': relationship_filter
        }
        data = await self.api_call("GET", "ISteamUser", "GetFriendList", "v1", params)

        if 'friendslist' in data and 'friends' in data['friendslist']:
            return data['friendslist']['friends']

        return {}

    @login_required
    async def get_escrow_duration(self, trade_offer_url: str) -> int:
        headers = {'Referer': SteamUrl.COMMUNITY_URL + urlparse.urlparse(trade_offer_url).path,
                   'Origin': SteamUrl.COMMUNITY_URL}
        async with aiohttp.ClientSession(cookies=self._cookies, connector=aiohttp.TCPConnector(ssl=False)) as sess:
            async with sess.get(trade_offer_url, headers=headers) as resp:
                response = await resp.text()
        my_escrow_duration = int(text_between(response, "var g_daysMyEscrow = ", ";"))
        their_escrow_duration = int(text_between(response, "var g_daysTheirEscrow = ", ";"))
        return max(my_escrow_duration, their_escrow_duration)

    @login_required
    async def make_offer_with_url(self, items_from_me: List[Asset], items_from_them: List[Asset],
                                  trade_offer_url: str, message: str = '', case_sensitive: bool = True) -> dict:
        url = SteamUrl.COMMUNITY_URL + '/tradeoffer/new/send'
        session_id = self._get_session_id()
        params = create_trade_offer_params(items_from_me, items_from_them, trade_offer_url, session_id,
                                           message, 2, case_sensitive)
        headers = create_trade_offer_header(trade_offer_url)
        async with aiohttp.ClientSession(cookies=self._cookies, connector=aiohttp.TCPConnector(ssl=False)) as sess:
            async with sess.post(url, data=params, headers=headers) as resp:
                response = await resp.json()
        # if response.get('needs_mobile_confirmation'):
        #     response.update(self._confirm_transaction(response['tradeofferid']))
        return response
