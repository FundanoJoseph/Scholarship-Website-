from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True, extra="ignore")


class RegisterBody(ApiModel):
    full_name: str = Field(alias="fullName", min_length=2, max_length=160)
    student_id: str = Field(alias="studentId", min_length=7, max_length=7)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    program: str = Field(min_length=1, max_length=160)
    year_level: str = Field(alias="yearLevel", min_length=1, max_length=80)


class LoginBody(ApiModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class ResetRequestBody(ApiModel):
    email: str = Field(min_length=3, max_length=254)


class ResetConfirmBody(ApiModel):
    new_password: str = Field(alias="newPassword", min_length=8, max_length=128)


class ChangePasswordBody(ApiModel):
    current_password: str = Field(alias="currentPassword", min_length=1, max_length=128)
    new_password: str = Field(alias="newPassword", min_length=8, max_length=128)


class ProfilePatchBody(ApiModel):
    program: str = Field(min_length=1, max_length=160)
    year_level: str = Field(alias="yearLevel", min_length=1, max_length=80)


class AccountCreateBody(ApiModel):
    role: Literal["staff", "admin"]
    full_name: str = Field(alias="fullName", min_length=2, max_length=160)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class AccountUpdateBody(ApiModel):
    full_name: str = Field(alias="fullName", min_length=2, max_length=160)
    email: str = Field(min_length=3, max_length=254)
    role: Literal["student", "staff", "admin"]
    password: str | None = Field(default=None, max_length=128)


class TermUpdateBody(ApiModel):
    trimester: Literal["1st Trimester", "2nd Trimester", "3rd Trimester"]
    academic_year: str = Field(alias="academicYear", min_length=9, max_length=9)


class DocumentBody(ApiModel):
    name: str = Field(min_length=1, max_length=255)
    path: str = Field(min_length=1, max_length=1024)
    uploaded_at: str | None = Field(default=None, alias="uploadedAt")
    size_bytes: int = Field(alias="sizeBytes", ge=0, le=5242880)
    mime_type: str = Field(alias="mimeType", min_length=3, max_length=100)
    sample: bool = False


class ApplicationCreateBody(ApiModel):
    id: UUID | None = None
    program: str = Field(min_length=1, max_length=160)
    year_level: str = Field(alias="yearLevel", min_length=1, max_length=80)
    scholarship_type: str = Field(alias="scholarshipType", min_length=1, max_length=80)
    gwa: float = Field(ge=0, le=100)
    lowest_grade: float = Field(alias="lowestGrade", ge=0, le=100)
    has_failing_grade: bool = Field(alias="hasFailingGrade")
    has_incomplete_grade: bool = Field(alias="hasIncompleteGrade")
    has_dropped_grade: bool = Field(alias="hasDroppedGrade")
    documents: dict[str, DocumentBody]


class StatusUpdateBody(ApiModel):
    status: Literal["Submitted", "Under Evaluation", "Approved", "Rejected"]
    remarks: str = Field(default="", max_length=4000)
    discount_percent: float | None = Field(default=None, alias="discountPercent", ge=0, le=100)


class DiscountUpdateBody(ApiModel):
    discount_percent: float | None = Field(default=None, alias="discountPercent", ge=0, le=100)


class ReopenBody(ApiModel):
    reason: str = Field(min_length=1, max_length=4000)


class UploadUrlBody(ApiModel):
    path: str = Field(min_length=1, max_length=1024)
    application_id: UUID = Field(alias="applicationId")
    requirement_key: str = Field(alias="requirementKey", min_length=1, max_length=80)
    file_name: str = Field(alias="fileName", min_length=1, max_length=255)
    content_type: str = Field(alias="contentType", min_length=3, max_length=100)
    size_bytes: int = Field(alias="sizeBytes", ge=0, le=5242880)


class DeleteFilesBody(ApiModel):
    paths: list[str] = Field(min_length=1, max_length=20)
