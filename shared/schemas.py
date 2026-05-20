from pydantic import BaseModel, EmailStr
from typing import Optional, Any
from datetime import datetime
import uuid

class UserCreate(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: str
    email: EmailStr
    plan: str
    created_at: datetime

class Token(BaseModel):
    access_token: str
    token_type: str

class JobCreate(BaseModel):
    input_key: str
    mode: str = "horizontal_4k"  # "horizontal_4k" or "vertical_4k"

class JobResponse(BaseModel):
    id: str
    user_id: str
    input_key: str
    mode: str = "horizontal_4k"
    output_key: Optional[str] = None
    status: str
    params_json: Optional[Any] = None
    error: Optional[str] = None
    download_url: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None
