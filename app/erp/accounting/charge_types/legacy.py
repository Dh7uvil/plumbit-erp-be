"""Map charge type codes to legacy expense_category values."""

from app.core.enums import ExpenseCategory

_LEGACY_BY_CODE: dict[str, ExpenseCategory] = {
    "FREIGHT": ExpenseCategory.FREIGHT,
    "CUSTOMS_DUTY": ExpenseCategory.CUSTOMS_DUTY,
    "INSURANCE": ExpenseCategory.INSURANCE,
    "CUSTOMS_CLEARANCE": ExpenseCategory.CLEARING,
    "INSPECTION": ExpenseCategory.INSPECTION,
    "OTHER_CHARGES": ExpenseCategory.OTHER,
}

_LEGACY_BY_EXPENSE: dict[ExpenseCategory, str] = {
    ExpenseCategory.FREIGHT: "FREIGHT",
    ExpenseCategory.CUSTOMS_DUTY: "CUSTOMS_DUTY",
    ExpenseCategory.INSURANCE: "INSURANCE",
    ExpenseCategory.CLEARING: "CUSTOMS_CLEARANCE",
    ExpenseCategory.INSPECTION: "INSPECTION",
    ExpenseCategory.OTHER: "OTHER_CHARGES",
}


def legacy_expense_category(code: str) -> ExpenseCategory:
    return _LEGACY_BY_CODE.get(code, ExpenseCategory.OTHER)


def charge_code_for_expense(category: ExpenseCategory) -> str:
    return _LEGACY_BY_EXPENSE.get(category, "OTHER_CHARGES")
