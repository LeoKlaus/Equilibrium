import logging
import subprocess
from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, SQLModel, create_engine
from pathlib import Path

Path("config").mkdir(parents=True, exist_ok=True)

sqlite_file_name = "./config/database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, connect_args=connect_args)


# from https://github.com/sqlalchemy/alembic/discussions/1483
def run_migrations(logger: logging.Logger):
    try:
        logger.info("Starting database migrations")

        # Run the Alembic upgrade command using subprocess
        result = subprocess.run(["alembic", "upgrade", "head"], capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Alembic upgrade failed: {result.stderr}")
            raise RuntimeError(f"Alembic upgrade failed: {result.stderr}")

        logger.info("Database migrations completed successfully")
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        # Ensure the engine is disposed
        engine.dispose()

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

# Dependency Injection in FastAPI
def get_session():
    with Session(engine) as session:
        yield session

SessionDep = Annotated[Session, Depends(get_session)]