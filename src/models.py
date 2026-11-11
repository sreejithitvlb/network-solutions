from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

DeviceType = Literal["phone", "tablet", "router", "watch", "other"]
LineStatus = Literal["Active", "Suspended", "Pending Activation", "Closed"]
AccountStatus = Literal["Active", "Suspended", "Pending Verification", "Closed"]
PaymentMethodType = Literal["Credit Card", "Debit Card", "PayPal"]
BillStatus = Literal["Draft", "Issued", "Paid", "Overdue", "Awaiting Payment", "Disputed"]
LineItemType = Literal["Plan Charge", "Overage", "Fee"]


class Plan(BaseModel):
    plan_id: str
    name: str
    data_limit_gb: float
    price_per_month: float
    data_refueling_price_per_gb: float


class Device(BaseModel):
    device_id: str
    device_type: DeviceType
    model: str
    imei: str | None = None
    is_esim_capable: bool
    activated: bool
    activation_date: datetime
    last_esim_transfer_date: datetime | None = None


class Line(BaseModel):
    line_id: str
    phone_number: str
    status: LineStatus
    plan_id: str
    device_id: str | None = None
    data_used_gb: float
    data_refueling_gb: float
    roaming_enabled: bool
    contract_end_date: date
    last_plan_change_date: date
    last_sim_replacement_date: date | None = None
    suspension_start_date: date | None = None


class Address(BaseModel):
    street: str
    city: str
    state: str
    zip_code: str


class PaymentMethod(BaseModel):
    method_type: PaymentMethodType
    account_number_last_4: str
    expiration_date: str


class Customer(BaseModel):
    customer_id: str
    full_name: str
    date_of_birth: date
    email: str
    phone_number: str
    account_status: AccountStatus
    created_at: datetime
    last_extension_date: date | None = None
    goodwill_credit_used_this_year: float
    address: Address
    payment_methods: list[PaymentMethod] = Field(default_factory=list)
    line_ids: list[str] = Field(default_factory=list)
    bill_ids: list[str] = Field(default_factory=list)


class LineItem(BaseModel):
    description: str
    amount: float
    date: date
    item_type: LineItemType


class Bill(BaseModel):
    bill_id: str
    customer_id: str
    period_start: date
    period_end: date
    issue_date: date
    total_due: float
    due_date: date
    status: BillStatus
    line_items: list[LineItem] = Field(default_factory=list)


class Database(BaseModel):
    plans: list[Plan]
    devices: list[Device]
    lines: list[Line]
    customers: list[Customer]
    bills: list[Bill]


class ManualSection(BaseModel):
    key: str
    heading: str
    path: str
    text: str


class Manual(BaseModel):
    sections: dict[str, ManualSection]
