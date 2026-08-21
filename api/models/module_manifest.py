from sqlmodel import Field, SQLModel


class ModuleManifestEntry(SQLModel):
    name: str
    capabilities: list[str] = Field(default_factory=list)
    endpoints: dict[str, str] = Field(default_factory=dict)


class ModulesManifestResponse(SQLModel):
    modules: list[ModuleManifestEntry]
