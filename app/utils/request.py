from typing import Any
from aiohttp import ClientSession, ClientResponse


class BaseRequest:
    def __init__(self, session: ClientSession | None = None) -> None:
        self.session: ClientSession | None = session

    async def request(
        self,
        url: str,
        method: str,
        **kwargs: Any,
    ) -> ClientResponse:
        if not self.session or self.session.closed:
            self.session = ClientSession()

        resp = await self.session.request(method, url, **kwargs)

        return resp

    async def post(self, url: str, **kwargs: Any) -> ClientResponse:
        if not self.session or self.session.closed:
            self.session = ClientSession()

        return await self.request(url, "POST", **kwargs)

    async def get(self, url: str, **kwargs: Any) -> ClientResponse:
        if not self.session or self.session.closed:
            self.session = ClientSession()

        return await self.request(url, "GET", **kwargs)
