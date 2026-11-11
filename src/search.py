from datetime import date

from models import Bill, BillStatus, Customer, Database, Device, Line, Plan, PaymentMethod


class DataLayer:
    """Search methods over the seed data.

    Each method takes a Database and returns a Database holding only the matching records.
    Search criteria are parameters. Sections with no matches are empty lists.
    """

    # Journey 1
    @staticmethod
    def find_customer_by_id(db: Database, customer_id: str) -> Database:
        """Find one customer by customer ID, such as "C1002". Returns an empty result if no customer has that ID."""
        customers: list[Customer] = [c for c in db.customers if c.customer_id == customer_id]
        return Database(plans=[], devices=[], lines=[], customers=customers, bills=[])

    # Journey 1
    @staticmethod
    def find_customers_by_phone(db: Database, phone_number: str) -> Database:
        """Find customers whose account phone number matches. Returns every match, which may be empty."""
        customers: list[Customer] = [c for c in db.customers if c.phone_number == phone_number]
        return Database(plans=[], devices=[], lines=[], customers=customers, bills=[])

    # Journey 1
    @staticmethod
    def find_customers_by_name(db: Database, name: str) -> Database:
        """Find customers whose full name contains the given text, ignoring case. Returns every match, which may be empty."""
        needle: str = name.lower()
        customers: list[Customer] = [c for c in db.customers if needle in c.full_name.lower()]
        return Database(plans=[], devices=[], lines=[], customers=customers, bills=[])

    # Journey 1
    @staticmethod
    def find_line_by_id(db: Database, line_id: str) -> Database:
        """Find one line by line ID, such as "L1004". Returns an empty result if no line has that ID."""
        lines: list[Line] = [line for line in db.lines if line.line_id == line_id]
        return Database(plans=[], devices=[], lines=lines, customers=[], bills=[])

    # Journey 2 (line context check)
    @staticmethod
    def find_line_by_phone(db: Database, phone_number: str) -> Database:
        """Find the line with this phone number. Returns an empty result if the number is not on any line."""
        lines: list[Line] = [line for line in db.lines if line.phone_number == phone_number]
        return Database(plans=[], devices=[], lines=lines, customers=[], bills=[])

    # Journey 1
    @staticmethod
    def get_customer_lines(db: Database, customer_id: str) -> Database:
        """List all lines on a customer's account, with their plans and devices. The customer is included, so an empty line list means the customer has no lines."""
        customers: list[Customer] = [c for c in db.customers if c.customer_id == customer_id]
        line_ids: set[str] = {line_id for c in customers for line_id in c.line_ids}
        lines: list[Line] = [line for line in db.lines if line.line_id in line_ids]
        plan_ids: set[str] = {line.plan_id for line in lines}
        device_ids: set[str] = {line.device_id for line in lines if line.device_id is not None}
        plans: list[Plan] = [p for p in db.plans if p.plan_id in plan_ids]
        devices: list[Device] = [d for d in db.devices if d.device_id in device_ids]
        return Database(plans=plans, devices=devices, lines=lines, customers=customers, bills=[])

    # Journey 1
    @staticmethod
    def find_bill_by_id(db: Database, bill_id: str) -> Database:
        """Find one bill by bill ID, such as "B1005". Returns an empty result if no bill has that ID."""
        bills: list[Bill] = [b for b in db.bills if b.bill_id == bill_id]
        return Database(plans=[], devices=[], lines=[], customers=[], bills=bills)

    # Journey 1
    @staticmethod
    def get_customer_bills(
        db: Database, customer_id: str, status: BillStatus | None = None
    ) -> Database:
        """List a customer's bills. Pass status to keep only bills with that status, or leave it out for all bills."""
        bills: list[Bill] = [
            b
            for b in db.bills
            if b.customer_id == customer_id and (status is None or b.status == status)
        ]
        return Database(plans=[], devices=[], lines=[], customers=[], bills=bills)

    # Journey 3
    @staticmethod
    def get_overdue_bills(db: Database, customer_id: str) -> Database:
        """List a customer's overdue bills with their amounts and due dates. Returns an empty result if none are overdue."""
        return DataLayer.get_customer_bills(db, customer_id, "Overdue")

    # Journey 1
    @staticmethod
    def find_plan_by_id(db: Database, plan_id: str) -> Database:
        """Find one plan by plan ID, such as "P1002". Returns an empty result if no plan has that ID."""
        plans: list[Plan] = [p for p in db.plans if p.plan_id == plan_id]
        return Database(plans=plans, devices=[], lines=[], customers=[], bills=[])

    # Journey 3
    @staticmethod
    def get_usable_payment_methods(
        db: Database, customer_id: str, reference_date: date
    ) -> Database:
        """List a customer's payment methods that have not expired on reference_date. Returns only usable methods."""
        customers: list[Customer] = []
        for c in db.customers:
            if c.customer_id != customer_id:
                continue
            usable: list[PaymentMethod] = [
                m for m in c.payment_methods if _expires_on_or_after(m, reference_date)
            ]
            customers.append(c.model_copy(update={"payment_methods": usable}))
        return Database(plans=[], devices=[], lines=[], customers=customers, bills=[])


# Journey 3 (helper for get_usable_payment_methods)
def _expires_on_or_after(method: PaymentMethod, reference_date: date) -> bool:
    month_text, year_text = method.expiration_date.split("/")
    expiry: tuple[int, int] = (int(year_text), int(month_text))
    return expiry >= (reference_date.year, reference_date.month)
