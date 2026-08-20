import logging
from pathlib import Path
from typing import Annotated

from alembic import command
from alembic.config import Config
from fastapi import Depends
from sqlmodel import Session, SQLModel, create_engine

Path("config").mkdir(parents=True, exist_ok=True)

sqlite_file_name = "./config/database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, connect_args=connect_args)

logger = logging.getLogger(__package__)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def run_migrations() -> None:
    db_existed = Path(sqlite_file_name).exists()
    cfg = Config("alembic.ini")

    if db_existed:
        try:
            logger.info("Running database migrations...")
            command.upgrade(cfg, "head")
            logger.info("Database migrations complete")
        except Exception:
            logger.exception("Database migration failed")
            raise
        finally:
            engine.dispose()
    else:
        logger.info("No database found, creating one...")

    create_db_and_tables()

    if not db_existed:
        command.stamp(cfg, "head")
        logger.info("New database stamped as up to date")

# Dependency Injection in FastAPI
def get_session():
    with Session(engine) as session:
        yield session

SessionDep = Annotated[Session, Depends(get_session)]