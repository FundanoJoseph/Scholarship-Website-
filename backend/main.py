import logging
import os
import re
from datetime import datetime, timezone
from pathlib import PurePath
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.config import cookie_is_secure, cors_origins, origin_is_allowed, required_env
from backend.database import first, get_db, rows
from backend.schemas import (
    AccountCreateBody,
    AccountUpdateBody,
    ApplicationCreateBody,
    ChangePasswordBody,
    DeleteFilesBody,
    DiscountUpdateBody,
    LoginBody,
    ProfilePatchBody,
    RegisterBody,
    ReopenBody,
    ResetConfirmBody,
    ResetRequestBody,
    StatusUpdateBody,
    TermUpdateBody,
    UploadUrlBody,
)
from backend.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    password_needs_rehash,
    token_max_age,
    verify_password,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("scholarship_api")

API_PREFIX = "/api"
AUTH_COOKIE = "sams_access"
DOCUMENT_BUCKET = "scholarship-documents"
ACTIVE_APPLICATION_ROLES = {"staff", "admin"}
SCHOLARSHIP_TYPES = {
    "Academic Scholarship",
    "Entrance Exam Scholarship",
    "4Ps Scholarship",
    "Urdanetarian Scholarship",
    "RPSEA Scholarship",
    "SOC Scholarship",
    "BSA Scholarship",
    "New Program Scholarship",
}
DOCUMENT_REQUIREMENTS = {"copyOfGrades", "letterOfIntent", "notarizedAgreement"}
MIME_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}
PASSWORD_SPECIALS = set("!@#$%^&*()_+-=[]{};':\"\\|,.<>/?~`")

app = FastAPI(title="Scholarship Portal API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_origin_regex=r"^https?://(?:localhost|127\.0\.0\.1)(?::[0-9]{1,5})?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Requested-With"],
)


@app.middleware("http")
async def enforce_browser_origin(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.url.path.startswith(API_PREFIX) and request.method in {"POST", "PUT", "PATCH", "DELETE"} and origin:
        if not origin_is_allowed(origin):
            return JSONResponse(status_code=403, content={"error": "Request origin is not allowed."})
    return await call_next(request)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, error: HTTPException):
    detail = error.detail
    content = {"error": detail if isinstance(detail, str) else "Request failed."}
    return JSONResponse(status_code=error.status_code, content=content, headers=error.headers)


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, error: RequestValidationError):
    issues = [
        {"field": ".".join(str(part) for part in item.get("loc", ())), "message": item.get("msg", "Invalid value.")}
        for item in error.errors()
    ]
    return JSONResponse(status_code=422, content={"error": "Please check the submitted information.", "issues": issues})


def current_utc():
    return datetime.now(timezone.utc).isoformat()


def normalize_email(email):
    return str(email or "").strip().lower()


def validate_university_email(email):
    normalized = normalize_email(email)
    if not re.fullmatch(r"[^@\s]+@panpacificu\.edu\.ph", normalized):
        raise HTTPException(status_code=400, detail="Only @panpacificu.edu.ph email addresses are accepted.")
    return normalized


def validate_password(password):
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long.")
    if not any(character.isupper() for character in password):
        raise HTTPException(status_code=400, detail="Password must include at least 1 uppercase letter.")
    if not any(character.isdigit() for character in password):
        raise HTTPException(status_code=400, detail="Password must include at least 1 number.")
    if not any(character in PASSWORD_SPECIALS for character in password):
        raise HTTPException(status_code=400, detail="Password must include at least 1 special character.")


def validate_full_name(full_name):
    value = str(full_name or "").strip()
    if len(value) < 2 or len(value) > 160:
        raise HTTPException(status_code=400, detail="Full name must be between 2 and 160 characters.")
    if not re.fullmatch(r"[A-Za-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u00FF][A-Za-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u00FF .,'&-]*", value):
        raise HTTPException(status_code=400, detail="Full name must contain letters only. Numbers are not allowed.")
    return value


def validate_student_id(student_id):
    value = str(student_id or "").strip()
    if not re.fullmatch(r"[0-9]{7}", value):
        raise HTTPException(status_code=400, detail="Student ID must be exactly 7 digits.")
    return value


def normalize_academic_year(value):
    match = re.fullmatch(r"\s*(\d{4})\s*[-/–]\s*(\d{4})\s*", str(value or ""))
    if not match:
        raise HTTPException(status_code=400, detail="Academic year must be two years like 2026-2027.")
    start, end = int(match.group(1)), int(match.group(2))
    if end != start + 1:
        raise HTTPException(status_code=400, detail=f"The second year must follow the first (did you mean {start}-{start + 1}?).")
    if start < 2000 or start > 2100:
        raise HTTPException(status_code=400, detail="Please type a realistic academic year (between 2000 and 2100).")
    return f"{start}–{end}"


def safe_database_error(error):
    message = getattr(error, "message", str(error))
    if "users_active_email_unique" in message or "duplicate key value" in message:
        return HTTPException(status_code=409, detail="An account with this email already exists.")
    known_messages = (
        "Only an Admin can",
        "Only Authorized Staff or Admin can",
        "Only an approved or rejected application can be reopened.",
        "Only an approved application",
        "Only approved applications",
        "Applications from past terms are locked.",
        "Documents from past-term applications are locked.",
        "Only an Admin can reopen",
        "You cannot change your own role.",
        "You cannot delete your own account.",
        "There must be at least one Admin account.",
        "An account with this email already exists.",
        "Account not found.",
        "Application not found.",
        "This application belongs to",
        "An application cannot move",
        "Remarks are required",
        "A reason is required",
        "The system is already on",
        "No active academic term",
        "Applications can only be submitted for the current academic term.",
        "The second year must follow",
        "Please choose the",
        "Discount percentage must be",
    )
    if any(message.startswith(prefix) for prefix in known_messages):
        return HTTPException(status_code=400, detail=message)
    logger.error("Supabase request failed: %s", message)
    return HTTPException(status_code=500, detail="A database operation failed.")


def execute_or_raise(operation):
    try:
        return operation.execute()
    except HTTPException:
        raise
    except Exception as error:
        raise safe_database_error(error) from error


def public_user(user):
    return {
        "id": str(user["id"]),
        "role": user["role"],
        "fullName": user.get("full_name", ""),
        "email": user.get("email", ""),
        "studentId": user.get("student_id", ""),
        "program": user.get("program", ""),
        "yearLevel": user.get("year_level", ""),
        "createdAt": user.get("created_at"),
    }


def term_label(term):
    if not term:
        return ""
    return f"{term.get('trimester', '')}, AY {term.get('academic_year', '')}"


def clean_numeric(value):
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:g}"


def _active_user_by_id(user_id):
    response = execute_or_raise(
        get_db().table("users")
        .select("*")
        .eq("id", str(user_id))
        .is_("deleted_at", "null")
        .limit(1)
    )
    return first(response)


def get_current_user(request: Request):
    token = request.cookies.get(AUTH_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
    try:
        payload = decode_access_token(token)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail="Authentication is not configured.") from error
    except jwt.ExpiredSignatureError as error:
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.") from error
    except jwt.InvalidTokenError as error:
        raise HTTPException(status_code=401, detail="Your session is invalid. Please sign in again.") from error
    user = _active_user_by_id(payload.get("sub", ""))
    if not user or int(user.get("session_version", 0)) != int(payload.get("sv", 0)):
        raise HTTPException(status_code=401, detail="Your session is no longer valid. Please sign in again.")
    return user


def role_dependency(*roles):
    def dependency(user=Depends(get_current_user)):
        if user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")
        return user

    return dependency


require_student = role_dependency("student")
require_staff = role_dependency("staff", "admin")
require_admin = role_dependency("admin")


def set_auth_cookie(response: Response, user):
    try:
        token = create_access_token(user)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail="Authentication is not configured.") from error
    response.set_cookie(
        key=AUTH_COOKIE,
        value=token,
        max_age=token_max_age(),
        httponly=True,
        secure=cookie_is_secure(),
        samesite="lax",
        path="/",
    )


def clear_auth_cookie(response: Response):
    response.delete_cookie(
        key=AUTH_COOKIE,
        path="/",
        httponly=True,
        secure=cookie_is_secure(),
        samesite="lax",
    )


def find_user_by_email(email):
    response = execute_or_raise(
        get_db().table("users")
        .select("*")
        .eq("email", normalize_email(email))
        .is_("deleted_at", "null")
        .limit(1)
    )
    return first(response)


def write_audit(actor_id, action, entity_type, entity_id=None, target_id=None, details=None):
    row = {
        "actor_user_id": actor_id,
        "target_user_id": target_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "details": details or {},
    }
    execute_or_raise(get_db().table("audit_logs").insert(row))


def _signed_url_value(result):
    if isinstance(result, dict):
        return result.get("signed_url") or result.get("signedUrl") or result.get("signedURL") or result.get("url")
    return None


def _current_term():
    response = execute_or_raise(
        get_db().table("academic_terms")
        .select("*")
        .eq("is_current", True)
        .is_("deleted_at", "null")
        .limit(1)
    )
    return first(response)


def _serialize_applications(application_rows):
    if not application_rows:
        return []
    database = get_db()
    application_ids = [str(row["id"]) for row in application_rows]
    term_ids = list({str(row["term_id"]) for row in application_rows if row.get("term_id")})
    histories = rows(
        execute_or_raise(
            database.table("application_status_history")
            .select("*")
            .in_("application_id", application_ids)
            .order("changed_at", desc=False)
        )
    )
    terms = rows(execute_or_raise(database.table("academic_terms").select("*").in_("id", term_ids))) if term_ids else []
    files = rows(
        execute_or_raise(
            database.table("application_files")
            .select("*")
            .in_("application_id", application_ids)
            .is_("deleted_at", "null")
        )
    )
    histories_by_app = {}
    files_by_app = {}
    terms_by_id = {str(term["id"]): term for term in terms}
    for history in histories:
        histories_by_app.setdefault(str(history["application_id"]), []).append(
            {
                "status": history.get("to_status"),
                "date": history.get("changed_at"),
                "by": history.get("changed_by_name", ""),
                "remarks": history.get("remarks", ""),
                "eventType": history.get("event_type"),
                "previousStatus": history.get("from_status"),
            }
        )
    for file_row in files:
        files_by_app.setdefault(str(file_row["application_id"]), {})[file_row["requirement_key"]] = {
            "name": file_row.get("original_filename", ""),
            "path": file_row.get("storage_path", ""),
            "uploadedAt": file_row.get("uploaded_at"),
            "sample": bool(file_row.get("is_sample", False)),
            "sizeBytes": file_row.get("size_bytes", 0),
            "mimeType": file_row.get("mime_type", ""),
        }
    result = []
    for row in application_rows:
        app_id = str(row["id"])
        history = histories_by_app.get(app_id, [])
        term = terms_by_id.get(str(row.get("term_id")))
        result.append(
            {
                "id": app_id,
                "code": row.get("code", ""),
                "studentUserId": str(row.get("student_user_id", "")),
                "studentName": row.get("student_name", ""),
                "studentId": row.get("student_id", ""),
                "universityEmail": row.get("university_email", ""),
                "program": row.get("program", ""),
                "yearLevel": row.get("year_level", ""),
                "gwa": clean_numeric(row.get("gwa")),
                "lowestGrade": clean_numeric(row.get("lowest_grade")),
                "hasFailingGrade": bool(row.get("has_failing_grade", False)),
                "hasIncompleteGrade": bool(row.get("has_incomplete_grade", False)),
                "hasDroppedGrade": bool(row.get("has_dropped_grade", False)),
                "scholarshipType": row.get("scholarship_type", ""),
                "status": row.get("status", "Submitted"),
                "remarks": row.get("remarks", ""),
                "evaluatedBy": row.get("evaluated_by_name", ""),
                "discountPercent": clean_numeric(row.get("discount_percent")),
                "dateSubmitted": row.get("submitted_at"),
                "documents": files_by_app.get(app_id, {}),
                "term": term_label(term),
                "archived": bool(row.get("is_archived", False)),
                "deleted": bool(row.get("deleted_at")),
                "deletedAt": row.get("deleted_at"),
                "history": history,
            }
        )
    return result


def _application_by_id(application_id, include_deleted=False):
    query = get_db().table("applications").select("*").eq("id", str(application_id))
    if not include_deleted:
        query = query.is_("deleted_at", "null")
    response = execute_or_raise(query.limit(1))
    return first(response)


def _file_exists_in_storage(path):
    directory, _, leaf = path.rpartition("/")
    try:
        listed = get_db().storage.from_(DOCUMENT_BUCKET).list(directory, {"limit": 1000, "search": leaf})
    except Exception as error:
        raise safe_database_error(error) from error
    return any(item.get("name") == leaf for item in listed)


def _validate_document_path(user_id, application_id, requirement_key, file_name, path):
    parts = path.split("/")
    if len(parts) != 4 or parts[0] != str(user_id) or parts[1] != str(application_id) or parts[2] != requirement_key:
        raise HTTPException(status_code=400, detail="The document upload path is invalid.")
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", PurePath(file_name).name)
    if not safe_name or not parts[3].endswith("_" + safe_name) or parts[3] in {".", ".."}:
        raise HTTPException(status_code=400, detail="The document upload path is invalid.")
    expected_type = MIME_BY_EXTENSION.get(PurePath(file_name).suffix.lower())
    if not expected_type:
        raise HTTPException(status_code=400, detail="Unsupported file type. Accepted: PDF, JPG or PNG.")
    return expected_type


@app.get("/api/health")
def health_check():
    return {"ok": True}


@app.post("/api/auth/register")
def register(body: RegisterBody, response: Response):
    full_name = validate_full_name(body.full_name)
    student_id = validate_student_id(body.student_id)
    email = validate_university_email(body.email)
    validate_password(body.password)
    if not body.program.strip() or not body.year_level.strip():
        raise HTTPException(status_code=400, detail="Program and year level are required.")
    if find_user_by_email(email):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user_row = {
        "full_name": full_name,
        "email": email,
        "role": "student",
        "password_hash": hash_password(body.password),
        "student_id": student_id,
        "program": body.program.strip(),
        "year_level": body.year_level.strip(),
    }
    created = first(execute_or_raise(get_db().table("users").insert(user_row).select("*").single()))
    write_audit(created["id"], "account_registered", "user", created["id"], created["id"], {"role": "student"})
    set_auth_cookie(response, created)
    return {"user": public_user(created)}


@app.post("/api/auth/login")
def login(body: LoginBody, response: Response):
    user = find_user_by_email(body.email)
    if not user or not verify_password(user.get("password_hash", ""), body.password):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    if password_needs_rehash(user["password_hash"]):
        updated = first(
            execute_or_raise(
                get_db().table("users")
                .update({"password_hash": hash_password(body.password)})
                .eq("id", user["id"])
                .is_("deleted_at", "null")
                .select("*")
                .single()
            )
        )
        user = updated or user
    set_auth_cookie(response, user)
    return {"user": public_user(user)}


@app.post("/api/auth/logout")
def logout(response: Response):
    clear_auth_cookie(response)
    return {"ok": True}


@app.get("/api/auth/me")
def current_user(user=Depends(get_current_user)):
    return {"user": public_user(user)}


@app.post("/api/auth/password-reset/request")
def request_password_reset(body: ResetRequestBody):
    return {
        "error": "Self-service password reset is not enabled because no verified email delivery service is configured. Please contact an administrator."
    }


@app.post("/api/auth/password-reset/confirm")
def confirm_password_reset(body: ResetConfirmBody):
    validate_password(body.new_password)
    return {"error": "Self-service password reset is not enabled because no verified email delivery service is configured. Please contact an administrator."}


@app.patch("/api/users/me")
def update_own_profile(body: ProfilePatchBody, user=Depends(require_student)):
    response = execute_or_raise(
        get_db().table("users")
        .update({"program": body.program.strip(), "year_level": body.year_level.strip()})
        .eq("id", user["id"])
        .is_("deleted_at", "null")
        .select("*")
        .single()
    )
    return {"user": public_user(first(response))}


@app.post("/api/users/me/password")
def change_own_password(body: ChangePasswordBody, response: Response, user=Depends(get_current_user)):
    if not verify_password(user.get("password_hash", ""), body.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    validate_password(body.new_password)
    if body.current_password == body.new_password:
        raise HTTPException(status_code=400, detail="New password must be different from your current password.")
    updated = first(
        execute_or_raise(
            get_db().table("users")
            .update({"password_hash": hash_password(body.new_password), "session_version": int(user.get("session_version", 0)) + 1})
            .eq("id", user["id"])
            .is_("deleted_at", "null")
            .select("*")
            .single()
        )
    )
    write_audit(user["id"], "password_changed", "user", user["id"], user["id"])
    set_auth_cookie(response, updated)
    return {"ok": True}


@app.get("/api/admin/accounts")
def list_admin_accounts(user=Depends(require_admin)):
    response = execute_or_raise(
        get_db().table("users").select("*").is_("deleted_at", "null").order("created_at", desc=False)
    )
    return [public_user(row) for row in rows(response)]


@app.post("/api/admin/accounts")
def create_staff_account(body: AccountCreateBody, user=Depends(require_admin)):
    full_name = validate_full_name(body.full_name)
    email = validate_university_email(body.email)
    validate_password(body.password)
    if find_user_by_email(email):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    new_row = {
        "full_name": full_name,
        "email": email,
        "role": body.role,
        "password_hash": hash_password(body.password),
        "student_id": "",
        "program": "",
        "year_level": "",
    }
    created = first(execute_or_raise(get_db().table("users").insert(new_row).select("*").single()))
    write_audit(user["id"], "account_created", "user", created["id"], created["id"], {"role": body.role})
    return {"user": public_user(created)}


@app.put("/api/admin/accounts/{target_user_id}")
def update_account(target_user_id: UUID, body: AccountUpdateBody, response: Response, user=Depends(require_admin)):
    full_name = validate_full_name(body.full_name)
    email = validate_university_email(body.email)
    password_hash = None
    if body.password:
        validate_password(body.password)
        password_hash = hash_password(body.password)
    params = {
        "p_actor_user_id": str(user["id"]),
        "p_target_user_id": str(target_user_id),
        "p_full_name": full_name,
        "p_email": email,
        "p_role": body.role,
        "p_password_hash": password_hash,
    }
    result = execute_or_raise(get_db().rpc("admin_update_account", params))
    if str(target_user_id) == str(user["id"]):
        updated_user = _active_user_by_id(target_user_id)
        if updated_user:
            set_auth_cookie(response, updated_user)
    return {"account": getattr(result, "data", None)}


@app.delete("/api/admin/accounts/{target_user_id}")
def delete_account(target_user_id: UUID, user=Depends(require_admin)):
    params = {"p_actor_user_id": str(user["id"]), "p_target_user_id": str(target_user_id)}
    result = execute_or_raise(get_db().rpc("admin_delete_account", params))
    return getattr(result, "data", None) or {"deleted": True}


@app.get("/api/terms/current")
def get_current_term(user=Depends(get_current_user)):
    term = _current_term()
    if not term:
        raise HTTPException(status_code=503, detail="No active academic term is configured.")
    return {
        "id": str(term["id"]),
        "trimester": term["trimester"],
        "academicYear": term["academic_year"],
        "label": term_label(term),
    }


@app.put("/api/terms/current")
def update_current_term(body: TermUpdateBody, user=Depends(require_staff)):
    academic_year = normalize_academic_year(body.academic_year)
    params = {
        "p_actor_user_id": str(user["id"]),
        "p_trimester": body.trimester,
        "p_academic_year": academic_year,
    }
    result = execute_or_raise(get_db().rpc("set_current_term", params))
    data = getattr(result, "data", None)
    if isinstance(data, list) and data:
        return data[0]
    return data or {}


@app.get("/api/applications")
def list_student_applications(active: bool = False, user=Depends(require_student)):
    query = (
        get_db().table("applications")
        .select("*")
        .eq("student_user_id", user["id"])
        .is_("deleted_at", "null")
    )
    if active:
        query = query.eq("is_archived", False)
    response = execute_or_raise(query.order("submitted_at", desc=True))
    return _serialize_applications(rows(response))


@app.get("/api/applications/{application_id}")
def get_application(application_id: UUID, user=Depends(get_current_user)):
    application = _application_by_id(application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found.")
    if user["role"] == "student" and str(application["student_user_id"]) != str(user["id"]):
        raise HTTPException(status_code=403, detail="You do not have permission to view this application.")
    response = _serialize_applications([application])
    return response[0]


@app.get("/api/staff/applications")
def list_active_staff_applications(user=Depends(require_staff)):
    response = execute_or_raise(
        get_db().table("applications")
        .select("*")
        .is_("deleted_at", "null")
        .eq("is_archived", False)
        .order("submitted_at", desc=True)
    )
    return _serialize_applications(rows(response))


@app.get("/api/staff/applications/history")
def list_staff_application_history(user=Depends(require_staff)):
    response = execute_or_raise(
        get_db().table("applications").select("*").order("submitted_at", desc=True)
    )
    return _serialize_applications(rows(response))


@app.post("/api/applications")
def submit_application(body: ApplicationCreateBody, user=Depends(require_student)):
    application_id = str(body.id or uuid4())
    if body.scholarship_type not in SCHOLARSHIP_TYPES:
        raise HTTPException(status_code=400, detail="Please select a valid scholarship program.")
    if set(body.documents) != DOCUMENT_REQUIREMENTS:
        raise HTTPException(status_code=400, detail="All three required documents must be uploaded.")
    higher_threshold = body.scholarship_type in {"Academic Scholarship", "Entrance Exam Scholarship"}
    minimum_gwa = 87 if higher_threshold else 85
    minimum_grade = 85 if higher_threshold else 82
    if body.gwa < minimum_gwa:
        raise HTTPException(status_code=400, detail=f"This scholarship requires a GWA of at least {minimum_gwa}.")
    if body.lowest_grade < minimum_grade:
        raise HTTPException(status_code=400, detail=f"This scholarship requires no grade below {minimum_grade}.")
    if body.has_failing_grade or body.has_incomplete_grade or body.has_dropped_grade:
        raise HTTPException(status_code=400, detail="Eligibility requires no failing grade, INC, or dropped remarks.")
    term = _current_term()
    if not term:
        raise HTTPException(status_code=503, detail="No active academic term is configured.")
    file_rows = []
    paths = []
    for requirement_key, document in body.documents.items():
        expected_type = _validate_document_path(user["id"], application_id, requirement_key, document.name, document.path)
        if document.mime_type != expected_type:
            raise HTTPException(status_code=400, detail="The document file type does not match its filename.")
        if document.size_bytes <= 0:
            raise HTTPException(status_code=400, detail="Uploaded documents cannot be empty.")
        if not _file_exists_in_storage(document.path):
            raise HTTPException(status_code=400, detail=f"The {requirement_key} upload is missing. Please upload it again.")
        paths.append(document.path)
        file_rows.append(
            {
                "application_id": application_id,
                "requirement_key": requirement_key,
                "original_filename": PurePath(document.name).name,
                "storage_path": document.path,
                "mime_type": document.mime_type,
                "size_bytes": document.size_bytes,
                "uploaded_by_user_id": user["id"],
            }
        )
    application_record = {
        "id": application_id,
        "student_user_id": user["id"],
        "student_name": user["full_name"],
        "student_id": user.get("student_id", ""),
        "university_email": user["email"],
        "program": body.program.strip(),
        "year_level": body.year_level.strip(),
        "gwa": body.gwa,
        "lowest_grade": body.lowest_grade,
        "has_failing_grade": body.has_failing_grade,
        "has_incomplete_grade": body.has_incomplete_grade,
        "has_dropped_grade": body.has_dropped_grade,
        "scholarship_type": body.scholarship_type,
        "term_id": term["id"],
    }
    created_application = None
    try:
        created_application = first(
            execute_or_raise(get_db().table("applications").insert(application_record).select("*").single())
        )
        execute_or_raise(get_db().table("application_files").insert(file_rows))
        execute_or_raise(
            get_db().table("application_status_history").insert(
                {
                    "application_id": application_id,
                    "event_type": "submitted",
                    "from_status": None,
                    "to_status": "Submitted",
                    "changed_by_user_id": user["id"],
                    "changed_by_name": user["full_name"],
                    "remarks": "Application submitted.",
                }
            )
        )
        notifications = [
            {
                "user_id": user["id"],
                "application_id": application_id,
                "type": "status",
                "message": f"Your {body.scholarship_type} application ({created_application['code']}) was submitted successfully.",
            }
        ]
        staff_rows = rows(
            execute_or_raise(
                get_db().table("users")
                .select("id")
                .in_("role", ["staff", "admin"])
                .is_("deleted_at", "null")
            )
        )
        notifications.extend(
            {
                "user_id": staff["id"],
                "application_id": application_id,
                "type": "admin",
                "message": f"New application {created_application['code']} was submitted by {user['full_name']}.",
            }
            for staff in staff_rows
        )
        execute_or_raise(get_db().table("notifications").insert(notifications))
        execute_or_raise(
            get_db().table("users")
            .update({"program": body.program.strip(), "year_level": body.year_level.strip()})
            .eq("id", user["id"])
            .is_("deleted_at", "null")
        )
        return _serialize_applications([created_application])[0]
    except HTTPException:
        raise
    except Exception as error:
        if created_application:
            try:
                get_db().table("applications").update({"deleted_at": current_utc()}).eq("id", application_id).execute()
                get_db().table("application_files").update({"deleted_at": current_utc()}).eq("application_id", application_id).is_("deleted_at", "null").execute()
                get_db().table("notifications").update({"deleted_at": current_utc()}).eq("application_id", application_id).is_("deleted_at", "null").execute()
                get_db().storage.from_(DOCUMENT_BUCKET).remove(paths)
            except Exception:
                logger.exception("Could not roll back an incomplete application submission")
        raise safe_database_error(error) from error


@app.patch("/api/staff/applications/{application_id}/status")
def update_application_status(application_id: UUID, body: StatusUpdateBody, user=Depends(require_staff)):
    params = {
        "p_actor_user_id": str(user["id"]),
        "p_application_id": str(application_id),
        "p_status": body.status,
        "p_remarks": body.remarks.strip(),
        "p_discount_percent": body.discount_percent,
    }
    execute_or_raise(get_db().rpc("transition_application_status", params))
    application = _application_by_id(application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found.")
    return _serialize_applications([application])[0]


@app.patch("/api/staff/applications/{application_id}/discount")
def update_application_discount(application_id: UUID, body: DiscountUpdateBody, user=Depends(require_staff)):
    params = {
        "p_actor_user_id": str(user["id"]),
        "p_application_id": str(application_id),
        "p_discount_percent": body.discount_percent,
    }
    execute_or_raise(get_db().rpc("update_application_discount", params))
    application = _application_by_id(application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found.")
    return _serialize_applications([application])[0]


@app.post("/api/admin/applications/{application_id}/reopen")
def reopen_application(application_id: UUID, body: ReopenBody, user=Depends(require_admin)):
    params = {
        "p_admin_user_id": str(user["id"]),
        "p_application_id": str(application_id),
        "p_reason": body.reason.strip(),
    }
    execute_or_raise(get_db().rpc("reopen_application", params))
    application = _application_by_id(application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found.")
    return _serialize_applications([application])[0]


@app.delete("/api/staff/applications/{application_id}")
def delete_application(application_id: UUID, user=Depends(require_staff)):
    application = _application_by_id(application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found.")
    if application.get("is_archived"):
        raise HTTPException(status_code=400, detail="Applications from past terms are locked.")
    deleted_at = current_utc()
    updated = first(
        execute_or_raise(
            get_db().table("applications")
            .update({"deleted_at": deleted_at})
            .eq("id", str(application_id))
            .eq("is_archived", False)
            .is_("deleted_at", "null")
            .select("*")
            .single()
        )
    )
    if not updated:
        raise HTTPException(status_code=400, detail="Applications from past terms are locked.")
    execute_or_raise(
        get_db().table("notifications")
        .update({"deleted_at": deleted_at})
        .eq("application_id", str(application_id))
        .is_("deleted_at", "null")
    )
    write_audit(user["id"], "application_deleted", "application", application_id, details={"code": application.get("code", "")})
    return _serialize_applications([updated])[0]


@app.post("/api/files/upload-url")
def create_file_upload_url(body: UploadUrlBody, user=Depends(require_student)):
    if body.requirement_key not in DOCUMENT_REQUIREMENTS:
        raise HTTPException(status_code=400, detail="Invalid document requirement.")
    expected_type = _validate_document_path(user["id"], body.application_id, body.requirement_key, body.file_name, body.path)
    if body.content_type != expected_type:
        raise HTTPException(status_code=400, detail="The document file type does not match its filename.")
    if body.size_bytes <= 0:
        raise HTTPException(status_code=400, detail="Uploaded documents cannot be empty.")
    try:
        signed = get_db().storage.from_(DOCUMENT_BUCKET).create_signed_upload_url(body.path, {"upsert": "false"})
    except Exception as error:
        raise safe_database_error(error) from error
    signed_url = _signed_url_value(signed)
    if not signed_url:
        raise HTTPException(status_code=502, detail="Could not create a document upload URL.")
    return {"signedUrl": signed_url, "path": body.path}


@app.get("/api/files/download-url")
def create_file_download_url(path: str, user=Depends(get_current_user)):
    file_row = first(
        execute_or_raise(
            get_db().table("application_files")
            .select("*")
            .eq("storage_path", path)
            .is_("deleted_at", "null")
            .limit(1)
        )
    )
    if not file_row:
        raise HTTPException(status_code=404, detail="Document not found.")
    application = _application_by_id(file_row["application_id"])
    if not application:
        raise HTTPException(status_code=404, detail="Application not found.")
    if user["role"] == "student" and str(application["student_user_id"]) != str(user["id"]):
        raise HTTPException(status_code=403, detail="You do not have permission to view this document.")
    if user["role"] not in {"student", "staff", "admin"}:
        raise HTTPException(status_code=403, detail="You do not have permission to view this document.")
    try:
        signed = get_db().storage.from_(DOCUMENT_BUCKET).create_signed_url(path, 60)
    except Exception as error:
        raise safe_database_error(error) from error
    signed_url = _signed_url_value(signed)
    if not signed_url:
        raise HTTPException(status_code=502, detail="Could not create a document download URL.")
    return {"signedUrl": signed_url}


@app.post("/api/files/delete")
def delete_application_files(body: DeleteFilesBody, user=Depends(require_staff)):
    file_rows = rows(
        execute_or_raise(
            get_db().table("application_files")
            .select("id,storage_path")
            .in_("storage_path", body.paths)
            .is_("deleted_at", "null")
        )
    )
    if not file_rows:
        return {"deletedCount": 0}
    paths = [file_row["storage_path"] for file_row in file_rows]
    application_ids = list({str(file_row["application_id"]) for file_row in file_rows})
    applications = rows(
        execute_or_raise(
            get_db().table("applications")
            .select("id,is_archived")
            .in_("id", application_ids)
        )
    )
    if any(application.get("is_archived") for application in applications):
        raise HTTPException(status_code=400, detail="Documents from past-term applications are locked.")
    try:
        get_db().storage.from_(DOCUMENT_BUCKET).remove(paths)
    except Exception as error:
        raise safe_database_error(error) from error
    deleted_at = current_utc()
    execute_or_raise(
        get_db().table("application_files")
        .update({"deleted_at": deleted_at})
        .in_("id", [file_row["id"] for file_row in file_rows])
        .is_("deleted_at", "null")
    )
    return {"deletedCount": len(paths)}


@app.post("/api/files/discard")
def discard_pending_files(body: DeleteFilesBody, user=Depends(require_student)):
    for path in body.paths:
        parts = path.split("/")
        if len(parts) != 4 or parts[0] != str(user["id"]) or parts[2] not in DOCUMENT_REQUIREMENTS or parts[3] in {".", ".."}:
            raise HTTPException(status_code=400, detail="The document upload path is invalid.")
    registered = rows(
        execute_or_raise(
            get_db().table("application_files")
            .select("id")
            .in_("storage_path", body.paths)
        )
    )
    if registered:
        raise HTTPException(status_code=400, detail="A submitted document cannot be discarded here.")
    try:
        get_db().storage.from_(DOCUMENT_BUCKET).remove(body.paths)
    except Exception as error:
        raise safe_database_error(error) from error
    return {"discardedCount": len(body.paths)}


@app.get("/api/notifications")
def list_notifications(user=Depends(get_current_user)):
    response = execute_or_raise(
        get_db().table("notifications")
        .select("*")
        .eq("user_id", user["id"])
        .is_("deleted_at", "null")
        .order("created_at", desc=True)
        .limit(100)
    )
    return [
        {
            "id": str(row["id"]),
            "userId": str(row.get("user_id", "")),
            "appId": str(row["application_id"]) if row.get("application_id") else "",
            "type": row.get("type", "status"),
            "message": row.get("message", ""),
            "date": row.get("created_at"),
            "read": bool(row.get("is_read", False)),
        }
        for row in rows(response)
    ]


@app.get("/api/notifications/unread-count")
def count_unread_notifications(user=Depends(get_current_user)):
    response = execute_or_raise(
        get_db().table("notifications")
        .select("id", count="exact")
        .eq("user_id", user["id"])
        .eq("is_read", False)
        .is_("deleted_at", "null")
    )
    return {"count": getattr(response, "count", None) or 0}


@app.patch("/api/notifications/{notification_id}/read")
def mark_notification_read(notification_id: UUID, user=Depends(get_current_user)):
    response = execute_or_raise(
        get_db().table("notifications")
        .update({"is_read": True, "read_at": current_utc()})
        .eq("id", str(notification_id))
        .eq("user_id", user["id"])
        .is_("deleted_at", "null")
        .select("id")
    )
    if not rows(response):
        raise HTTPException(status_code=404, detail="Notification not found.")
    return {"ok": True}


@app.post("/api/notifications/read-all")
def mark_all_notifications_read(user=Depends(get_current_user)):
    execute_or_raise(
        get_db().table("notifications")
        .update({"is_read": True, "read_at": current_utc()})
        .eq("user_id", user["id"])
        .eq("is_read", False)
        .is_("deleted_at", "null")
    )
    return {"ok": True}
