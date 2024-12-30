import os

from aiohttp import ClientSession
from app.env_validator import get_settings
from app.logger import use_logger

from aiogoogle import Aiogoogle, auth as aiogoogle_auth
from aiogoogle.auth.creds import UserCreds

from app.student.schema.group import StudentSchema
from app.user.entities.user import GoogleCredential
from app.utils.string import GoogleScope

settings = get_settings()
logger = use_logger("google_service")
SERVER_STATE = os.urandom(32).hex()
logger.debug(f"Google Oauth2 Server state: {SERVER_STATE}")

GOOGLE_DRIVE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
GOOGLE_DRIVE_SPREADSHEET_MIME_TYPE = "application/vnd.google-apps.spreadsheet"


class GoogleRequestService:
    def __init__(self) -> None:
        self.__server_state = SERVER_STATE

        self.__google_credentials = aiogoogle_auth.creds.ClientCreds(
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            scopes=[
                GoogleScope["userinfo.email"],
                GoogleScope["userinfo.profile"],
                GoogleScope["docs"],
                GoogleScope["drive"],
                GoogleScope["drive.readonly"],
                GoogleScope["spreadsheets"],
            ],
            redirect_uri=settings.GOOGLE_REDIRECT_URI,
        )
        self._google_client = Aiogoogle(
            client_creds=self.__google_credentials,
        )
        self._request = ClientSession()

    def get_server_state(self) -> str:
        return self.__server_state

    async def get_authorization_url(self) -> str:
        return self._google_client.oauth2.authorization_url(
            state=self.__server_state,
            access_type="offline",
            include_granted_scopes=True,
            prompt="consent",
        )

    async def fetch_user_credentials(self, code: str) -> dict:
        return await self._google_client.oauth2.build_user_creds(
            grant=code, client_creds=self.__google_credentials
        )

    async def fetch_user_info(self, user_credentials: dict) -> dict:
        return await self._google_client.oauth2.get_me_info(
            user_creds=user_credentials,
        )

    @staticmethod
    def build_user_credentials(google_credential: GoogleCredential) -> UserCreds:
        return UserCreds(
            access_token=google_credential.access_token,
            refresh_token=google_credential.refresh_token,
            expires_at=google_credential.access_token_expires_at,
        )

    async def fetch_drive_folder_id_by_name(
        self, folder_name: str, credential: UserCreds
    ) -> dict:
        drive_v3 = await self._google_client.discover("drive", "v3")
        query = f"name contains '{folder_name}' and mimeType='{GOOGLE_DRIVE_FOLDER_MIME_TYPE}' and trashed=false"
        response = await self._google_client.as_user(
            drive_v3.files.list(
                q=query,
                fields="files(id, name)",
                orderBy="name",
            ),
            user_creds=credential,
        )
        return response

    async def create_drive_folder(
        self, folder_name: str, credential: UserCreds
    ) -> dict:
        drive_v3 = await self._google_client.discover("drive", "v3")
        response = await self._google_client.as_user(
            drive_v3.files.create(
                json={"name": folder_name, "mimeType": GOOGLE_DRIVE_FOLDER_MIME_TYPE},
                fields="id",
            ),
            user_creds=credential,
        )
        return response

    async def fetch_spreadsheets_in_folder(
        self, folder_name: str, credential: UserCreds
    ) -> list[dict]:
        drive_v3 = await self._google_client.discover("drive", "v3")
        folder_query = (
            f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder'"
        )
        folder_response = await self._google_client.as_user(
            drive_v3.files.list(q=folder_query, fields="files(id)"),
            user_creds=credential,
        )

        if not folder_response.get("files"):
            return []

        folder_id = folder_response["files"][0]["id"]

        spreadsheet_query = f"'{folder_id}' in parents and mimeType='{GOOGLE_DRIVE_SPREADSHEET_MIME_TYPE}'"
        spreadsheet_response = await self._google_client.as_user(
            drive_v3.files.list(
                q=spreadsheet_query,
                fields="files(id, name, createdTime, modifiedTime)",
                orderBy="modifiedTime desc",
            ),
            user_creds=credential,
        )

        return spreadsheet_response.get("files", [])

    async def copy_drive_sheet(
        self, new_name: str, sheet_id: str, folder_id: str, credential: UserCreds
    ) -> dict:
        try:
            drive_v3 = await self._google_client.discover("drive", "v3")
            file_metadata = {
                "parents": [folder_id],
                "name": f"[Mixir 팀빌딩] {new_name}",
            }
            copy_response = await self._google_client.as_user(
                drive_v3.files.copy(
                    fileId=sheet_id, json=file_metadata, fields="id,name"
                ),
                user_creds=credential,
            )
            return copy_response
        except Exception as e:
            if "insufficientPermissions" in str(e):
                logger.error(
                    "스프레드시트에 대한 접근 권한이 없습니다. 공유 설정을 확인해주세요.",
                    e,
                )
            raise e

    async def edit_drive_sheet_name(
        self, sheet_id: str, new_name: str, credential: UserCreds
    ) -> dict:
        sheets_v4 = await self._google_client.discover("sheets", "v4")
        request_data = {
            "requests": [
                {
                    "updateSpreadsheetProperties": {
                        "properties": {"title": new_name},
                        "fields": "title",
                    }
                }
            ]
        }
        response = await self._google_client.as_user(
            sheets_v4.spreadsheets.batchUpdate(
                spreadsheetId=sheet_id, json=request_data
            ),
            user_creds=credential,
        )
        return response

    async def fetch_spreadsheets_by_id(
        self, sheet_id: str, credential: UserCreds
    ) -> list[dict]:
        sheets_v4 = await self._google_client.discover("sheets", "v4")
        spreadsheet_info = await self._google_client.as_user(
            sheets_v4.spreadsheets.get(
                spreadsheetId=sheet_id, fields="sheets.properties"
            ),
            user_creds=credential,
        )
        return spreadsheet_info

    async def fetch_spreadsheet_data(
        self,
        sheet_id: str,
        tab_name: str,
        credential: UserCreds,
    ) -> dict:
        """
        Fetch data from a specific sheet tab
        Handles sheet names with special characters including Korean
        """
        sheets_v4 = await self._google_client.discover("sheets", "v4")
        try:
            # Use sheet name without quotes, the API will handle escaping
            range_name = tab_name
            response = await self._google_client.as_user(
                sheets_v4.spreadsheets.values.get(
                    spreadsheetId=sheet_id,
                    range=range_name,  # Remove the quotes around tab_name
                    majorDimension="ROWS"
                ),
                user_creds=credential,
            )
            return response
        except aiogoogle.excs.HTTPError as e:
            logger.error(f"Error fetching spreadsheet data: {str(e)}")
            # If the direct approach fails, try with the sheet ID instead
            try:
                # Get the sheet ID for the given name
                spreadsheet_info = await self.fetch_spreadsheets_by_id(sheet_id, credential)
                sheet_id = None
                for sheet in spreadsheet_info["sheets"]:
                    if sheet["properties"]["title"] == tab_name:
                        sheet_id = sheet["properties"]["sheetId"]
                        break
                
                if sheet_id is None:
                    raise APIError(
                        status_code=404,
                        error_code=ErrorCode.SHEET_NOT_FOUND,
                        message="해당 시트를 찾을 수 없습니다.",
                    )
                
                # Use A1 notation with sheet ID
                response = await self._google_client.as_user(
                    sheets_v4.spreadsheets.values.get(
                        spreadsheetId=sheet_id,
                        range=f"'{tab_name}'!A1:Z1000",  # Use a wide range to get all data
                        majorDimension="ROWS"
                    ),
                    user_creds=credential,
                )
                return response
            except aiogoogle.excs.HTTPError as e:
                logger.error(f"Error fetching spreadsheet data with sheet ID: {str(e)}")
                raise APIError(
                    status_code=400,
                    error_code=ErrorCode.INVALID_SPREADSHEET_ID,
                    message="스프레드시트 데이터를 가져올 수 없습니다.",
                )

    async def add_student(
        self,
        sheet_id: str,
        tab_name: str,
        student_data: StudentSchema,
        credential: UserCreds,
    ) -> dict:
        sheets_v4 = await self._google_client.discover("sheets", "v4")
        response = await self._google_client.as_user(
            sheets_v4.spreadsheets.get(
                spreadsheetId=sheet_id, fields="sheets.properties"
            ),
            user_creds=credential,
        )

        worksheet_id = next(
            sheet["properties"]["sheetId"]
            for sheet in response["sheets"]
            if sheet["properties"]["title"] == tab_name
        )

        request_data = {
            "requests": [
                {
                    "appendCells": {
                        "sheetId": worksheet_id,
                        "rows": [
                            {
                                "values": [
                                    {
                                        "userEnteredValue": {
                                            "stringValue": str(student_data.student_id)
                                        },
                                        "userEnteredFormat": {
                                            "horizontalAlignment": "CENTER",
                                            "verticalAlignment": "MIDDLE",
                                        },
                                    },
                                    {
                                        "userEnteredValue": {
                                            "stringValue": student_data.name
                                        },
                                        "userEnteredFormat": {
                                            "horizontalAlignment": "CENTER",
                                            "verticalAlignment": "MIDDLE",
                                        },
                                    },
                                    {
                                        "userEnteredValue": {
                                            "stringValue": {
                                                "male": "남",
                                                "female": "여",
                                            }[student_data.gender]
                                        },
                                        "userEnteredFormat": {
                                            "horizontalAlignment": "CENTER",
                                            "verticalAlignment": "MIDDLE",
                                        },
                                    },
                                    {
                                        "userEnteredValue": {
                                            "stringValue": student_data.level
                                        },
                                        "userEnteredFormat": {
                                            "horizontalAlignment": "CENTER",
                                            "verticalAlignment": "MIDDLE",
                                        },
                                    },
                                ]
                            }
                        ],
                        "fields": "userEnteredValue,userEnteredFormat(horizontalAlignment,verticalAlignment)",
                    }
                }
            ]
        }
        response = await self._google_client.as_user(
            sheets_v4.spreadsheets.batchUpdate(
                spreadsheetId=sheet_id, json=request_data
            ),
            user_creds=credential,
        )
        return response

    async def create_group_sheet(
        self, sheet_id: str, name: str, credential: UserCreds
    ) -> dict:
        sheets_v4 = await self._google_client.discover("sheets", "v4")
        request_data = [{"addSheet": {"properties": {"title": name}}}]
        response = await self._google_client.as_user(
            sheets_v4.spreadsheets.batchUpdate(
                spreadsheetId=sheet_id, json={"requests": request_data}
            ),
            user_creds=credential,
        )
        worksheet_id = response["replies"][0]["addSheet"]["properties"]["sheetId"]
        request_data = {
            "requests": [
                {
                    "appendCells": {
                        "sheetId": worksheet_id,
                        "rows": [
                            {
                                "values": [
                                    {
                                        "userEnteredValue": {"stringValue": "번호"},
                                        "userEnteredFormat": {
                                            "horizontalAlignment": "CENTER",
                                            "verticalAlignment": "MIDDLE",
                                        },
                                    },
                                    {
                                        "userEnteredValue": {"stringValue": "이름"},
                                        "userEnteredFormat": {
                                            "horizontalAlignment": "CENTER",
                                            "verticalAlignment": "MIDDLE",
                                        },
                                    },
                                    {
                                        "userEnteredValue": {"stringValue": "성별"},
                                        "userEnteredFormat": {
                                            "horizontalAlignment": "CENTER",
                                            "verticalAlignment": "MIDDLE",
                                        },
                                    },
                                    {
                                        "userEnteredValue": {
                                            "stringValue": "수준",
                                        },
                                        "userEnteredFormat": {
                                            "horizontalAlignment": "CENTER",
                                            "verticalAlignment": "MIDDLE",
                                        },
                                    },
                                ]
                            }
                        ],
                        "fields": "userEnteredValue,userEnteredFormat(horizontalAlignment,verticalAlignment)",
                    }
                }
            ]
        }
        last_response = await self._google_client.as_user(
            sheets_v4.spreadsheets.batchUpdate(
                spreadsheetId=sheet_id,
                json=request_data,  # worksheet_id에서 sheet_id로 수정
            ),
            user_creds=credential,
        )

        return last_response

    async def delete_drive_file(
        self,
        file_id: str,
        credential: UserCreds,
    ) -> None:
        """Delete a file from Google Drive"""
        drive_v3 = await self._google_client.discover("drive", "v3")
        await self._google_client.as_user(
            drive_v3.files.delete(fileId=file_id),
            user_creds=credential,
        )

    async def delete_sheet(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        credential: UserCreds,
    ) -> dict:
        """Delete a specific sheet from a spreadsheet"""
        sheets_v4 = await self._google_client.discover("sheets", "v4")
        
        # First get the sheet ID
        response = await self.fetch_spreadsheets_by_id(spreadsheet_id, credential)
        sheet_id = None
        for sheet in response["sheets"]:
            if sheet["properties"]["title"] == sheet_name:
                sheet_id = sheet["properties"]["sheetId"]
                break
        
        if sheet_id is None:
            raise APIError(
                status_code=404,
                error_code=ErrorCode.SHEET_NOT_FOUND,
                message="해당 시트를 찾을 수 없습니다.",
            )
            
        request_data = {
            "requests": [
                {
                    "deleteSheet": {
                        "sheetId": sheet_id
                    }
                }
            ]
        }
        
        response = await self._google_client.as_user(
            sheets_v4.spreadsheets.batchUpdate(
                spreadsheetId=spreadsheet_id,
                json=request_data,
            ),
            user_creds=credential,
        )
        return response

    async def delete_student(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        row_index: int,
        credential: UserCreds,
    ) -> dict:
        """Delete a student row from a sheet"""
        sheets_v4 = await self._google_client.discover("sheets", "v4")
        
        # Get sheet ID first
        response = await self.fetch_spreadsheets_by_id(spreadsheet_id, credential)
        sheet_id = None
        for sheet in response["sheets"]:
            if sheet["properties"]["title"] == sheet_name:
                sheet_id = sheet["properties"]["sheetId"]
                break
        
        if sheet_id is None:
            raise APIError(
                status_code=404,
                error_code=ErrorCode.SHEET_NOT_FOUND,
                message="해당 시트를 찾을 수 없습니다.",
            )
        
        request_data = {
            "requests": [
                {
                    "deleteDimension": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "ROWS",
                            "startIndex": row_index,
                            "endIndex": row_index + 1
                        }
                    }
                }
            ]
        }
        
        response = await self._google_client.as_user(
            sheets_v4.spreadsheets.batchUpdate(
                spreadsheetId=spreadsheet_id,
                json=request_data,
            ),
            user_creds=credential,
        )
        return response
    
    async def update_student(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        row_index: int,
        student_data: StudentSchema,
        credential: UserCreds,
    ) -> dict:
        """
        Update a student's information in a specific sheet
        
        Args:
            spreadsheet_id (str): The ID of the spreadsheet
            sheet_name (str): Name of the sheet containing student data
            row_index (int): The row index of the student to update
            student_data (StudentSchema): Updated student information
            credential (UserCreds): Google API credentials
        
        Returns:
            dict: Response from the Google Sheets API
        """
        sheets_v4 = await self._google_client.discover("sheets", "v4")
        
        # Get sheet ID first
        response = await self.fetch_spreadsheets_by_id(spreadsheet_id, credential)
        sheet_id = None
        for sheet in response["sheets"]:
            if sheet["properties"]["title"] == sheet_name:
                sheet_id = sheet["properties"]["sheetId"]
                break
        
        if sheet_id is None:
            raise APIError(
                status_code=404,
                error_code=ErrorCode.SHEET_NOT_FOUND,
                message="해당 시트를 찾을 수 없습니다.",
            )
        
        # Prepare the cell data with formatting
        request_data = {
            "requests": [
                {
                    "updateCells": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": row_index,
                            "endRowIndex": row_index + 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": 4
                        },
                        "rows": [
                            {
                                "values": [
                                    {
                                        "userEnteredValue": {
                                            "stringValue": str(student_data.student_id)
                                        },
                                        "userEnteredFormat": {
                                            "horizontalAlignment": "CENTER",
                                            "verticalAlignment": "MIDDLE",
                                        },
                                    },
                                    {
                                        "userEnteredValue": {
                                            "stringValue": student_data.name
                                        },
                                        "userEnteredFormat": {
                                            "horizontalAlignment": "CENTER",
                                            "verticalAlignment": "MIDDLE",
                                        },
                                    },
                                    {
                                        "userEnteredValue": {
                                            "stringValue": {
                                                "male": "남",
                                                "female": "여",
                                            }[student_data.gender]
                                        },
                                        "userEnteredFormat": {
                                            "horizontalAlignment": "CENTER",
                                            "verticalAlignment": "MIDDLE",
                                        },
                                    },
                                    {
                                        "userEnteredValue": {
                                            "stringValue": student_data.level or ""
                                        },
                                        "userEnteredFormat": {
                                            "horizontalAlignment": "CENTER",
                                            "verticalAlignment": "MIDDLE",
                                        },
                                    },
                                ]
                            }
                        ],
                        "fields": "userEnteredValue,userEnteredFormat(horizontalAlignment,verticalAlignment)",
                    }
                }
            ]
        }
        
        try:
            response = await self._google_client.as_user(
                sheets_v4.spreadsheets.batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    json=request_data,
                ),
                user_creds=credential,
            )
            return response
        except aiogoogle.excs.HTTPError as e:
            logger.error(f"Error updating student data: {str(e)}")
            raise APIError(
                status_code=400,
                error_code=ErrorCode.INVALID_SPREADSHEET_ID,
                message="스프레드시트 데이터를 수정할 수 없습니다.",
            )
            
    async def rename_sheet(
        self,
        spreadsheet_id: str,
        current_sheet_name: str,
        new_sheet_name: str,
        credential: UserCreds,
    ) -> dict:
        """
        Rename a specific sheet in a spreadsheet
        
        Args:
            spreadsheet_id (str): The ID of the spreadsheet
            current_sheet_name (str): Current name of the sheet to rename
            new_sheet_name (str): New name for the sheet
            credential (UserCreds): Google API credentials
        
        Returns:
            dict: Response from the Google Sheets API
        """
        sheets_v4 = await self._google_client.discover("sheets", "v4")
        
        # First get the sheet ID
        response = await self.fetch_spreadsheets_by_id(spreadsheet_id, credential)
        sheet_id = None
        for sheet in response["sheets"]:
            if sheet["properties"]["title"] == current_sheet_name:
                sheet_id = sheet["properties"]["sheetId"]
                break
        
        if sheet_id is None:
            raise APIError(
                status_code=404,
                error_code=ErrorCode.SHEET_NOT_FOUND,
                message="해당 시트를 찾을 수 없습니다.",
            )
        
        # Check if new name already exists
        for sheet in response["sheets"]:
            if sheet["properties"]["title"] == new_sheet_name:
                raise APIError(
                    status_code=400,
                    error_code=ErrorCode.SHEET_NAME_EXISTS,
                    message="동일한 이름의 시트가 이미 존재합니다.",
                )
                
        request_data = {
            "requests": [
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": sheet_id,
                            "title": new_sheet_name
                        },
                        "fields": "title"
                    }
                }
            ]
        }
        
        try:
            response = await self._google_client.as_user(
                sheets_v4.spreadsheets.batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    json=request_data,
                ),
                user_creds=credential,
            )
            return response
        except aiogoogle.excs.HTTPError as e:
            logger.error(f"Error renaming sheet: {str(e)}")
            raise APIError(
                status_code=400,
                error_code=ErrorCode.INVALID_SPREADSHEET_ID,
                message="시트 이름을 변경할 수 없습니다.",
            )
            
    async def share_spreadsheet(
        self,
        spreadsheet_id: str,
        email: str,
        credential: UserCreds,
    ) -> dict:
        """
        Share a spreadsheet with a specific Gmail user as an editor
        
        Args:
            spreadsheet_id (str): The ID of the spreadsheet
            email (str): Gmail address to share with
            credential (UserCreds): Google API credentials
        
        Returns:
            dict: Response from the Google Drive API
        """
        drive_v3 = await self._google_client.discover("drive", "v3")
        
        # Prepare the permission data
        permission_data = {
            "type": "user",
            "role": "writer",
            "emailAddress": email,
            # Optional notification settings
            "sendNotificationEmail": True,
            "emailMessage": "Mixir 팀빌딩 스프레드시트가 공유되었습니다."
        }
        
        try:
            response = await self._google_client.as_user(
                drive_v3.permissions.create(
                    fileId=spreadsheet_id,
                    json=permission_data,
                    fields="id",
                    supportsAllDrives=True
                ),
                user_creds=credential,
            )
            return response
        except aiogoogle.excs.HTTPError as e:
            logger.error(f"Error sharing spreadsheet: {str(e)}")
            raise e