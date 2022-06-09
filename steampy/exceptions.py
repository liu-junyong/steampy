class SevenDaysHoldException(Exception):
    pass


class TooManyRequests(Exception):
    pass


class ApiException(Exception):
    pass


class LoginRequired(Exception):
    pass


class InvalidCredentials(Exception):
    pass


class InvalidApiKey(InvalidCredentials):
    pass


class CaptchaRequired(Exception):
    pass


class ConfirmationExpected(Exception):
    pass


class SteamTradeError(Exception):
    pass


class InvalidSteamTradeURL(SteamTradeError):
    pass


class SteamInventoryNotPublic(SteamTradeError):
    pass


class SteamCannotTrade(SteamTradeError):
    pass


class SteamCookieNotAlive(Exception):
    pass
