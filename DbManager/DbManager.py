import threading
from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, SQLModel, create_engine
from pathlib import Path


class DbManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:

                    cls._instance = super(DbManager, cls).__new__(cls)
                    cls._instance._initialize_pool()
        return cls._instance

    def _initialize_pool(self):
        Path("config").mkdir(parents=True, exist_ok=True)

        sqlite_file_name = "./config/database.db"
        sqlite_url = f"sqlite:///{sqlite_file_name}"

        connect_args = {"check_same_thread": False}
        self.engine = create_engine(sqlite_url, connect_args=connect_args)
        SQLModel.metadata.create_all(self.engine)

    def get_session(self):
        return Session(self.engine)

# Dependency Injection in FastAPI
def get_db():
    db_manager = DbManager()
    yield db_manager.get_session()

SessionDep = Annotated[Session, Depends(get_db)]