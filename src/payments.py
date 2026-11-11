import sqlite3
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from models import BillStatus

RequestStatus = Literal["Awaiting Acceptance", "Accepted", "Paid", "Cancelled"]
GatewayOutcome = Literal["ok", "declined", "unavailable"]
OPEN_STATUSES: tuple[RequestStatus, ...] = ("Awaiting Acceptance", "Accepted")


class PaymentRequest(BaseModel):
    request_id: str
    customer_id: str
    bill_id: str
    amount: float
    status: RequestStatus
    method_last_4: str | None = None
    attempt: int = 1


class PaymentStore:
    """Payment requests and bill status overrides, kept in SQLite so an open request survives a restart."""

    def __init__(self, path: Path) -> None:
        self._conn: sqlite3.Connection = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS payment_requests (request_id TEXT PRIMARY KEY, customer_id TEXT, "
            "bill_id TEXT, amount REAL, status TEXT, method_last_4 TEXT, attempt INTEGER)"
        )
        self._conn.execute("CREATE TABLE IF NOT EXISTS bill_overrides (bill_id TEXT PRIMARY KEY, status TEXT)")
        self._conn.commit()

    def create_request(self, customer_id: str, bill_id: str, amount: float) -> PaymentRequest:
        request: PaymentRequest = PaymentRequest(
            request_id=f"PR-{uuid.uuid4().hex[:8]}",
            customer_id=customer_id,
            bill_id=bill_id,
            amount=amount,
            status="Awaiting Acceptance",
        )
        self.save(request)
        return request

    def get_request(self, request_id: str) -> PaymentRequest | None:
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT * FROM payment_requests WHERE request_id = ?", (request_id,)
        ).fetchone()
        return None if row is None else PaymentRequest.model_validate(dict(row))

    def list_requests(self, customer_id: str) -> list[PaymentRequest]:
        rows: list[sqlite3.Row] = self._conn.execute(
            "SELECT * FROM payment_requests WHERE customer_id = ?", (customer_id,)
        ).fetchall()
        return [PaymentRequest.model_validate(dict(row)) for row in rows]

    def save(self, request: PaymentRequest) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO payment_requests VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                request.request_id,
                request.customer_id,
                request.bill_id,
                request.amount,
                request.status,
                request.method_last_4,
                request.attempt,
            ),
        )
        self._conn.commit()

    def bill_override(self, bill_id: str) -> BillStatus | None:
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT status FROM bill_overrides WHERE bill_id = ?", (bill_id,)
        ).fetchone()
        return None if row is None else row["status"]

    def set_bill_status(self, bill_id: str, status: BillStatus) -> None:
        self._conn.execute("INSERT OR REPLACE INTO bill_overrides VALUES (?, ?)", (bill_id, status))
        self._conn.commit()


class SimulatedGateway:
    """Scripted payment gateway. Each charge takes the next scripted outcome. Once the script is used up, charges succeed.

    A repeated idempotency key returns the earlier success without charging again.
    """

    def __init__(self, script: list[GatewayOutcome]) -> None:
        self._script: list[GatewayOutcome] = script
        self._succeeded_keys: set[str] = set()

    def charge(self, idempotency_key: str) -> GatewayOutcome:
        if idempotency_key in self._succeeded_keys:
            return "ok"
        outcome: GatewayOutcome = self._script.pop(0) if self._script else "ok"
        if outcome == "ok":
            self._succeeded_keys.add(idempotency_key)
        return outcome
