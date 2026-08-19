from sqlmodel import SQLModel


class ModuleManifestEntry(SQLModel):
    name: str
    capabilities: list[str] = []
    endpoints: dict[str, str] = {}


class ModulesManifestResponse(SQLModel):
    modules: list[ModuleManifestEntry]
