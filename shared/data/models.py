"""
SQLAlchemy ORM models for URL shortener database.
"""
from sqlalchemy import Column, String, DateTime, Index
from sqlalchemy.orm import declarative_base


Base = declarative_base()


class URLModel(Base):
    """SQLAlchemy model for URL mappings."""

    __tablename__ = "urls"

    short_code = Column(String(7), primary_key=True)
    original_url = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False)

    __table_args__ = (
        Index('idx_created_at', 'created_at'),
    )
