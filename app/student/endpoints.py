import traceback

import aiogoogle.excs
from dependency_injector.wiring import inject, Provide

from fastapi import APIRouter, Depends, Body
from fastapi_restful.cbv import cbv
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.application.authorization import (
    get_current_user_entity,
    get_current_auth_user_entity,
)
from app.application.error import ErrorCode
from app.application.response import APIResponse, APIError, SuccessfulEntityResponse
from app.containers import AppContainers
from app.google.services import GoogleRequestService
from app.student.dto.add import AddStudentDTO
from app.student.schema.group import (
    GroupListSchema,
    GroupSchema,
    StudentListSchema,
    StudentSchema,
)

from app.user.entities import User

from app.env_validator import get_settings
from app.logger import use_logger

settings = get_settings()
logger = use_logger("student")

router = APIRouter(
    prefix="/student",
    tags=["Student"],
    responses={404: {"description": "Not found"}},
)
limiter = Limiter(key_func=get_remote_address)


@cbv(router)
class StudentEndpoint:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @router.get("/list", description="그룹 목록을 반환합니다.")
    @inject
    async def get_group_list(
        self,
        user: User = Depends(get_current_auth_user_entity),
        google_service: GoogleRequestService = Depends(
            Provide[AppContainers.google.service]
        ),
    ) -> APIResponse[GroupListSchema]:

        google_credential = google_service.build_user_credentials(
            user.google_credential
        )
        spreadsheet_list = await google_service.fetch_spreadsheets_in_folder(
            "Mixir-팀빌딩", credential=google_credential
        )
        return APIResponse(
            message="그룹 목록 조회 완료",
            data=GroupListSchema(
                groups=[
                    GroupSchema(
                        group_id=group_data["id"],
                        name=group_data["name"].replace("[Mixir 팀빌딩] ", ""),
                    )
                    for group_data in spreadsheet_list
                ]
            ),
        )

    @router.post("/create", description="새 그룹 (파일) 만들기")
    @inject
    async def create_new_group(
        self,
        name: str = Body(description="그룹 이름 (파일명)", embed=True),
        user: User = Depends(get_current_user_entity),
        google_service: GoogleRequestService = Depends(
            Provide[AppContainers.google.service]
        ),
    ) -> APIResponse[SuccessfulEntityResponse]:
        google_credential = google_service.build_user_credentials(
            user.google_credential
        )
        folders = await google_service.fetch_drive_folder_id_by_name(
            "Mixir-팀빌딩", credential=google_credential
        )
        folder_id = folders["files"][0]["id"]
        copy_response = await google_service.copy_drive_sheet(
            sheet_id=settings.SHEET_TEMPLATE_ID,
            new_name=name,
            folder_id=folder_id,
            credential=google_credential,
        )
        return APIResponse(
            message="파일 생성 완료",
            data=SuccessfulEntityResponse(entity_id=copy_response["id"]),
        )

    @router.get("/{sheet_id}/groups", description="그룹 정보 조회")
    @inject
    async def get_group_info(
        self,
        sheet_id: str,
        user: User = Depends(get_current_auth_user_entity),
        google_service: GoogleRequestService = Depends(
            Provide[AppContainers.google.service]
        ),
    ) -> APIResponse[GroupListSchema]:
        google_credential = google_service.build_user_credentials(
            user.google_credential
        )
        try:
            spreadsheet_list = await google_service.fetch_spreadsheets_by_id(
                sheet_id, credential=google_credential
            )
            return APIResponse(
                message="그룹 조회 완료",
                data=GroupListSchema(
                    groups=[
                        GroupSchema(
                            group_id=str(group_data["properties"]["sheetId"]),
                            name=group_data["properties"]["title"],
                        )
                        for group_data in spreadsheet_list["sheets"]
                    ]
                ),
            )
        except aiogoogle.excs.HTTPError:
            raise APIError(
                status_code=400,
                error_code=ErrorCode.INVALID_SPREADSHEET_ID,
                message="스프레드시트 ID가 올바르지 않습니다.",
            )

    @router.post("/{sheet_id}/edit", description="팀 정보 수정하기")
    async def edit_file_info(
        self,
        sheet_id: str,
        name: str = Body(description="팀 이름", embed=True),
        user: User = Depends(get_current_auth_user_entity),
        google_service: GoogleRequestService = Depends(
            Provide[AppContainers.google.service]
        ),
    ) -> APIResponse[SuccessfulEntityResponse]:
        try:
            google_credential = google_service.build_user_credentials(
                user.google_credential
            )
            response = await google_service.edit_drive_sheet_name(
                sheet_id, name, credential=google_credential
            )
            logger.debug(f"edit_file_info response[id={sheet_id}]", response)
        except aiogoogle.excs.HTTPError:
            logger.error(
                f"[EDIT_FILE_INFO Error] user.id={user.id}", traceback.format_exc()
            )
            raise APIError(
                status_code=400,
                error_code=ErrorCode.INVALID_SPREADSHEET_ID,
                message="스프레드시트 ID가 올바르지 않습니다.",
            )
        return APIResponse(
            message="파일 수정 완료",
            data=SuccessfulEntityResponse(entity_id=sheet_id),
        )

    @router.post("/{sheet_id}/groups", description="하위 그룹 만들기")
    @inject
    async def create_group(
        self,
        sheet_id: str,
        name: str = Body(description="그룹 이름 (시트명)", embed=True),
        user: User = Depends(get_current_auth_user_entity),
        google_service: GoogleRequestService = Depends(
            Provide[AppContainers.google.service]
        ),
    ) -> APIResponse[SuccessfulEntityResponse]:
        google_credential = google_service.build_user_credentials(
            user.google_credential
        )
        response = await google_service.create_group_sheet(
            sheet_id, name, credential=google_credential
        )
        return APIResponse(
            message="그룹 생성 완료",
            data=SuccessfulEntityResponse(entity_id=response["spreadsheetId"]),
        )

    @router.get("/{sheet_id}/{group_name}/members", description="그룹 멤버 조회")
    @inject
    async def get_group_members(
        self,
        sheet_id: str,
        group_name: str,
        user: User = Depends(get_current_auth_user_entity),
        google_service: GoogleRequestService = Depends(
            Provide[AppContainers.google.service]
        ),
    ) -> APIResponse[StudentListSchema]:
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
            return APIResponse(
                message="그룹 조회 완료",
                data=StudentListSchema(
                    students=student_list,
                ),
            )
        except aiogoogle.excs.HTTPError:
            raise APIError(
                status_code=400,
                error_code=ErrorCode.INVALID_SPREADSHEET_ID,
                message="스프레드시트 ID가 올바르지 않습니다.",
            )

    @router.post("/{sheet_id}/{group_name}/members", description="그룹 멤버 추가")
    @inject
    async def add_group_member(
        self,
        sheet_id: str,
        group_name: str,
        data: AddStudentDTO,
        user: User = Depends(get_current_auth_user_entity),
        google_service: GoogleRequestService = Depends(
            Provide[AppContainers.google.service]
        ),
    ) -> APIResponse[SuccessfulEntityResponse]:
        google_credential = google_service.build_user_credentials(
            user.google_credential
        )
        try:
            spreadsheet_data = await google_service.fetch_spreadsheet_data(
                sheet_id, group_name, credential=google_credential
            )
            next_student_id = len(spreadsheet_data["values"][1:]) + 1
            response = await google_service.add_student(
                sheet_id,
                group_name,
                StudentSchema(
                    student_id=str(next_student_id),
                    name=data.name,
                    gender=data.gender,
                    level=data.level,
                ),
                credential=google_credential,
            )
            return APIResponse(
                message="그룹 조회 완료",
                data=SuccessfulEntityResponse(entity_id=response["spreadsheetId"]),
            )
        except aiogoogle.excs.HTTPError:
            logger.error(traceback.format_exc())
            raise APIError(
                status_code=400,
                error_code=ErrorCode.INVALID_SPREADSHEET_ID,
                message="스프레드시트 ID가 올바르지 않습니다.",
            )
