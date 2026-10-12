from functools import lru_cache

from fastapi import HTTPException
from supabase import Client, create_client

from backend.config import required_env


@lru_cache(maxsize=1)
def get_db() -> Client:
    try:
        url = required_env("SUPABASE_URL")
        service_role_key = required_env("SUPABASE_SERVICE_ROLE_KEY")
        return create_client(url, service_role_key)
    except Exception as error:
        if isinstance(error, HTTPException):
            raise
        raise HTTPException(status_code=503, detail="Database service is not configured.") from error


def rows(response):
    data = getattr(response, "data", None)
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return [data]


def first(response):
    result = rows(response)
    return result[0] if result else None
