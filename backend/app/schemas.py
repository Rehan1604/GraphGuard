from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, model_validator

EntityId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class AccountCreate(BaseModel):
    id: EntityId
    name: str = Field(min_length=1, max_length=100)
    account_type: Literal["individual", "business"]


class Account(AccountCreate):
    created_at: datetime


class TransactionCreate(BaseModel):
    id: EntityId
    source_account_id: EntityId
    target_account_id: EntityId
    # Decimal, never float. Serialized in JSON as a string, e.g. "250.00".
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    currency: Currency = "USD"
    timestamp: AwareDatetime  # naive datetimes (no timezone) are rejected

    @model_validator(mode="after")
    def no_self_transfer(self) -> "TransactionCreate":
        if self.source_account_id == self.target_account_id:
            raise ValueError("source_account_id and target_account_id must differ")
        return self


class Transaction(TransactionCreate):
    ingested_at: datetime