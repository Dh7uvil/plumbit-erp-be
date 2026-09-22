"""Seed the sixteen standard import/export charge types per tenant."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AccountSystemRole, ChargeAppliesTo, LandedCostAllocationMethod
from app.erp.accounting.accounts.models import Account
from app.erp.accounting.charge_types.models import ChargeType

# (code, name, sort_order, is_inventoriable, system_role, allocation_basis, applies_to)
_CHARGE_SEED: tuple[
    tuple[
        str, str, int, bool, AccountSystemRole, LandedCostAllocationMethod | None, ChargeAppliesTo
    ],
    ...,
] = (
    (
        "FREIGHT",
        "Freight",
        10,
        True,
        AccountSystemRole.FREIGHT_IN,
        None,
        ChargeAppliesTo.IMPORT,
    ),
    (
        "INSURANCE",
        "Insurance",
        20,
        True,
        AccountSystemRole.OTHER_CHARGES,
        None,
        ChargeAppliesTo.IMPORT,
    ),
    (
        "CUSTOMS_DUTY",
        "Customs Duty",
        30,
        True,
        AccountSystemRole.CUSTOMS_DUTY,
        None,
        ChargeAppliesTo.IMPORT,
    ),
    (
        "CUSTOMS_CLEARANCE",
        "Customs Clearance",
        40,
        True,
        AccountSystemRole.OTHER_CHARGES,
        None,
        ChargeAppliesTo.IMPORT,
    ),
    (
        "PORT_CHARGES",
        "Port Charges",
        50,
        True,
        AccountSystemRole.OTHER_CHARGES,
        None,
        ChargeAppliesTo.IMPORT,
    ),
    (
        "TERMINAL_HANDLING",
        "Terminal Handling",
        60,
        True,
        AccountSystemRole.OTHER_CHARGES,
        LandedCostAllocationMethod.QUANTITY,
        ChargeAppliesTo.IMPORT,
    ),
    (
        "DOCUMENTATION",
        "Documentation Charges",
        70,
        True,
        AccountSystemRole.OTHER_CHARGES,
        None,
        ChargeAppliesTo.BOTH,
    ),
    (
        "LOADING",
        "Loading Charges",
        80,
        True,
        AccountSystemRole.OTHER_CHARGES,
        LandedCostAllocationMethod.QUANTITY,
        ChargeAppliesTo.BOTH,
    ),
    (
        "UNLOADING",
        "Unloading Charges",
        90,
        True,
        AccountSystemRole.OTHER_CHARGES,
        LandedCostAllocationMethod.QUANTITY,
        ChargeAppliesTo.BOTH,
    ),
    (
        "TRANSPORTATION",
        "Transportation / Delivery",
        100,
        True,
        AccountSystemRole.OTHER_CHARGES,
        LandedCostAllocationMethod.VOLUME,
        ChargeAppliesTo.BOTH,
    ),
    (
        "DEMURRAGE",
        "Demurrage",
        110,
        False,
        AccountSystemRole.OTHER_CHARGES,
        None,
        ChargeAppliesTo.IMPORT,
    ),
    (
        "DETENTION",
        "Detention",
        120,
        False,
        AccountSystemRole.OTHER_CHARGES,
        None,
        ChargeAppliesTo.IMPORT,
    ),
    ("STORAGE", "Storage", 130, False, AccountSystemRole.OTHER_CHARGES, None, ChargeAppliesTo.BOTH),
    (
        "INSPECTION",
        "Inspection Charges",
        140,
        True,
        AccountSystemRole.OTHER_CHARGES,
        None,
        ChargeAppliesTo.IMPORT,
    ),
    (
        "BANK_CHARGES",
        "Bank Charges",
        150,
        False,
        AccountSystemRole.BANK_CHARGES,
        None,
        ChargeAppliesTo.BOTH,
    ),
    (
        "OTHER_CHARGES",
        "Other Charges",
        160,
        True,
        AccountSystemRole.OTHER_CHARGES,
        None,
        ChargeAppliesTo.BOTH,
    ),
)


async def _account_for_role(
    session: AsyncSession, tenant_id: UUID, role: AccountSystemRole
) -> UUID:
    account_id = (
        await session.execute(
            select(Account.id).where(
                Account.tenant_id == tenant_id,
                Account.system_role == role.value,
                Account.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    return account_id


async def seed_charge_types(session: AsyncSession, tenant_id: UUID) -> None:
    """Insert missing charge types; never overwrite accountant edits."""

    existing_codes = set(
        (
            await session.execute(
                select(ChargeType.code).where(
                    ChargeType.tenant_id == tenant_id,
                    ChargeType.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for (
        code,
        name,
        sort_order,
        is_inventoriable,
        system_role,
        allocation_basis,
        applies_to,
    ) in _CHARGE_SEED:
        if code in existing_codes:
            continue
        default_account_id = await _account_for_role(session, tenant_id, system_role)
        session.add(
            ChargeType(
                tenant_id=tenant_id,
                code=code,
                name=name,
                sort_order=sort_order,
                is_inventoriable=is_inventoriable,
                default_account_id=default_account_id,
                allocation_basis=(None if allocation_basis is None else allocation_basis.value),
                applies_to=applies_to.value,
                is_active=True,
            )
        )
