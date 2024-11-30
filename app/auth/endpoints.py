import aiogoogle.excs
import traceback

from dependency_injector.wiring import inject, Provide

from fastapi import APIRouter, Depends
from fastapi_restful.cbv import cbv
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.application.error import ErrorCode
from app.application.response import APIResponse, APIError
from app.application.utils import validate_email
from app.auth.dto.auth import AuthVerifyDTO
from app.auth.schema.string import AuthorizationURLSchema
from app.auth.schema.user import UserLoginResponse, UserLoginRequestType
from app.auth.services import AuthService
from app.containers import AppContainers
from app.google.services import GoogleRequestService

from app.user.entities import User
from app.user.entities.user import GoogleCredential
from app.logger import use_logger

logger = use_logger("auth_endpoint")

router = APIRouter(
    prefix="/auth",
    tags=["Authorization"],
    responses={404: {"description": "Not found"}},
)
limiter = Limiter(key_func=get_remote_address)


@cbv(router)
class AuthEndpoint:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @router.get(
        "/authorization-url",
        description="구글 로그인 URL을 반환합니다.",
    )
    @inject
    async def get_authorization_url(
        self,
        google_service: GoogleRequestService = Depends(
            Provide[AppContainers.google.service]
        ),
    ) -> APIResponse[AuthorizationURLSchema]:
        authorization_url = await google_service.get_authorization_url()
        return APIResponse(
            message="구글 로그인 URL을 성공적으로 반환했습니다.",
            data=AuthorizationURLSchema(url=authorization_url),
        )

    @router.post(
        "/login",
        description="구글 로그인 후 사용자 정보를 반환합니다. (안되어있으면 자동가입)",
    )
    @inject
    async def login(
        self,
        data: AuthVerifyDTO,
        google_service: GoogleRequestService = Depends(
            Provide[AppContainers.google.service]
        ),
        auth_service: AuthService = Depends(Provide[AppContainers.auth.service]),
    ) -> APIResponse[UserLoginResponse]:
        try:
            user_credential_data = await google_service.fetch_user_credentials(
                data.code
            )
        except aiogoogle.excs.HTTPError:
            logger.error(
                f"Invalid google code: {data.code}, {traceback.format_exc()}",
            )
            raise APIError(
                status_code=400,
                error_code=ErrorCode.INVALID_GOOGLE_CODE,
                message="구글 코드가 유효하지 않습니다.",
            )
        user_info = await google_service.fetch_user_info(user_credential_data)
        odm_user = await User.find({"email": user_info["email"]}).first_or_none()
        if validate_email(user_info["email"]):
            raise APIError(
                status_code=403,
                error_code=ErrorCode.ACCESS_DENIED,
                message="이 리소스에 접근할 권한이 없습니다.",
            )
        if not odm_user:
            odm_user = User(
                email=user_info["email"],
                name=user_info["name"],
                picture=user_info["picture"],
                google_credential=GoogleCredential(
                    access_token=user_credential_data.get("access_token"),
                    refresh_token=user_credential_data.get("refresh_token"),
                    access_token_expires_at=user_credential_data.get("expires_at"),
                ),
            )
            await odm_user.create()
            access_token = await auth_service.create_access_token(str(odm_user.id))
            user_credential = google_service.build_user_credentials(
                odm_user.google_credential
            )
            response = await google_service.fetch_drive_folder_id_by_name(
                "Mixir-팀빌딩", credential=user_credential
            )
            if len(response["files"]) == 0:
                await google_service.create_drive_folder(
                    "Mixir-팀빌딩", credential=user_credential
                )

            return APIResponse(
                message="회원가입 완료. 이메일 인증 필요.",
                data=UserLoginResponse(
                    request_type=UserLoginRequestType.SIGNUP, access_token=access_token
                ),
            )
        else:
            new_google_credential = GoogleCredential(
                access_token=user_credential_data.get("access_token"),
                refresh_token=user_credential_data.get(
                    "refresh_token", odm_user.google_credential.refresh_token
                ),
                access_token_expires_at=user_credential_data.get("expires_at"),
            )
            await odm_user.set({User.google_credential: new_google_credential})
            access_token = await auth_service.create_access_token(str(odm_user.id))
            return APIResponse(
                message="로그인 완료.",
                data=UserLoginResponse(
                    request_type=UserLoginRequestType.LOGIN, access_token=access_token
                ),
            )
