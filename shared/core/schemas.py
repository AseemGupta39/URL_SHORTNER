"""
Pydantic schemas for URL shortener API and internal data models.
"""
from pydantic import BaseModel, HttpUrl
from datetime import datetime


class ShortenRequest(BaseModel):
    """Request schema for shortening a URL."""
    original_url: HttpUrl


class ShortenResponse(BaseModel):
    """Response schema for URL shortening."""
    short_code: str
    short_url: str
    created_at: datetime

    class Config:
        json_schema_extra = {
            "example": {
                "short_code": "abc1234",
                "short_url": "https://short.ly/abc1234",
                "created_at": "2024-01-15T10:30:00Z"
            }
        }


class RedirectResponse(BaseModel):
    """Response schema for URL redirection."""
    original_url: HttpUrl
    status: str = "found"

    class Config:
        json_schema_extra = {
            "example": {
                "original_url": "https://example.com/very/long/path",
                "status": "found"
            }
        }


class URLData(BaseModel):
    """Internal data model for URL mappings."""
    short_code: str
    original_url: str
    created_at: datetime

    class Config:
        json_schema_extra = {
            "example": {
                "short_code": "abc1234",
                "original_url": "https://example.com/very/long/path",
                "created_at": "2024-01-15T10:30:00Z"
            }
        }
