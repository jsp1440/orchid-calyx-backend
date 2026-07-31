from pydantic import BaseModel, ConfigDict, Field


class PublishLedgerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    expected_review_content_hash: str = Field(pattern="^[0-9a-f]{64}$")
    publication_note: str = Field(default="", max_length=4000)
