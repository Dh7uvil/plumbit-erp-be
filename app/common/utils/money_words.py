"""Convert a money amount into English words for print DTOs."""

from decimal import Decimal, ROUND_HALF_UP

_ONES = (
    "",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
)
_TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")
_SCALES = ("", "Thousand", "Million", "Billion", "Trillion")


def amount_in_words(amount: Decimal, *, currency_code: str | None = None) -> str:
    quantized = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    negative = quantized < 0
    quantized = abs(quantized)
    whole = int(quantized)
    fils = int((quantized - Decimal(whole)) * 100)
    words = _integer_to_words(whole) if whole else "Zero"
    currency = (currency_code or "AED").upper()
    subunit = "Fils" if currency == "AED" else "Cents"
    major = f"{words} {currency}"
    if fils:
        major = f"{major} and {_integer_to_words(fils)} {subunit}"
    major = f"{major} Only"
    if negative:
        return f"Minus {major}"
    return major


def _integer_to_words(value: int) -> str:
    if value == 0:
        return "Zero"
    parts: list[str] = []
    scale = 0
    remaining = value
    while remaining:
        chunk = remaining % 1000
        remaining //= 1000
        if chunk:
            rendered = _chunk_to_words(chunk)
            if _SCALES[scale]:
                rendered = f"{rendered} {_SCALES[scale]}"
            parts.append(rendered)
        scale += 1
    return " ".join(reversed(parts))


def _chunk_to_words(value: int) -> str:
    hundreds, remainder = divmod(value, 100)
    words: list[str] = []
    if hundreds:
        words.append(f"{_ONES[hundreds]} Hundred")
    if remainder < 20:
        if remainder:
            words.append(_ONES[remainder])
    else:
        tens, ones = divmod(remainder, 10)
        words.append(_TENS[tens])
        if ones:
            words.append(_ONES[ones])
    return " ".join(words)
