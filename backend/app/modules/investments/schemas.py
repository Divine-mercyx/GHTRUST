import enum
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class InvestmentPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    min_amount: Decimal
    max_amount: Decimal | None = None
    return_rate: Decimal = Field(description="% a year, simple interest")
    tenure_months: int
    risk: RiskLevel
    description: str | None = None
    is_active: bool = True
    image_url: str | None = Field(None, description="Path of the plan's picture (changes when it changes)")


class InvestRequest(BaseModel):
    plan_id: str = Field(..., max_length=36)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    transaction_pin: str = Field(..., min_length=4, max_length=4)


class InvestmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    reference: str | None = None
    plan_id: str
    plan_name: str
    image_url: str | None = None
    amount: Decimal
    return_rate: Decimal
    start_date: date
    maturity_date: date
    projected_return: Decimal
    maturity_value: Decimal = Field(description="Amount plus returns, paid into the wallet at maturity")
    status: str = Field(description="active | paid_out")
    paid_out_at: datetime | None = None


class InvestmentCalculatorRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    tenure_months: int = Field(ge=1, le=60)
    annual_rate: Decimal = Field(default=Decimal("18"))


class InvestmentCalculatorResponse(BaseModel):
    amount: Decimal
    tenure_months: int
    projected_return: Decimal
    maturity_value: Decimal


# ── Staff ────────────────────────────────────────────────────────────────────


class PlanFields(BaseModel):
    name: str = Field(..., min_length=3, max_length=100)
    description: str | None = Field(None, max_length=2000)
    min_amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    max_amount: Decimal | None = Field(None, gt=0, max_digits=18, decimal_places=2)
    return_rate: Decimal = Field(..., gt=0, le=100, max_digits=5, decimal_places=2)
    tenure_months: int = Field(..., ge=1, le=60)
    risk: RiskLevel = RiskLevel.LOW
    is_active: bool = True

    @model_validator(mode="after")
    def _range(self):
        if self.max_amount is not None and self.max_amount < self.min_amount:
            raise ValueError("The maximum must be at least the minimum")
        return self


class CreatePlanRequest(PlanFields):
    pass


class UpdatePlanRequest(BaseModel):
    name: str | None = Field(None, min_length=3, max_length=100)
    description: str | None = Field(None, max_length=2000)
    min_amount: Decimal | None = Field(None, gt=0, max_digits=18, decimal_places=2)
    max_amount: Decimal | None = Field(None, gt=0, max_digits=18, decimal_places=2)
    return_rate: Decimal | None = Field(None, gt=0, le=100, max_digits=5, decimal_places=2)
    tenure_months: int | None = Field(None, ge=1, le=60)
    risk: RiskLevel | None = None
    is_active: bool | None = None


class PlanImageRequest(BaseModel):
    image: str = Field(..., description="Base64 JPEG or PNG, up to 2 MB")


class AdminPlanResponse(InvestmentPlanResponse):
    active_investors: int = 0
    active_amount: Decimal = Decimal("0")
    created_at: datetime


class AdminHoldingResponse(BaseModel):
    id: str
    reference: str | None
    customer_id: str
    customer_name: str
    plan_name: str
    amount: Decimal
    return_rate: Decimal
    projected_return: Decimal
    start_date: date
    maturity_date: date
    status: str
    paid_out_at: datetime | None


class AdminHoldingsPage(BaseModel):
    items: list[AdminHoldingResponse]
    total: int
    active_amount: Decimal
    due_in_30_days: Decimal
