from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings, resolve_database_url

engine = create_engine(resolve_database_url(get_settings()))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
