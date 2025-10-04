from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import Integer
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Mapped, mapped_column
from src.config import settings
from src.logs import getLogger

sqlalchemy_logger = getLogger("sqlalchemy.engine").propagate = False

# log connection target (without password) to help debug test/main differences
db = settings.db
getLogger(__name__).info(
    f"DB connect target: user={db.user} host={db.host} port={db.port} db={db.db_name}")

async_engine = create_async_engine(
    settings.db.database_url,
    echo=False)

AsyncSessionLocal = sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False)


class Base(DeclarativeBase):
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    def __repr__(self):
        cols = ", ".join(f"{c.name}={getattr(self, c.name)}" for c in self.__table__.columns)
        return f"<{self.__class__.__name__}({cols})>"
