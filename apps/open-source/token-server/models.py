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
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel, EmailStr
from dotenv import load_dotenv

load_dotenv()

# Database connection setup
postgres_url = os.getenv("POSTGRES_URL", "postgres://postgres.xjjvdxomublvmzqaopbz:w0m3S3jOh2o6OqRn@aws-1-us-west-1.pooler.supabase.com:6543/postgres?sslmode=require&supa=base-pooler.x")
ASYNC_DATABASE_URL = postgres_url.replace("postgres://", "postgresql+asyncpg://", 1)

# Create async engine
engine = create_async_engine(ASYNC_DATABASE_URL)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

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

# Prospects Table for Dialer
prospects = Table(
    "prospects",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("business_id", String(255), ForeignKey("businesses.id"), nullable=False),
    Column("name", String(255)),
    Column("phone_number", String(50), nullable=False),
    Column("email", String(255)),
    Column("notes", Text),
    Column("status", String(50), default="new"),  # new, contacted, qualified, converted, dead
    Column("last_called", DateTime),
    Column("call_count", Integer, default=0),
    Column("created_at", DateTime, default=datetime.datetime.utcnow),
)

# Call Logs Table
call_logs = Table(
    "call_logs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("prospect_id", Integer, ForeignKey("prospects.id")),
    Column("business_id", String(255), ForeignKey("businesses.id"), nullable=False),
    Column("phone_number", String(50), nullable=False),
    Column("room_name", String(255)),
    Column("call_duration", Integer),  # seconds
    Column("call_status", String(50)),  # initiated, connected, failed, completed
    Column("notes", Text),
    Column("created_at", DateTime, default=datetime.datetime.utcnow),
)

# Pydantic Models
class LeadBase(BaseModel):
    visitor_name: str | None = None
    visitor_email: str | None = None  # Made optional for dialer
    visitor_phone: str | None = None
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

# Prospect Models
class ProspectBase(BaseModel):
    name: str | None = None
    phone_number: str
    email: str | None = None
    notes: str | None = None
    status: str = "new"

class ProspectCreate(ProspectBase):
    business_id: str

class Prospect(ProspectBase):
    id: int
    business_id: str
    last_called: datetime.datetime | None = None
    call_count: int = 0
    created_at: datetime.datetime

    class Config:
        from_attributes = True

# Call Log Models
class CallLogBase(BaseModel):
    phone_number: str
    room_name: str | None = None
    call_duration: int | None = None
    call_status: str = "initiated"
    notes: str | None = None

class CallLogCreate(CallLogBase):
    prospect_id: int | None = None
    business_id: str

class CallLog(CallLogBase):
    id: int
    prospect_id: int | None = None
    business_id: str
    created_at: datetime.datetime

    class Config:
        from_attributes = True

async def get_db() -> AsyncSession:
    """Database session dependency"""
    async with AsyncSessionLocal() as session:
        yield session