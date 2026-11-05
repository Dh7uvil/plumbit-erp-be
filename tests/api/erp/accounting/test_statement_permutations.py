"""Account statement permutations: party, GL account, PDC."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.api.erp.accounting.test_banking import _bank_account, _enable_books, _posted_invoice
from tests.api.erp.purchase_orders.test_routes import (
    _create_product,
    _create_supplier,
    _seeded_ids,
)
from tests.api.erp.supplier_payments.test_routes import (
    _enable_books as _enable_books_supplier,
)
from tests.api.inventory_management.goods_receipts.test_routes import (
    _create_from_po,
    _idempotent as _gr_idempotent,
    _issue_tracked_po,
    _post_grn,
)
from tests.conftest import login_headers, provision_admin


async def _posted_supplier_goods_bill(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    rate: str = "200.0000",
) -> dict[str, object]:
    ctx = await _issue_tracked_po(client, headers, quantity="1")
    created = await client.post(
        "/api/v1/purchase-invoices",
        headers=headers,
        json={
            "supplier_id": ctx["supplier_id"],
            "lines": [
                {
                    "product_id": ctx["product_id"],
                    "quantity": "1",
                    "rate": rate,
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    bill = created.json()["data"]
    posted = await client.post(
        f"/api/v1/purchase-invoices/{bill['id']}/post",
        headers=_gr_idempotent(headers, bill["version"]),
    )
    assert posted.status_code == 200, posted.text
    return posted.json()["data"]


async def _posted_orphan_supplier_bill(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    rate: str = "200.0000",
) -> dict[str, object]:
    """Goods bill with no purchase order (legacy statement credits PI, not PO)."""
    ids = await _seeded_ids(client, headers)
    supplier_id = await _create_supplier(client, headers)
    product_id = await _create_product(client, headers, ids)
    created = await client.post(
        "/api/v1/purchase-invoices",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "lines": [
                {
                    "product_id": product_id,
                    "quantity": "1",
                    "rate": rate,
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    bill = created.json()["data"]
    posted = await client.post(
        f"/api/v1/purchase-invoices/{bill['id']}/post",
        headers=_gr_idempotent(headers, bill["version"]),
    )
    assert posted.status_code == 200, posted.text
    return posted.json()["data"]


async def _accounts(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    roles = await client.get("/api/v1/accounts/system-roles", headers=headers)
    assert roles.status_code == 200, roles.text
    return {item["role"]: item["account_id"] for item in roles.json()["data"]}


@pytest.mark.asyncio
async def test_account_statement_collapses_multi_line_journal_on_same_account(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    bank_id = accounts["BANK"]
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={
            "narration": "Payment with charges",
            "lines": [
                {"account_id": bank_id, "debit": "0", "credit": "100.0000"},
                {"account_id": bank_id, "debit": "0", "credit": "5.0000", "description": "Bank fee"},
                {"account_id": accounts["SALES_REVENUE"], "debit": "105.0000", "credit": "0"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    posted = await client.post(
        f"/api/v1/journals/{row['id']}/post",
        headers={**headers, "If-Match": str(row["version"]), "Idempotency-Key": uuid4().hex},
    )
    assert posted.status_code == 200, posted.text
    entry_date = posted.json()["data"]["entry_date"]
    statement = await client.get(
        "/api/v1/reports/account-statement",
        headers=headers,
        params={"account_id": bank_id, "from": entry_date, "to": entry_date},
    )
    assert statement.status_code == 200, statement.text
    data = statement.json()["data"]
    bank_lines = [
        line
        for line in data["lines"]
        if line["journal_entry_id"] == posted.json()["data"]["id"]
    ]
    assert bank_lines == []
    assert Decimal(data["closing_balance"]) == Decimal("-105.0000")


@pytest.mark.asyncio
async def test_account_statement_by_gl_account(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    bank_id = accounts["BANK"]
    created = await client.post(
        "/api/v1/journals",
        headers=headers,
        json={
            "lines": [
                {"account_id": bank_id, "debit": "50.0000", "credit": "0"},
                {"account_id": accounts["SALES_REVENUE"], "debit": "0", "credit": "50.0000"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    posted = await client.post(
        f"/api/v1/journals/{row['id']}/post",
        headers={**headers, "If-Match": str(row["version"]), "Idempotency-Key": uuid4().hex},
    )
    assert posted.status_code == 200, posted.text
    entry_date = posted.json()["data"]["entry_date"]
    statement = await client.get(
        "/api/v1/reports/account-statement",
        headers=headers,
        params={"account_id": bank_id, "from": entry_date, "to": entry_date},
    )
    assert statement.status_code == 200, statement.text
    data = statement.json()["data"]
    assert data["account_id"] == bank_id
    assert Decimal(data["closing_balance"]) == Decimal("50.0000")
    assert data["lines"] == []


@pytest.mark.asyncio
async def test_account_statement_include_pdc_pending_line(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    bank = await _bank_account(client, headers)
    invoice = await _posted_invoice(client, headers)
    total = Decimal(str(invoice["grand_total"]))
    created = await client.post(
        "/api/v1/cheques",
        headers=headers,
        json={
            "cheque_number": "PDC-STMT-1",
            "direction": "INBOUND",
            "cheque_date": "2026-12-15",
            "due_date": "2026-12-15",
            "amount": str(total),
            "currency_id": invoice["currency_id"],
            "party_type": "CUSTOMER",
            "party_id": invoice["customer_id"],
            "bank_account_id": bank["id"],
        },
    )
    assert created.status_code == 201, created.text
    cheque = created.json()["data"]
    issued = await client.post(
        f"/api/v1/cheques/{cheque['id']}/issue",
        headers={**headers, "If-Match": str(cheque["version"]), "Idempotency-Key": uuid4().hex},
    )
    assert issued.status_code == 200, issued.text
    statement = await client.get(
        "/api/v1/reports/account-statement",
        headers=headers,
        params={
            "party_type": "CUSTOMER",
            "party_id": invoice["customer_id"],
            "from": "2026-12-01",
            "to": "2026-12-31",
            "include_pdc": "true",
        },
    )
    assert statement.status_code == 200, statement.text
    data = statement.json()["data"]
    pdc_lines = [line for line in data["lines"] if line.get("voucher_code") == "PD"]
    assert len(pdc_lines) == 1
    assert pdc_lines[0]["cheque_number"] == "PDC-STMT-1"


@pytest.mark.asyncio
async def test_account_statement_exclude_opening_balance(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    bank_id = accounts["BANK"]

    async def post_bank(amount: str, entry_date: str) -> None:
        created = await client.post(
            "/api/v1/journals",
            headers=headers,
            json={
                "entry_date": entry_date,
                "lines": [
                    {"account_id": bank_id, "debit": amount, "credit": "0"},
                    {
                        "account_id": accounts["SALES_REVENUE"],
                        "debit": "0",
                        "credit": amount,
                    },
                ],
            },
        )
        assert created.status_code == 201, created.text
        row = created.json()["data"]
        posted = await client.post(
            f"/api/v1/journals/{row['id']}/post",
            headers={**headers, "If-Match": str(row["version"]), "Idempotency-Key": uuid4().hex},
        )
        assert posted.status_code == 200, posted.text

    await post_bank("100.0000", "2026-06-01")
    await post_bank("25.0000", "2026-06-15")

    statement = await client.get(
        "/api/v1/reports/account-statement",
        headers=headers,
        params={
            "account_id": bank_id,
            "from": "2026-06-15",
            "to": "2026-06-15",
            "include_opening": "false",
        },
    )
    assert statement.status_code == 200, statement.text
    data = statement.json()["data"]
    assert data["opening"] is None
    assert Decimal(data["opening_balance"]) == Decimal("100.0000")
    assert Decimal(data["closing_balance"]) == Decimal("25.0000")
    assert data["lines"] == []


@pytest.mark.asyncio
async def test_account_statement_opening_row_balance_only_preserves_math(
    client: AsyncClient,
) -> None:
    """Opening OP row is display-only; balances and period lines stay GL-correct."""
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    bank_id = accounts["BANK"]

    async def post_bank(amount: str, entry_date: str) -> None:
        created = await client.post(
            "/api/v1/journals",
            headers=headers,
            json={
                "entry_date": entry_date,
                "lines": [
                    {"account_id": bank_id, "debit": amount, "credit": "0"},
                    {
                        "account_id": accounts["SALES_REVENUE"],
                        "debit": "0",
                        "credit": amount,
                    },
                ],
            },
        )
        assert created.status_code == 201, created.text
        row = created.json()["data"]
        posted = await client.post(
            f"/api/v1/journals/{row['id']}/post",
            headers={**headers, "If-Match": str(row["version"]), "Idempotency-Key": uuid4().hex},
        )
        assert posted.status_code == 200, posted.text

    await post_bank("100.0000", "2026-06-01")
    await post_bank("25.0000", "2026-06-15")

    statement = await client.get(
        "/api/v1/reports/account-statement",
        headers=headers,
        params={
            "account_id": bank_id,
            "from": "2026-06-15",
            "to": "2026-06-15",
            "include_opening": "true",
        },
    )
    assert statement.status_code == 200, statement.text
    data = statement.json()["data"]
    assert data["opening"] is not None
    assert Decimal(data["opening"]["debit"]) == Decimal("0")
    assert Decimal(data["opening"]["credit"]) == Decimal("0")
    assert Decimal(data["opening"]["running_balance"]) == Decimal("100.0000")
    assert Decimal(data["opening_balance"]) == Decimal("100.0000")
    assert Decimal(data["closing_balance"]) == Decimal("125.0000")
    assert data["lines"] == []

    gl = await client.get(
        "/api/v1/reports/general-ledger",
        headers=headers,
        params={"account_id": bank_id, "from": "2026-06-15", "to": "2026-06-15"},
    )
    assert gl.status_code == 200, gl.text
    assert len(gl.json()["data"]["lines"]) == 1
    assert Decimal(gl.json()["data"]["opening_balance"]) == Decimal("100.0000")


@pytest.mark.asyncio
async def test_account_statement_unrelated_manual_journals_stay_separate(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    accounts = await _accounts(client, headers)
    bank_id = accounts["BANK"]
    entry_date = "2026-07-01"

    for amount in ("10.0000", "20.0000"):
        created = await client.post(
            "/api/v1/journals",
            headers=headers,
            json={
                "entry_date": entry_date,
                "lines": [
                    {"account_id": bank_id, "debit": amount, "credit": "0"},
                    {
                        "account_id": accounts["SALES_REVENUE"],
                        "debit": "0",
                        "credit": amount,
                    },
                ],
            },
        )
        assert created.status_code == 201, created.text
        row = created.json()["data"]
        posted = await client.post(
            f"/api/v1/journals/{row['id']}/post",
            headers={**headers, "If-Match": str(row["version"]), "Idempotency-Key": uuid4().hex},
        )
        assert posted.status_code == 200, posted.text

    statement = await client.get(
        "/api/v1/reports/account-statement",
        headers=headers,
        params={"account_id": bank_id, "from": entry_date, "to": entry_date},
    )
    assert statement.status_code == 200, statement.text
    data = statement.json()["data"]
    assert data["lines"] == []
    assert Decimal(data["closing_balance"]) == Decimal("30.0000")
    assert Decimal(data["total_debit"]) == Decimal("0")
    assert Decimal(data["total_credit"]) == Decimal("0")


@pytest.mark.asyncio
async def test_customer_statement_csv_export(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    invoice = await _posted_invoice(client, headers)
    customer_id = invoice["customer_id"]
    from_date = invoice["invoice_date"]
    to_date = invoice["invoice_date"]
    json_resp = await client.get(
        "/api/v1/reports/customer-statement",
        headers=headers,
        params={"customer_id": customer_id, "from": from_date, "to": to_date},
    )
    assert json_resp.status_code == 200, json_resp.text
    json_lines = json_resp.json()["data"]["lines"]
    csv_resp = await client.get(
        "/api/v1/reports/customer-statement",
        headers=headers,
        params={
            "customer_id": customer_id,
            "from": from_date,
            "to": to_date,
            "format": "csv",
            "include_pdc": "true",
        },
    )
    assert csv_resp.status_code == 200, csv_resp.text
    content_type = csv_resp.headers.get("content-type", "")
    assert "text/csv" in content_type
    csv_rows = [line for line in csv_resp.text.splitlines() if line.strip()]
    if json_lines:
        assert len(csv_rows) >= len(json_lines)
    else:
        assert len(csv_rows) >= 1


@pytest.mark.asyncio
async def test_supplier_statement_purchase_invoice_credit_and_payment_debit(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books_supplier(client, headers)
    accounts = await _accounts(client, headers)
    bill = await _posted_orphan_supplier_bill(client, headers, rate="200.0000")
    supplier_id = bill["supplier_id"]
    bill_date = bill["invoice_date"]
    total = Decimal(str(bill["grand_total"]))
    payment = await client.post(
        "/api/v1/supplier-payments",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "amount_paid": str(total),
            "payment_account_id": accounts["BANK"],
            "payment_method": "TT",
            "allocations": [
                {
                    "item_type": "PURCHASE_INVOICE",
                    "item_id": bill["id"],
                    "amount": str(total),
                }
            ],
        },
    )
    assert payment.status_code == 201, payment.text
    pay_row = payment.json()["data"]
    posted_pay = await client.post(
        f"/api/v1/supplier-payments/{pay_row['id']}/post",
        headers={**headers, "If-Match": str(pay_row["version"]), "Idempotency-Key": uuid4().hex},
    )
    assert posted_pay.status_code == 200, posted_pay.text
    pay_body = posted_pay.json()["data"]
    pay_date = pay_body["payment_date"]

    statement = await client.get(
        "/api/v1/reports/supplier-statement",
        headers=headers,
        params={"supplier_id": supplier_id, "from": bill_date, "to": pay_date},
    )
    assert statement.status_code == 200, statement.text
    data = statement.json()["data"]
    assert data["account_code"]
    assert Decimal(data["total_credit"]) == total
    assert Decimal(data["total_debit"]) == total
    pi_lines = [line for line in data["lines"] if line["type_code"] == "PI"]
    sp_lines = [line for line in data["lines"] if line["type_code"] == "PV"]
    assert len(pi_lines) == 1
    assert Decimal(pi_lines[0]["credit"]) == total
    assert len(sp_lines) == 1
    assert Decimal(sp_lines[0]["debit"]) == total


@pytest.mark.asyncio
async def test_supplier_statement_journal_cost_sheet_supplier_line(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books_supplier(client, headers)
    supplier_id = await _create_supplier(client, headers)
    invoice = await _posted_invoice(client, headers)
    listed = await client.get("/api/v1/accounts", headers=headers)
    assert listed.status_code == 200, listed.text
    skip = {"ACCOUNTS_RECEIVABLE", "ACCOUNTS_PAYABLE", "CASH", "BANK"}
    postable = [
        row["id"]
        for row in listed.json()["data"]
        if not row.get("is_group") and row.get("account_subtype") not in skip
    ]
    assert postable, "need a postable expense account"
    expense_account = postable[0]
    created = await client.post(
        "/api/v1/cost-sheets",
        headers=headers,
        json={
            "sheet_type": "IMPORT",
            "sheet_mode": "JOURNAL",
            "supplier_id": supplier_id,
            "source_document_type": "SALES_INVOICE",
            "source_document_id": invoice["id"],
            "journal_lines": [
                {
                    "line_kind": "G",
                    "account_id": expense_account,
                    "debit": "75.0000",
                    "credit": "0",
                    "capitalize": False,
                },
                {
                    "line_kind": "S",
                    "party_id": supplier_id,
                    "debit": "0",
                    "credit": "75.0000",
                    "description": "Sea freight CS",
                },
            ],
        },
    )
    assert created.status_code == 201, created.text
    sheet = created.json()["data"]
    assert sheet["journal_entry_id"] is not None
    doc_date = sheet["document_date"]
    statement = await client.get(
        "/api/v1/reports/supplier-statement",
        headers=headers,
        params={"supplier_id": supplier_id, "from": doc_date, "to": doc_date},
    )
    assert statement.status_code == 200, statement.text
    data = statement.json()["data"]
    cs_lines = [line for line in data["lines"] if line["type_code"] == "CSI"]
    assert len(cs_lines) == 1
    assert Decimal(cs_lines[0]["credit"]) == Decimal("75.0000")
    assert cs_lines[0]["description"] == "Sea freight CS"


@pytest.mark.asyncio
async def test_account_statement_cost_sheet_source_type_code(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    supplier_id = await _create_supplier(client, headers)
    invoice = await _posted_invoice(client, headers)
    listed = await client.get("/api/v1/accounts", headers=headers)
    postable = [
        row["id"]
        for row in listed.json()["data"]
        if not row.get("is_group")
        and row.get("account_subtype")
        not in {"ACCOUNTS_RECEIVABLE", "ACCOUNTS_PAYABLE", "CASH", "BANK"}
    ]
    expense_account = postable[0]
    created = await client.post(
        "/api/v1/cost-sheets",
        headers=headers,
        json={
            "sheet_type": "IMPORT",
            "sheet_mode": "JOURNAL",
            "supplier_id": supplier_id,
            "source_document_type": "SALES_INVOICE",
            "source_document_id": invoice["id"],
            "journal_lines": [
                {
                    "line_kind": "G",
                    "account_id": expense_account,
                    "debit": "40.0000",
                    "credit": "0",
                    "capitalize": False,
                },
                {
                    "line_kind": "S",
                    "party_id": supplier_id,
                    "debit": "0",
                    "credit": "40.0000",
                },
            ],
        },
    )
    assert created.status_code == 201, created.text
    sheet = created.json()["data"]
    assert sheet["journal_entry_id"] is not None
    doc_date = sheet["document_date"]
    statement = await client.get(
        "/api/v1/reports/account-statement",
        headers=headers,
        params={
            "party_type": "SUPPLIER",
            "party_id": supplier_id,
            "from": doc_date,
            "to": doc_date,
        },
    )
    assert statement.status_code == 200, statement.text
    data = statement.json()["data"]
    cs_lines = [line for line in data["lines"] if line.get("voucher_code") == "CSI"]
    assert len(cs_lines) >= 1


@pytest.mark.asyncio
async def test_account_statement_cost_sheet_one_row_per_ledger_line_on_account(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books_supplier(client, headers)
    supplier_id = await _create_supplier(client, headers)
    invoice = await _posted_invoice(client, headers)
    listed = await client.get("/api/v1/accounts", headers=headers)
    skip = {"ACCOUNTS_RECEIVABLE", "ACCOUNTS_PAYABLE", "CASH", "BANK"}
    postable = [
        row["id"]
        for row in listed.json()["data"]
        if not row.get("is_group") and row.get("account_subtype") not in skip
    ]
    assert len(postable) >= 1
    expense_account = postable[0]
    created = await client.post(
        "/api/v1/cost-sheets",
        headers=headers,
        json={
            "sheet_type": "IMPORT",
            "sheet_mode": "JOURNAL",
            "supplier_id": supplier_id,
            "source_document_type": "SALES_INVOICE",
            "source_document_id": invoice["id"],
            "journal_lines": [
                {
                    "line_kind": "G",
                    "account_id": expense_account,
                    "debit": "10.0000",
                    "credit": "0",
                    "description": "Freight A",
                    "capitalize": False,
                },
                {
                    "line_kind": "G",
                    "account_id": expense_account,
                    "debit": "20.0000",
                    "credit": "0",
                    "description": "Freight B",
                    "capitalize": False,
                },
                {
                    "line_kind": "S",
                    "party_id": supplier_id,
                    "debit": "0",
                    "credit": "30.0000",
                },
            ],
        },
    )
    assert created.status_code == 201, created.text
    sheet = created.json()["data"]
    if sheet.get("journal_entry_id") is None:
        posted = await client.post(
            f"/api/v1/cost-sheets/{sheet['id']}/post",
            headers={**headers, "If-Match": str(sheet["version"])},
            json={"version": sheet["version"]},
        )
        assert posted.status_code == 200, posted.text
        sheet = posted.json()["data"]
    assert sheet.get("journal_entry_id") is not None
    doc_date = sheet["document_date"]
    statement = await client.get(
        "/api/v1/reports/account-statement",
        headers=headers,
        params={
            "account_id": expense_account,
            "from": doc_date,
            "to": doc_date,
        },
    )
    assert statement.status_code == 200, statement.text
    data = statement.json()["data"]
    cs_lines = [line for line in data["lines"] if line.get("voucher_code") == "CSI"]
    assert len(cs_lines) == 2
    debits = sorted(Decimal(line["debit"]) for line in cs_lines)
    assert debits == [Decimal("10.0000"), Decimal("20.0000")]


@pytest.mark.asyncio
async def test_account_statement_cost_sheet_credit_on_expense_account(
    client: AsyncClient,
) -> None:
    """Expense account shows GL debit per cost sheet goods line."""
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books_supplier(client, headers)
    supplier_id = await _create_supplier(client, headers)
    invoice = await _posted_invoice(client, headers)
    listed = await client.get("/api/v1/accounts", headers=headers)
    skip = {"ACCOUNTS_RECEIVABLE", "ACCOUNTS_PAYABLE", "CASH", "BANK"}
    postable = [
        row["id"]
        for row in listed.json()["data"]
        if not row.get("is_group") and row.get("account_subtype") not in skip
    ]
    expense_account = postable[0]
    created = await client.post(
        "/api/v1/cost-sheets",
        headers=headers,
        json={
            "sheet_type": "IMPORT",
            "sheet_mode": "JOURNAL",
            "supplier_id": supplier_id,
            "source_document_type": "SALES_INVOICE",
            "source_document_id": invoice["id"],
            "journal_lines": [
                {
                    "line_kind": "G",
                    "account_id": expense_account,
                    "debit": "55.0000",
                    "credit": "0",
                    "capitalize": False,
                },
                {
                    "line_kind": "S",
                    "party_id": supplier_id,
                    "debit": "0",
                    "credit": "55.0000",
                },
            ],
        },
    )
    assert created.status_code == 201, created.text
    sheet = created.json()["data"]
    doc_date = sheet["document_date"]
    statement = await client.get(
        "/api/v1/reports/account-statement",
        headers=headers,
        params={
            "account_id": expense_account,
            "from": doc_date,
            "to": doc_date,
        },
    )
    assert statement.status_code == 200, statement.text
    data = statement.json()["data"]
    cs_lines = [line for line in data["lines"] if line.get("voucher_code") == "CSI"]
    assert len(cs_lines) == 1
    assert Decimal(cs_lines[0]["debit"]) == Decimal("55.0000")
    assert Decimal(cs_lines[0]["credit"]) == Decimal("0")


@pytest.mark.asyncio
async def test_account_statement_shows_voucher_module_entry_not_gl_jv(
    client: AsyncClient,
) -> None:
    from tests.api.erp.accounting.test_vouchers import _account_by_subtype, _counter_account

    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    cash_account = await _account_by_subtype(client, headers, "CASH")
    counter_account = await _counter_account(client, headers)
    invoice = await _posted_invoice(client, headers)
    created = await client.post(
        "/api/v1/vouchers",
        headers=headers,
        json={
            "voucher_type": "CASH_PAYMENT",
            "payment_account_id": cash_account,
            "total_amount": "60.0000",
            "payment_method": "CASH",
            "lines": [{"account_id": counter_account, "amount": "60.0000"}],
            "source_document_type": "SALES_INVOICE",
            "source_document_id": invoice["id"],
        },
    )
    assert created.status_code == 201, created.text
    voucher = created.json()["data"]
    assert voucher["status"] == "POSTED"
    assert voucher["journal_entry_id"] is not None
    journal = await client.get(
        f"/api/v1/journals/{voucher['journal_entry_id']}", headers=headers
    )
    assert journal.status_code == 200, journal.text
    journal_body = journal.json()["data"]
    assert journal_body["source_type"] == "cash_payment_voucher"
    assert journal_body["document_number"] == voucher["document_number"]
    assert journal_body["document_number"].startswith("CPV")

    voucher_date = voucher["voucher_date"]
    statement = await client.get(
        "/api/v1/reports/account-statement",
        headers=headers,
        params={
            "account_id": cash_account,
            "from": voucher_date,
            "to": voucher_date,
        },
    )
    assert statement.status_code == 200, statement.text
    data = statement.json()["data"]
    cp_lines = [
        line
        for line in data["lines"]
        if line.get("source_type") == "cash_payment_voucher"
    ]
    assert len(cp_lines) == 1
    assert cp_lines[0]["voucher_code"] == "CP"
    assert cp_lines[0]["document_number"] == voucher["document_number"]
    assert Decimal(cp_lines[0]["credit"]) == Decimal("60.0000")


@pytest.mark.asyncio
async def test_customer_statement_includes_period_totals(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books(client, headers)
    invoice = await _posted_invoice(client, headers)
    customer_id = invoice["customer_id"]
    from_date = invoice["invoice_date"]
    statement = await client.get(
        "/api/v1/reports/customer-statement",
        headers=headers,
        params={"customer_id": customer_id, "from": from_date, "to": from_date},
    )
    assert statement.status_code == 200, statement.text
    data = statement.json()["data"]
    assert data["account_code"]
    assert Decimal(data["total_debit"]) > 0
    assert Decimal(data["total_credit"]) == Decimal("0")
    si_lines = [line for line in data["lines"] if line["type_code"] == "SI"]
    assert len(si_lines) == 1


@pytest.mark.asyncio
async def test_supplier_statement_legacy_po_credit_skips_linked_pi(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books_supplier(client, headers)
    ctx = await _issue_tracked_po(client, headers, quantity="2")
    order = ctx["order"]
    supplier_id = ctx["supplier_id"]
    po_total = Decimal(str(order["grand_total"]))
    order_date = order["order_date"]

    created_grn = await _create_from_po(client, headers, order["id"])
    posted_grn = await _post_grn(
        client,
        headers,
        created_grn["body"]["data"]["id"],
        created_grn["body"]["data"]["version"],
    )
    assert posted_grn.status_code == 200, posted_grn.text
    grn = posted_grn.json()["data"]
    goods = await client.post(
        "/api/v1/purchase-invoices/from-goods-receipt",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={"goods_receipt_id": grn["id"]},
    )
    assert goods.status_code == 201, goods.text
    posted_bill = await client.post(
        f"/api/v1/purchase-invoices/{goods.json()['data']['id']}/post",
        headers=_gr_idempotent(headers, goods.json()["data"]["version"]),
    )
    assert posted_bill.status_code == 200, posted_bill.text
    bill_date = posted_bill.json()["data"]["invoice_date"]

    statement = await client.get(
        "/api/v1/reports/supplier-statement",
        headers=headers,
        params={"supplier_id": supplier_id, "from": order_date, "to": bill_date},
    )
    assert statement.status_code == 200, statement.text
    data = statement.json()["data"]
    po_lines = [line for line in data["lines"] if line["type_code"] == "PO"]
    pi_lines = [line for line in data["lines"] if line["type_code"] == "PI"]
    assert len(po_lines) == 1
    assert Decimal(po_lines[0]["credit"]) == po_total
    assert pi_lines == []


@pytest.mark.asyncio
async def test_supplier_statement_opening_ap_ob_line(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books_supplier(client, headers)
    today = datetime.now(UTC).date()
    supplier_id = await _create_supplier(client, headers, tax_treatment="UNREGISTERED", trn=None)
    committed = await client.post(
        "/api/v1/opening-balances/commit",
        headers={**headers, "Idempotency-Key": uuid4().hex},
        json={
            "books_start_date": today.isoformat(),
            "gl_lines": [],
            "ar_items": [],
            "ap_items": [
                {
                    "party_id": supplier_id,
                    "amount": "125.0000",
                    "due_date": today.isoformat(),
                    "external_reference": "OB-STMT-AP",
                }
            ],
            "stock_lines": [],
        },
    )
    assert committed.status_code == 200, committed.text
    from_date = (today - timedelta(days=30)).isoformat()
    statement = await client.get(
        "/api/v1/reports/supplier-statement",
        headers=headers,
        params={"supplier_id": supplier_id, "from": from_date, "to": today.isoformat()},
    )
    assert statement.status_code == 200, statement.text
    ob_lines = [line for line in statement.json()["data"]["lines"] if line["type_code"] == "OB"]
    assert len(ob_lines) == 1
    assert Decimal(ob_lines[0]["credit"]) == Decimal("125.0000")


@pytest.mark.asyncio
async def test_supplier_statement_refund_sr_credit(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    await _enable_books_supplier(client, headers)
    accounts = await _accounts(client, headers)
    supplier_id = await _create_supplier(client, headers)
    created = await client.post(
        "/api/v1/supplier-payments",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "amount_paid": "50.0000",
            "payment_account_id": accounts["BANK"],
            "payment_method": "TT",
            "allocations": [],
        },
    )
    assert created.status_code == 201, created.text
    pay_row = created.json()["data"]
    posted = await client.post(
        f"/api/v1/supplier-payments/{pay_row['id']}/post",
        headers={**headers, "If-Match": str(pay_row["version"]), "Idempotency-Key": uuid4().hex},
    )
    assert posted.status_code == 200, posted.text
    posted_row = posted.json()["data"]
    refunded = await client.post(
        f"/api/v1/supplier-payments/{posted_row['id']}/refund",
        headers={**headers, "If-Match": str(posted_row["version"]), "Idempotency-Key": uuid4().hex},
    )
    assert refunded.status_code == 200, refunded.text
    refund_date = refunded.json()["data"]["refunded_at"][:10]
    statement = await client.get(
        "/api/v1/reports/supplier-statement",
        headers=headers,
        params={"supplier_id": supplier_id, "from": refund_date, "to": refund_date},
    )
    assert statement.status_code == 200, statement.text
    sr_lines = [line for line in statement.json()["data"]["lines"] if line["type_code"] == "SR"]
    assert len(sr_lines) == 1
    assert Decimal(sr_lines[0]["credit"]) == Decimal("50.0000")
