from pathlib import Path

import pytest
from pydantic import ValidationError

from file_loader import MANUAL_PATH, load_database, load_manual
from models import Customer, Database, Line, Manual, ManualSection

DB_PATH: Path = Path(__file__).parents[1] / "datasource" / "db.toml"


@pytest.fixture
def db() -> Database:
    return load_database(DB_PATH)


@pytest.fixture(scope="module")
def manual() -> Manual:
    return load_manual(MANUAL_PATH)


def test_loads_every_record_type(db: Database) -> None:
    assert len(db.plans) == 5
    assert len(db.devices) == 9
    assert len(db.lines) == 9
    assert len(db.customers) == 4
    assert len(db.bills) == 6


def test_starting_payment_case_is_overdue(db: Database) -> None:
    bill = next(b for b in db.bills if b.bill_id == "B1005")
    assert bill.customer_id == "C1002"
    assert bill.status == "Overdue"
    assert bill.total_due == 425.0
    assert bill.due_date.isoformat() == "2025-02-26"


def test_customer_payment_methods_and_lines_are_loaded(db: Database) -> None:
    customer = next(c for c in db.customers if c.customer_id == "C1002")
    assert [m.method_type for m in customer.payment_methods] == ["Debit Card", "Credit Card"]
    assert customer.line_ids == ["L1004", "L1005", "L1006", "L1007", "L1008"]


def test_customer_with_no_lines_has_empty_lists(db: Database) -> None:
    customer = next(c for c in db.customers if c.customer_id == "C1004")
    assert customer.payment_methods == []
    assert customer.line_ids == []
    assert customer.bill_ids == []


def test_optional_line_dates_are_none_when_absent(db: Database) -> None:
    line = next(line for line in db.lines if line.line_id == "L1001")
    assert line.suspension_start_date is None
    assert line.last_sim_replacement_date is None


def test_suspended_line_has_suspension_date(db: Database) -> None:
    line = next(line for line in db.lines if line.line_id == "L1003")
    assert line.status == "Suspended"
    assert line.suspension_start_date is not None
    assert line.suspension_start_date.isoformat() == "2025-02-01"


def test_bill_line_items_are_loaded(db: Database) -> None:
    bill = next(b for b in db.bills if b.bill_id == "B1001")
    assert len(bill.line_items) == 4
    assert bill.line_items[3].item_type == "Overage"


def test_unknown_status_is_rejected(tmp_path: Path) -> None:
    text = DB_PATH.read_text(encoding="utf-8").replace('status = "Overdue"', 'status = "Late"', 1)
    path = tmp_path / "db.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValidationError):
        load_database(path)


def test_missing_section_is_rejected(tmp_path: Path) -> None:
    text = DB_PATH.read_text(encoding="utf-8")
    text = text.split("[[bills]]")[0]
    path = tmp_path / "db.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValidationError):
        load_database(path)


def test_list_defaults_are_not_shared_between_customers() -> None:
    address = {"street": "1 Test St", "city": "Testville", "state": "CA", "zip_code": "90000"}
    base = {
        "customer_id": "C9001",
        "full_name": "Test One",
        "date_of_birth": "1990-01-01",
        "email": "one@example.com",
        "phone_number": "555-000-0001",
        "account_status": "Active",
        "created_at": "2025-01-01T00:00:00",
        "goodwill_credit_used_this_year": 0.0,
        "address": address,
    }
    first = Customer.model_validate(base)
    second = Customer.model_validate({**base, "customer_id": "C9002"})
    first.line_ids.append("L9999")
    assert second.line_ids == []


def test_line_device_id_may_be_absent() -> None:
    line = Line.model_validate(
        {
            "line_id": "L9001",
            "phone_number": "555-000-0002",
            "status": "Active",
            "plan_id": "P1001",
            "data_used_gb": 0.0,
            "data_refueling_gb": 0.0,
            "roaming_enabled": False,
            "contract_end_date": "2027-01-01",
            "last_plan_change_date": "2025-01-01",
        }
    )
    assert line.device_id is None


def test_manual_section_path_joins_heading_levels() -> None:
    section = ManualSection(
        key="S9",
        heading="Airplane Mode",
        path="Cellular Service > Troubleshooting Service Problems > Airplane Mode",
        text="Turn airplane mode on, then off.",
    )
    assert section.path.split(" > ") == ["Cellular Service", "Troubleshooting Service Problems", "Airplane Mode"]
    assert section.path.endswith(section.heading)


def test_manual_has_every_section_with_unique_key(manual: Manual) -> None:
    assert len(manual.sections) == 36
    assert all(key == section.key for key, section in manual.sections.items())


def test_repeated_heading_has_distinct_paths(manual: Manual) -> None:
    airplane = [section for section in manual.sections.values() if section.heading == "Airplane Mode"]
    assert len(airplane) == 2
    assert len({section.path for section in airplane}) == 2
    assert {section.path.split(" > ")[-2] for section in airplane} == {
        "Troubleshooting Service Problems",
        "Troubleshooting Mobile Data Problems",
    }


def test_top_level_section_path_is_its_heading(manual: Manual) -> None:
    intro = manual.sections["S1"]
    assert intro.heading == "Introduction"
    assert intro.path == "Introduction"


def test_section_text_stops_at_next_heading(manual: Manual) -> None:
    airplane = manual.sections["S9"]
    next_section = manual.sections["S10"]
    assert airplane.text.endswith("to turn it OFF.")
    assert next_section.text.splitlines()[0] not in airplane.text


def test_manual_round_trips_through_json(manual: Manual) -> None:
    restored = Manual.model_validate_json(manual.model_dump_json())
    assert restored == manual


def test_manual_section_requires_path() -> None:
    with pytest.raises(ValidationError):
        ManualSection.model_validate({"key": "S1", "heading": "Introduction", "text": "Hello."})
