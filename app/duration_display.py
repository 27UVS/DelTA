"""
Отображение длительности в днях с разбиением на годы и месяцы фиксированной длины.

Правило (по запросу UI): 1 год = 365 суток, 1 месяц = 30 суток; остаток — в днях.
Декомпозиция «жадная»: сначала годы из полных 365, затем месяцы из полных 30 в остатке.
"""


APPROX_DAYS_PER_YEAR = 365
APPROX_DAYS_PER_MONTH = 30


def format_approx_ymd(total_days: int) -> str:
    """
    Примеры: 452 → «1 г., 2 мес., 27 дн.»; 8 → «8 дн.»; 365 → «1 г.»
    Нулевые части не показываются (кроме полного нуля → «0 дн.»).
    """
    n = max(0, int(total_days))
    if n == 0:
        return "0 дн."
    years, rem = divmod(n, APPROX_DAYS_PER_YEAR)
    months, days = divmod(rem, APPROX_DAYS_PER_MONTH)
    parts: list[str] = []
    if years:
        parts.append(f"{years} г.")
    if months:
        parts.append(f"{months} мес.")
    if days:
        parts.append(f"{days} дн.")
    # Для любого n >= 1 набор непуст (хотя бы один из г/мес/дней).
    return ", ".join(parts)
