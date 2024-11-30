from fastapi import APIRouter, Query
from fastapi_restful.cbv import cbv
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.application.response import APIResponse

router = APIRouter(
    prefix="/_test",
    tags=["TestEndpoint"],
    responses={404: {"description": "Not found"}},
)
limiter = Limiter(key_func=get_remote_address)


@cbv(router)
class TestEndpoint:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @router.get("/google-callback")
    async def google_callback(
        self, state: str = Query(), code: str = Query()
    ) -> APIResponse[dict]:
        return APIResponse(
            message="Google Callback", data={"state": state, "code": code}
        )
