import aiogoogle.excs
from beanie import WriteRules
from dependency_injector.wiring import inject, Provide

from fastapi import APIRouter, Depends
from fastapi_restful.cbv import cbv
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.application.authorization import (
    get_current_auth_user_entity,
)
from app.application.error import ErrorCode
from app.application.response import APIResponse, APIError
from app.bracket.dto.match import MatchTypeDTO
from app.bracket.schema.match import (
    BracketMatchListSchema,
    BracketMatchSchema,
    SavedBracketMatchListSchema,
)
from app.bracket.services import BracketService
from app.containers import AppContainers
from app.google.services import GoogleRequestService
from app.student.schema.group import StudentSchema

from app.user.entities import User
from app.bracket.entities import Match

router = APIRouter(
    prefix="/bracket",
    tags=["Bracket"],
    responses={404: {"description": "Not found"}},
)
limiter = Limiter(key_func=get_remote_address)


@cbv(router)
class BracketEndpoint:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @router.get("/list", description="사용자가 생성한 대진표 목록을 조회합니다.")
    @inject
    async def fetch_match_list(
        self, user: User = Depends(get_current_auth_user_entity)
    ) -> APIResponse[SavedBracketMatchListSchema]:
        user_entity = await User.get(user.id, fetch_links=True)
        return APIResponse(
            message="대진표 목록 조회 완료",
            data=SavedBracketMatchListSchema(
                matches=user_entity.matches,
            ),
        )

    @router.get("/match/{match_id}", description="대진표를 조회합니다.")
    @inject
    async def fetch_match(
        self,
        match_id: str,
        _user: User = Depends(get_current_auth_user_entity),
    ) -> APIResponse[Match]:
        try:
            match = await Match.get(match_id)
        except Exception as _:
            raise APIError(
                status_code=400,
                error_code=ErrorCode.INVALID_MATCH_ID,
                message="대진표 ID가 올바르지 않습니다.",
            )
        return APIResponse(message="대진표 조회 완료", data=match)

    @router.post(
        "/{sheet_id}/{group_name}/new", description="새로운 대진표를 생성합니다."
    )
    @inject
    async def create_new_bracket(
        self,
        sheet_id: str,
        group_name: str,
        data: MatchTypeDTO,
        user: User = Depends(get_current_auth_user_entity),
        google_service: GoogleRequestService = Depends(
            Provide[AppContainers.google.service]
        ),
        bracket_service: BracketService = Depends(
            Provide[AppContainers.bracket.service]
        ),
    ) -> APIResponse[BracketMatchListSchema]:
        google_credential = google_service.build_user_credentials(
            user.google_credential
        )
        try:
            spreadsheet_data = await google_service.fetch_spreadsheet_data(
                sheet_id, group_name, credential=google_credential
            )
            student_list = []
            for student_data in spreadsheet_data["values"][1:]:
                student_model_kwargs = {
                    "student_id": student_data[0],
                    "name": student_data[1],
                    "gender": {"남": "male", "여": "female"}[student_data[2]],
                }
                if len(student_data) > 3:
                    student_model_kwargs["level"] = student_data[3]
                else:
                    student_model_kwargs["level"] = None
                student_list.append(StudentSchema(**student_model_kwargs))
            matches = bracket_service.create_matches(student_list, data.match_type)
            match_response = []
            match_beanie_links = []
            for match in matches["matches"]:
                match: Match
                match_response.append(
                    BracketMatchSchema(
                        match_id=str(match.id),
                        match_type=match.match_type,
                        student1=match.student1,
                        student2=match.student2,
                    )
                )
                match_beanie_links.append(match)
            user.matches = user.matches + match_beanie_links
            await user.save(link_rule=WriteRules.WRITE)

            return APIResponse(
                message="대진표 생성 완료",
                data=BracketMatchListSchema(
                    matches=match_response,
                    unmatched_count=matches["unmatched_count"],
                ),
            )
        except aiogoogle.excs.HTTPError:
            raise APIError(
                status_code=400,
                error_code=ErrorCode.INVALID_SPREADSHEET_ID,
                message="스프레드시트 ID가 올바르지 않습니다.",
            )
