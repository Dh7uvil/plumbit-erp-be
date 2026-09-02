from app.auth.org_repository import next_employee_code_from_existing


def test_first_employee_code_is_padded_01() -> None:
    assert next_employee_code_from_existing([], 2026) == "EMP202601"


def test_sequence_increments_with_two_digit_padding() -> None:
    assert next_employee_code_from_existing(["EMP202601"], 2026) == "EMP202602"


def test_prior_year_codes_do_not_affect_current_year() -> None:
    assert next_employee_code_from_existing(["EMP202599"], 2026) == "EMP202601"


def test_sequence_grows_past_two_digits() -> None:
    assert next_employee_code_from_existing(["EMP202699"], 2026) == "EMP2026100"
