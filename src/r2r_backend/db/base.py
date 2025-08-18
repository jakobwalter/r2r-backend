"""Database connection and session management."""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

load_dotenv()

# Build DATABASE_URL from components
db_user = os.getenv("db_user")
db_password = os.getenv("db_password")
db_host = os.getenv("db_host")
db_port = os.getenv("port", "5432")
db_name = os.getenv("dbname", "postgres")

if not all([db_user, db_password, db_host]):
    raise ValueError(
        "Missing database credentials in .env file. "
        "Please check db_user, db_password, and db_host are set."
    )

DATABASE_URL = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

# Create engine with pooler-friendly settings
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # Verify connections before using
    pool_size=10,
    max_overflow=20,
    # Important for Supabase pooler
    connect_args={
        "sslmode": "require",  # Supabase requires SSL
        "connect_timeout": 10,
    }
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db() -> Session:
    """Dependency for FastAPI routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()