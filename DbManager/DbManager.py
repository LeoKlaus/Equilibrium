from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, SQLModel, create_engine
from pathlib import Path


Path("config").mkdir(parents=True, exist_ok=True)

sqlite_file_name = "./config/database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, connect_args=connect_args)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

# Dependency Injection in FastAPI
def get_session():
    with Session(engine) as session:
        yield session

SessionDep = Annotated[Session, Depends(get_session)]