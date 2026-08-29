"""API tests for administration identity and organization endpoints."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import event

from app.db.session import engine
from tests.conftest import login_headers, provision_admin


async def _create_limited_user(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    permission_code: str,
) -> tuple[str, str]:
    permissions = await client.get("/api/v1/permissions?page_size=100", headers=headers)
    assert permissions.status_code == 200, permissions.text
    permission_id = next(
        item["id"] for item in permissions.json()["data"] if item["code"] == permission_code
    )
    suffix = uuid4().hex[:8]
    email = f"limited-{suffix}@example.com"
    password = "password12"
    role = await client.post(
        "/api/v1/roles",
        headers=headers,
        json={"name": f"Limited {suffix}", "permission_ids": [permission_id]},
    )
    assert role.status_code == 201, role.text
    user = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "name": "Limited User",
            "email": email,
            "password": password,
            "role_ids": [role.json()["data"]["id"]],
        },
    )
    assert user.status_code == 201, user.text
    return email, password


@pytest.mark.asyncio
async def test_user_list_includes_roles_without_n_plus_one(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)

    for index in range(3):
        created = await client.post(
            "/api/v1/users",
            headers=headers,
            json={
                "name": f"User {index}",
                "email": f"user-{index}-{uuid4().hex[:6]}@example.com",
                "password": "password12",
            },
        )
        assert created.status_code == 201, created.text

    statements: list[str] = []

    def before_cursor_execute(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
    try:
        response = await client.get("/api/v1/users", headers=headers)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before_cursor_execute)

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload
    assert "roles" in payload[0]
    assert len(statements) < 12


@pytest.mark.asyncio
async def test_user_list_filters_by_role_id(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    suffix = uuid4().hex[:8]
    role = await client.post(
        "/api/v1/roles",
        headers=headers,
        json={"name": f"Filter Role {suffix}"},
    )
    assert role.status_code == 201, role.text
    role_id = role.json()["data"]["id"]

    matched = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "name": "With Role",
            "email": f"with-role-{suffix}@example.com",
            "password": "password12",
            "role_ids": [role_id],
        },
    )
    assert matched.status_code == 201, matched.text
    unmatched = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "name": "Without Role",
            "email": f"without-role-{suffix}@example.com",
            "password": "password12",
        },
    )
    assert unmatched.status_code == 201, unmatched.text

    response = await client.get(f"/api/v1/users?role_id={role_id}", headers=headers)
    assert response.status_code == 200, response.text
    ids = {item["id"] for item in response.json()["data"]}
    assert matched.json()["data"]["id"] in ids
    assert unmatched.json()["data"]["id"] not in ids

    other_role = await client.post(
        "/api/v1/roles",
        headers=headers,
        json={"name": f"Other Role {suffix}"},
    )
    assert other_role.status_code == 201, other_role.text
    other_role_id = other_role.json()["data"]["id"]
    second = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "name": "Second Role",
            "email": f"second-role-{suffix}@example.com",
            "password": "password12",
            "role_ids": [other_role_id],
        },
    )
    assert second.status_code == 201, second.text
    multi = await client.get(
        f"/api/v1/users?role_ids={role_id}&role_ids={other_role_id}",
        headers=headers,
    )
    assert multi.status_code == 200, multi.text
    multi_ids = {item["id"] for item in multi.json()["data"]}
    assert matched.json()["data"]["id"] in multi_ids
    assert second.json()["data"]["id"] in multi_ids
    assert unmatched.json()["data"]["id"] not in multi_ids


@pytest.mark.asyncio
async def test_user_list_filters_by_employee_and_profile_fields(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    suffix = uuid4().hex[:8]
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    manager_id = me.json()["data"]["id"]

    branch = await client.post(
        "/api/v1/branches",
        headers=headers,
        json={"name": "Dubai", "code": f"DXB-{suffix[:4]}"},
    )
    assert branch.status_code == 201, branch.text
    branch_id = branch.json()["data"]["id"]
    other_branch = await client.post(
        "/api/v1/branches",
        headers=headers,
        json={"name": "Sharjah", "code": f"SHJ-{suffix[:4]}"},
    )
    assert other_branch.status_code == 201, other_branch.text
    department = await client.post(
        "/api/v1/departments",
        headers=headers,
        json={
            "name": "Sales",
            "code": f"SAL-{suffix[:4]}",
            "branch_id": branch_id,
            "manager_id": manager_id,
        },
    )
    assert department.status_code == 201, department.text
    department_id = department.json()["data"]["id"]
    other_department = await client.post(
        "/api/v1/departments",
        headers=headers,
        json={
            "name": "Ops",
            "code": f"OPS-{suffix[:4]}",
            "branch_id": other_branch.json()["data"]["id"],
        },
    )
    assert other_department.status_code == 201, other_department.text

    matched = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "name": "Sales Manager",
            "email": f"sales-{suffix}@example.com",
            "password": "password12",
            "phone": "+971501234567",
            "employee": {
                "employee_code": f"E-SALES-{suffix[:6]}",
                "branch_id": branch_id,
                "department_id": department_id,
                "designation": "Sales Manager",
                "joining_date": "2026-01-15",
            },
        },
    )
    assert matched.status_code == 201, matched.text
    unmatched = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "name": "Ops Lead",
            "email": f"ops-{suffix}@example.com",
            "password": "password12",
            "phone": "+971509999999",
            "employee": {
                "employee_code": f"E-OPS-{suffix[:6]}",
                "branch_id": other_branch.json()["data"]["id"],
                "department_id": other_department.json()["data"]["id"],
                "designation": "Operations Lead",
                "joining_date": "2025-06-01",
            },
        },
    )
    assert unmatched.status_code == 201, unmatched.text
    matched_id = matched.json()["data"]["id"]
    unmatched_id = unmatched.json()["data"]["id"]

    async def listed_ids(query: str) -> set[str]:
        response = await client.get(f"/api/v1/users?{query}", headers=headers)
        assert response.status_code == 200, response.text
        return {item["id"] for item in response.json()["data"]}

    department_ids = await listed_ids(f"department_id={department_id}")
    assert matched_id in department_ids
    assert unmatched_id not in department_ids

    branch_ids = await listed_ids(f"branch_id={branch_id}")
    assert matched_id in branch_ids
    assert unmatched_id not in branch_ids

    designation_ids = await listed_ids("designation=Sales")
    assert matched_id in designation_ids
    assert unmatched_id not in designation_ids

    joining_ids = await listed_ids("joining_date=2026-01-15")
    assert matched_id in joining_ids
    assert unmatched_id not in joining_ids

    joining_range_ids = await listed_ids("joining_date_from=2026-01-01&joining_date_to=2026-01-31")
    assert matched_id in joining_range_ids
    assert unmatched_id not in joining_range_ids

    employee_status_ids = await listed_ids("employee_status=ACTIVE")
    assert matched_id in employee_status_ids
    assert unmatched_id in employee_status_ids

    code_ids = await listed_ids(f"employee_code=E-SALES-{suffix[:6]}")
    assert matched_id in code_ids
    assert unmatched_id not in code_ids

    phone_ids = await listed_ids("phone=501234")
    assert matched_id in phone_ids
    assert unmatched_id not in phone_ids

    manager_ids = await listed_ids(f"manager_id={manager_id}")
    assert matched_id in manager_ids
    assert unmatched_id not in manager_ids

    last_login_ids = await listed_ids("last_login_from=2020-01-01T00:00:00Z")
    assert manager_id in last_login_ids
    assert matched_id not in last_login_ids


@pytest.mark.asyncio
async def test_activate_and_deactivate_user(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    created = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "name": "Staff",
            "email": f"staff-{uuid4().hex[:8]}@example.com",
            "password": "password12",
        },
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["data"]["id"]

    deactivated = await client.post(f"/api/v1/users/{user_id}/deactivate", headers=headers)
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["data"]["status"] == "DISABLED"

    activated = await client.post(f"/api/v1/users/{user_id}/activate", headers=headers)
    assert activated.status_code == 200, activated.text
    assert activated.json()["data"]["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_nested_employee_on_user_create(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    branch = await client.post(
        "/api/v1/branches",
        headers=headers,
        json={"name": "Dubai", "code": f"DXB-{uuid4().hex[:4]}", "address": {"city": "Dubai"}},
    )
    assert branch.status_code == 201, branch.text
    department = await client.post(
        "/api/v1/departments",
        headers=headers,
        json={
            "name": "Sales",
            "code": f"SAL-{uuid4().hex[:4]}",
            "branch_id": branch.json()["data"]["id"],
        },
    )
    assert department.status_code == 201, department.text
    created = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "name": "Employee User",
            "email": f"emp-{uuid4().hex[:8]}@example.com",
            "password": "password12",
            "employee": {
                "employee_code": f"E-{uuid4().hex[:6]}",
                "branch_id": branch.json()["data"]["id"],
                "department_id": department.json()["data"]["id"],
                "designation": "Manager",
                "joining_date": "2026-01-15",
            },
        },
    )
    assert created.status_code == 201, created.text
    employee = created.json()["data"]["employee"]
    assert employee is not None
    assert employee["designation"] == "Manager"
    assert employee["department"]["name"] == "Sales"
    assert employee["branch"]["name"] == "Dubai"


@pytest.mark.asyncio
async def test_reset_permissions_rejects_non_system_role(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    role = await client.post(
        "/api/v1/roles",
        headers=headers,
        json={"name": f"Custom {uuid4().hex[:6]}", "permission_ids": []},
    )
    assert role.status_code == 201, role.text
    reset = await client.post(
        f"/api/v1/roles/{role.json()['data']['id']}/permissions/reset",
        headers=headers,
    )
    assert reset.status_code == 422
    assert reset.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_reset_admin_permissions_restores_catalog(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    roles = await client.get("/api/v1/roles", headers=headers)
    admin = next(item for item in roles.json()["data"] if item["is_system_role"])
    assert admin["name"] == "Superadmin"
    reset = await client.post(
        f"/api/v1/roles/{admin['id']}/permissions/reset",
        headers=headers,
    )
    assert reset.status_code == 200, reset.text
    codes = {item["code"] for item in reset.json()["data"]["permissions"]}
    assert "identity.audit_log.read" in codes
    assert "identity.organization.update" in codes
    matrix = await client.get(
        f"/api/v1/permissions/matrix?role_id={admin['id']}",
        headers=headers,
    )
    assert matrix.status_code == 200, matrix.text
    granted = [
        action
        for module in matrix.json()["data"]["modules"]
        for resource in module["resources"]
        for action in resource["actions"]
        if action["granted"]
    ]
    assert granted


@pytest.mark.asyncio
async def test_permission_denied_on_branches(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    limited_email, limited_password = await _create_limited_user(
        client,
        headers,
        permission_code="identity.user.read",
    )
    limited_headers = await login_headers(client, tenant_id, limited_email, limited_password)
    response = await client.get("/api/v1/branches", headers=limited_headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_tenant_isolation_on_branches(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)

    created = await client.post(
        "/api/v1/branches",
        headers=headers_b,
        json={"name": "Secret Branch", "code": f"SEC-{uuid4().hex[:4]}"},
    )
    assert created.status_code == 201, created.text
    branch_id = created.json()["data"]["id"]

    missing = await client.get(f"/api/v1/branches/{branch_id}", headers=headers_a)
    assert missing.status_code == 404
    listed = await client.get("/api/v1/branches", headers=headers_a)
    assert listed.status_code == 200
    assert all(item["id"] != branch_id for item in listed.json()["data"])


@pytest.mark.asyncio
async def test_tenant_isolation_on_departments_and_audit_logs(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)

    branch = await client.post(
        "/api/v1/branches",
        headers=headers_b,
        json={"name": "HQ", "code": f"HQ-{uuid4().hex[:4]}"},
    )
    assert branch.status_code == 201, branch.text
    department = await client.post(
        "/api/v1/departments",
        headers=headers_b,
        json={
            "name": "Finance",
            "code": f"FIN-{uuid4().hex[:4]}",
            "branch_id": branch.json()["data"]["id"],
        },
    )
    assert department.status_code == 201, department.text
    missing = await client.get(
        f"/api/v1/departments/{department.json()['data']['id']}",
        headers=headers_a,
    )
    assert missing.status_code == 404

    logs_a = await client.get("/api/v1/audit-logs", headers=headers_a)
    logs_b = await client.get("/api/v1/audit-logs", headers=headers_b)
    assert logs_a.status_code == 200
    assert logs_b.status_code == 200
    ids_a = {item["id"] for item in logs_a.json()["data"]}
    ids_b = {item["id"] for item in logs_b.json()["data"]}
    assert ids_a.isdisjoint(ids_b)


@pytest.mark.asyncio
async def test_failed_login_writes_audit_and_summary(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    failed = await client.post(
        "/api/v1/auth/login",
        json={"tenant_id": tenant_id, "email": email, "password": "wrong-password"},
    )
    assert failed.status_code == 401

    headers = await login_headers(client, tenant_id, email, password)
    summary = await client.get("/api/v1/audit-logs/summary", headers=headers)
    assert summary.status_code == 200, summary.text
    assert summary.json()["data"]["failed_attempts"] >= 1
    logs = await client.get("/api/v1/audit-logs?action=LOGIN", headers=headers)
    assert logs.status_code == 200
    assert any(item["status"] == "FAILED" for item in logs.json()["data"])


@pytest.mark.asyncio
async def test_current_tenant_round_trip(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    updated = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={
            "name": "Updated Org",
            "timezone": "Asia/Dubai",
            "industry": "Plumbing",
            "default_currency": "aed",
            "headquarters": {"city": "Dubai", "country": "UAE"},
        },
    )
    assert updated.status_code == 200, updated.text
    data = updated.json()["data"]
    assert data["name"] == "Updated Org"
    assert data["timezone"] == "Asia/Dubai"
    assert data["default_currency"] == "AED"
    assert data["headquarters"]["city"] == "Dubai"
    assert "users_count" in data
    assert data["logo_url"] is None
    fetched = await client.get("/api/v1/tenants/current", headers=headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["data"]["logo_url"] is None
    assert "warehouses_count" not in data


@pytest.mark.asyncio
async def test_current_tenant_accepts_org_settings_form_payload(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    current = await client.get("/api/v1/tenants/current", headers=headers)
    assert current.status_code == 200, current.text
    currency_id = current.json()["data"]["default_currency_id"]

    company = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={
            "name": "Plumb It",
            "industry": "Plumbing",
            "website": "https://plumbit.example",
            "contact_email": "hello@plumbit.example",
            "phone": None,
            "founded": None,
            "headquarters": None,
        },
    )
    assert company.status_code == 200, company.text

    regional = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={
            "timezone": "Asia/Kolkata",
            "fiscal_year_start": "April 1",
            "default_currency": "INR",
            "default_currency_id": currency_id,
            "quotation_requires_approval": True,
        },
    )
    assert regional.status_code == 200, regional.text
    data = regional.json()["data"]
    assert data["timezone"] == "Asia/Kolkata"
    assert data["fiscal_year_start"] == "April 1"
    assert data["default_currency"] == "INR"
    assert data["quotation_requires_approval"] is True

    cleared = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={
            "timezone": "",
            "fiscal_year_start": "  ",
            "default_currency": "  ",
            "default_currency_id": "none",
        },
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"]["timezone"] == "Asia/Kolkata"
    assert cleared.json()["data"]["fiscal_year_start"] is None
    assert cleared.json()["data"]["default_currency_id"] is None


@pytest.mark.asyncio
async def test_current_tenant_rejects_invalid_contact_email(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    rejected = await client.patch(
        "/api/v1/tenants/current",
        headers=headers,
        json={"contact_email": "not-an-email"},
    )
    assert rejected.status_code == 422, rejected.text
    error = rejected.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "contact_email" in error["details"]
