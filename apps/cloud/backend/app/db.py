import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

# Asynchronous Database URL for FastAPI (Supabase)
# Convert postgres:// to postgresql+asyncpg:// for asyncpg
postgres_url = os.getenv("POSTGRES_URL", "postgres://postgres.xjjvdxomublvmzqaopbz:w0m3S3jOh2o6OqRn@aws-1-us-west-1.pooler.supabase.com:6543/postgres?sslmode=require&supa=base-pooler.x")
ASYNC_DATABASE_URL = postgres_url.replace("postgres://", "postgresql+asyncpg://", 1)

# Create an asynchronous engine to connect to the database
engine = create_async_engine(ASYNC_DATABASE_URL)

# Create a configured "AsyncSession" class
AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_db() -> AsyncSession:
    """
    FastAPI dependency that provides a database session.
    It ensures the session is properly closed after the request.
    """
    async with AsyncSessionLocal() as session:
        yield session