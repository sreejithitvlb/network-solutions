import sqlite3
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

RequestStatus = Literal["Open", "Paid"]
GatewayOutcome = Literal["ok", "declined", "unavailable"]
OPEN: RequestStatus = "Open"
PAID: RequestStatus = "Paid"


class PaymentRequest(BaseModel):
    request_id: str
    customer_id: str
    bill_id: str
    amount: float
    status: RequestStatus


class PaymentStore:
    """Payment requests, kept in SQLite so an unfinished request survives a restart."""

    def __init__(self, path: Path) -> None:
        self._conn: sqlite3.Connection = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS payment_requests (request_id TEXT PRIMARY KEY, customer_id TEXT, "
            "bill_id TEXT, amount REAL, status TEXT)"
        )
        self._conn.commit()

    def create_request(self, customer_id: str, bill_id: str, amount: float) -> PaymentRequest:
        request: PaymentRequest = PaymentRequest(
            request_id=f"PR-{uuid.uuid4().hex[:8]}",
            customer_id=customer_id,
            bill_id=bill_id,
            amount=amount,
            status=OPEN,
        )
        self.save(request)
        return request

    def list_requests(self, customer_id: str) -> list[PaymentRequest]:
        rows: list[sqlite3.Row] = self._conn.execute(
            "SELECT * FROM payment_requests WHERE customer_id = ?", (customer_id,)
        ).fetchall()
        return [PaymentRequest.model_validate(dict(row)) for row in rows]

    def get_request(self, request_id: str) -> PaymentRequest | None:
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT * FROM payment_requests WHERE request_id = ?", (request_id,)
        ).fetchone()
        return None if row is None else PaymentRequest.model_validate(dict(row))

    def save(self, request: PaymentRequest) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO payment_requests VALUES (?, ?, ?, ?, ?)",
            (request.request_id, request.customer_id, request.bill_id, request.amount, request.status),
        )
        self._conn.commit()


class SimulatedGateway:
    """Scripted payment gateway. Each charge takes the next scripted outcome. Once the script is used up, charges succeed."""

    def __init__(self, script: list[GatewayOutcome]) -> None:
        self._script: list[GatewayOutcome] = script

    def charge(self) -> GatewayOutcome:
        return self._script.pop(0) if self._script else "ok"
