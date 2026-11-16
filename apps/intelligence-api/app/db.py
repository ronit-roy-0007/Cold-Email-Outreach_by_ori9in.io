from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.config import get_settings, resolve_database_url
from app.models import Base

db_url = resolve_database_url(get_settings())
connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
engine = create_engine(db_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def ensure_schema():
    Base.metadata.create_all(bind=engine)
    try:
        inspector = inspect(engine)
        if "campaigns" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("campaigns")}
            with engine.connect() as conn:
                if "target_sent_emails" not in columns:
                    conn.execute(text("ALTER TABLE campaigns ADD COLUMN target_sent_emails INTEGER DEFAULT 50"))
                if "total_sent_emails" not in columns:
                    conn.execute(text("ALTER TABLE campaigns ADD COLUMN total_sent_emails INTEGER DEFAULT 0"))
                if "sub_campaign_index" not in columns:
                    conn.execute(text("ALTER TABLE campaigns ADD COLUMN sub_campaign_index INTEGER DEFAULT 1"))
                if "is_auto_mode" not in columns:
                    conn.execute(text("ALTER TABLE campaigns ADD COLUMN is_auto_mode BOOLEAN DEFAULT 0"))
                if "is_exhausted" not in columns:
                    conn.execute(text("ALTER TABLE campaigns ADD COLUMN is_exhausted BOOLEAN DEFAULT 0"))
                if "radius_expanded" not in columns:
                    conn.execute(text("ALTER TABLE campaigns ADD COLUMN radius_expanded BOOLEAN DEFAULT 0"))
                if "expanded_locations" not in columns:
                    conn.execute(text("ALTER TABLE campaigns ADD COLUMN expanded_locations JSON DEFAULT '[]'"))
                conn.commit()
    except Exception:
        pass


ensure_schema()


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
