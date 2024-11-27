from pydantic import Field

from app.application.pydantic_model import BaseSchema


class AuthVerifyDTO(BaseSchema):
    code: str = Field(..., description="구글 로그인 후 받은 code 값")
