"""
Pydantic schemas for URL shortener API and internal data models.
"""
from pydantic import BaseModel, HttpUrl
from datetime import datetime
from typing import Optional


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
                "short_code": "abc12345",
                "short_url": "https://short.ly/abc12345",
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
                "short_code": "abc12345",
                "original_url": "https://example.com/very/long/path",
                "created_at": "2024-01-15T10:30:00Z"
            }
        }


class ClickData(BaseModel):
    """Domain model for click analytics data (before persistence)."""
    click_id: str  # Producer-generated UUID; used as DB PK for idempotent inserts
    short_code: str
    original_url: str
    clicked_at: datetime
    ip_address: str
    user_agent: str
    referrer: Optional[str] = None  # Can be empty for direct navigation

    class Config:
        json_schema_extra = {
            "example": {
                "click_id": "550e8400-e29b-41d4-a716-446655440000",
                "short_code": "abc12345",
                "original_url": "https://example.com/very/long/path",
                "clicked_at": "2024-01-15T10:30:00Z",
                "ip_address": "192.168.1.1",
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "referrer": "https://google.com"
            }
        }
