"""
SQLAlchemy ORM models for URL shortener database.
"""
from sqlalchemy import Column, String, DateTime, Index, Text
from sqlalchemy.orm import declarative_base
import uuid


Base = declarative_base()


class URLModel(Base):
    """SQLAlchemy model for URL mappings."""

    __tablename__ = "urls"

    short_code = Column(String(8), primary_key=True)
    original_url = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False)

    __table_args__ = (
        Index('idx_created_at', 'created_at'),
    )


class ClickModel(Base):
    """SQLAlchemy model for click analytics."""

    __tablename__ = "clicks"

    # UUID as string for DB portability (works with SQLite, Postgres, MySQL)
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    short_code = Column(String(8), nullable=False, index=True)
    original_url = Column(Text, nullable=False)  # Denormalized for performance
    clicked_at = Column(DateTime, nullable=False, index=True)
    ip_address = Column(String(45), nullable=False)  # Supports IPv4 and IPv6
    user_agent = Column(Text, nullable=False)
    referrer = Column(Text, nullable=True)  # Referrer can be empty (direct navigation)
    created_at = Column(DateTime, nullable=False)

    __table_args__ = (
        Index('idx_clicks_short_code_clicked_at', 'short_code', 'clicked_at'),
    )
