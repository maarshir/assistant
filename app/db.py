from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATABASE_URL

url = DATABASE_URL
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql+psycopg://", 1)
elif url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)

connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}

engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db():
    from app import models  # noqa: F401

    Base.metadata.create_all(engine)


def get_profile(session):
    """Профиль всегда существует, иначе шаблоны спотыкаются о пустые значения."""
    from app.models import Profile

    profile = session.get(Profile, 1)
    if profile is None:
        profile = Profile(id=1)
        session.add(profile)
        session.commit()
    return profile
