import aiogoogle.excs
from dependency_injector.wiring import inject, Provide

from fastapi import APIRouter, Depends
from fastapi_restful.cbv import cbv
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.application.authorization import get_current_user_id
from app.application.error import ErrorCode
from app.application.response import APIResponse, APIError, SuccessfulEntityResponse
from app.auth.dto.auth import AuthVerifyDTO
from app.auth.dto.email import EmailVerificationRequestDTO, EmailVerificationDTO
from app.auth.schema.string import AuthorizationURLSchema
from app.auth.schema.user import UserLoginResponse, UserLoginRequestType
from app.auth.services import AuthService
from app.containers import AppContainers
from app.email.services import EmailService
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

    @router.post("/email/requestCode", description="이메일 인증 코드를 요청합니다.")
    @inject
    async def request_email_verification_code(
        self,
        data: EmailVerificationRequestDTO,
        email_service: EmailService = Depends(Provide[AppContainers.email.service]),
        auth_service: AuthService = Depends(Provide[AppContainers.auth.service]),
        user_id: str = Depends(get_current_user_id),
    ) -> APIResponse[SuccessfulEntityResponse]:
        user = await User.find_one({User.sen_email: data.email})
        if user:
            raise APIError(
                status_code=400,
                error_code=ErrorCode.ALREADY_VERIFIED,
                message="이미 인증된 이메일입니다.",
            )
        success, code = await email_service.send_verify_email(data.email)
        if not success:
            raise APIError(
                status_code=500,
                error_code=ErrorCode.INTERNAL_SERVER_ERROR,
                message="이메일 전송에 실패했습니다. 서버 오류입니다.",
            )
        entity_id = await auth_service.create_verification_code(
            data.email, str(user_id), code
        )
        return APIResponse(
            message="인증 코드를 성공적으로 발급했습니다.",
            data=SuccessfulEntityResponse(entity_id=entity_id),
        )

    @router.post("/email/verify", description="이메일 인증 코드를 검증합니다.")
    @inject
    async def verify_email(
        self,
        data: EmailVerificationDTO,
        auth_service: AuthService = Depends(Provide[AppContainers.auth.service]),
    ) -> APIResponse[SuccessfulEntityResponse]:
        is_verified = await auth_service.verify_code(data.session_id, data.code)
        if not is_verified:
            raise APIError(
                status_code=400,
                error_code=ErrorCode.INVALID_VERIFICATION_CODE,
                message="인증 코드가 일치하지 않습니다.",
            )

        await auth_service.remove_verification_code(data.session_id)
        return APIResponse(
            message="이메일 인증에 성공했습니다.",
            data=SuccessfulEntityResponse(entity_id=data.session_id),
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
            import traceback
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
                sen_email=None,
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
