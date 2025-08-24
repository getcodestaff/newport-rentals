import datetime
import os
from sqlalchemy import (
    MetaData,
    Table,
    Column,
    Integer,
    String,
    DateTime,
    Text,
    ForeignKey,
)
from pydantic import BaseModel, EmailStr
from dotenv import load_dotenv

load_dotenv()

# Synchronous Database URL for Alembic (Supabase)
# Convert postgres:// to postgresql+psycopg2:// for psycopg2
postgres_url_sync = os.getenv("POSTGRES_URL_NON_POOLING", "postgres://postgres.xjjvdxomublvmzqaopbz:w0m3S3jOh2o6OqRn@aws-1-us-west-1.pooler.supabase.com:5432/postgres?sslmode=require")
DATABASE_URL = postgres_url_sync.replace("postgres://", "postgresql+psycopg2://", 1)

metadata = MetaData()

# Businesses Table Definition
businesses = Table(
    "businesses",
    metadata,
    Column("id", String(255), primary_key=True),
    Column("business_name", String(255), nullable=False),
    Column("contact_name", String(255)),
    Column("phone_number", String(50)),
    Column("email", String(255)),
    Column("knowledge_base", Text),
    Column("created_at", DateTime, default=datetime.datetime.utcnow),
)


# Leads Table Definition
leads = Table(
    "leads",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("business_id", String(255), ForeignKey("businesses.id"), nullable=False),
    Column("visitor_name", String(255)),
    Column("visitor_phone", String(50)),
    Column("visitor_email", String(255)),
    Column("inquiry", Text, nullable=False),
    Column("status", String(50), default="new"),
    Column("captured_at", DateTime, default=datetime.datetime.utcnow),
)

# Pydantic Models
class LeadBase(BaseModel):
    visitor_name: str | None = None
    visitor_email: EmailStr  # Email is now required and validated
    visitor_phone: str | None = None # Phone is now optional
    inquiry: str

class LeadCreate(LeadBase):
    business_id: str

class Lead(LeadBase):
    id: int
    business_id: str
    status: str
    captured_at: datetime.datetime

    class Config:
        from_attributes = True

class BusinessBase(BaseModel):
    business_name: str
    contact_name: str | None = None
    phone_number: str | None = None
    email: str | None = None
    knowledge_base: str | None = None

class BusinessCreate(BusinessBase):
    id: str

class Business(BusinessBase):
    id: str
    created_at: datetime.datetime

    class Config:
        from_attributes = True