from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.loans.schemas import InterestMethod, RepaymentCadence
from app.modules.loans.servicing import (
    LoanServicingService,
    add_months,
    build_schedule,
    installment_count,
    resolve_tenure_months,
)

START = date(2026, 1, 31)


def total(lines, attr="amount"):
    return sum((getattr(line, attr) for line in lines), Decimal("0"))


class TestFlat:
    def test_totals_are_exact(self):
        lines = build_schedule(
            principal=Decimal("100000"), monthly_rate_pct=Decimal("8"), tenure_months=3,
            cadence=RepaymentCadence.MONTHLY, method=InterestMethod.FLAT, start=START,
        )
        assert len(lines) == 3
        assert total(lines, "principal") == Decimal("100000.00")
        assert total(lines, "interest") == Decimal("24000.00")  # 100k x 8% x 3
        # 100000/3 doesn't divide: last installment absorbs the kobo.
        assert [line.principal for line in lines] == [Decimal("33333.33"), Decimal("33333.33"), Decimal("33333.34")]

    def test_zero_rate(self):
        lines = build_schedule(
            principal=Decimal("1000"), monthly_rate_pct=Decimal("0"), tenure_months=2,
            cadence=RepaymentCadence.MONTHLY, method=InterestMethod.REDUCING_BALANCE, start=START,
        )
        assert total(lines, "interest") == 0
        assert total(lines) == Decimal("1000.00")


class TestReducingBalance:
    def test_level_installments_and_declining_interest(self):
        lines = build_schedule(
            principal=Decimal("100000"), monthly_rate_pct=Decimal("8"), tenure_months=6,
            cadence=RepaymentCadence.MONTHLY, method=InterestMethod.REDUCING_BALANCE, start=START,
        )
        assert total(lines, "principal") == Decimal("100000.00")
        # Standard annuity: 100000 * 0.08 / (1 - 1.08^-6) = 21631.54
        assert all(abs(line.amount - Decimal("21631.54")) <= Decimal("0.05") for line in lines)
        interests = [line.interest for line in lines]
        assert interests == sorted(interests, reverse=True)
        assert interests[0] == Decimal("8000.00")  # first month on the full balance

    def test_cheaper_than_flat(self):
        common = dict(principal=Decimal("100000"), monthly_rate_pct=Decimal("8"), tenure_months=6,
                      cadence=RepaymentCadence.MONTHLY, start=START)
        flat = build_schedule(method=InterestMethod.FLAT, **common)
        reducing = build_schedule(method=InterestMethod.REDUCING_BALANCE, **common)
        assert total(reducing, "interest") < total(flat, "interest")


class TestCadence:
    @pytest.mark.parametrize(
        ("cadence", "months", "expected"),
        [
            (RepaymentCadence.MONTHLY, 6, 6),
            (RepaymentCadence.SALARY_DATE, 4, 4),
            (RepaymentCadence.WEEKLY, 6, 26),  # ceil(180 / 7)
            (RepaymentCadence.DAILY, 1, 30),
        ],
    )
    def test_installment_count(self, cadence, months, expected):
        assert installment_count(months, cadence) == expected

    def test_weekly_dates(self):
        lines = build_schedule(
            principal=Decimal("7000"), monthly_rate_pct=Decimal("5"), tenure_months=1,
            cadence=RepaymentCadence.WEEKLY, method=InterestMethod.FLAT, start=date(2026, 3, 2),
        )
        assert [line.due_date for line in lines[:2]] == [date(2026, 3, 9), date(2026, 3, 16)]

    def test_month_end_is_clamped(self):
        assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
        assert add_months(date(2026, 1, 31), 3) == date(2026, 4, 30)

    def test_salary_day(self):
        lines = build_schedule(
            principal=Decimal("50000"), monthly_rate_pct=Decimal("8"), tenure_months=2,
            cadence=RepaymentCadence.SALARY_DATE, method=InterestMethod.FLAT,
            start=date(2026, 5, 10), salary_day=25,
        )
        assert [line.due_date for line in lines] == [date(2026, 6, 25), date(2026, 7, 25)]


class TestTenureResolution:
    def _app(self, **kw):
        base = dict(approved_tenure_months=None, product_data={}, universal_form={})
        base.update(kw)
        return SimpleNamespace(**base)

    def test_staff_approved_wins(self):
        assert resolve_tenure_months(self._app(approved_tenure_months=4, product_data={"tenure_months": 9})) == 4

    @pytest.mark.parametrize(
        ("text", "months"),
        [("6 months", 6), ("12 Months", 12), ("8 weeks", 2), ("90 days", 3), ("as agreed", None)],
    )
    def test_parses_free_text_period(self, text, months):
        assert resolve_tenure_months(self._app(universal_form={"repayment_period": text})) == months


class TestAllocation:
    def _line(self, n, principal, interest, principal_paid="0", interest_paid="0"):
        return SimpleNamespace(
            installment=n, principal=Decimal(principal), interest=Decimal(interest),
            principal_paid=Decimal(principal_paid), interest_paid=Decimal(interest_paid),
        )

    def test_interest_first_then_principal_oldest_first(self):
        schedule = [self._line(2, "100", "20"), self._line(1, "100", "20")]
        allocations = LoanServicingService.allocate(schedule, Decimal("150"))
        assert [(a.installment, a.interest, a.principal) for a in allocations] == [
            (1, Decimal("20"), Decimal("100")),
            (2, Decimal("20"), Decimal("10")),
        ]

    def test_skips_paid_installments(self):
        schedule = [self._line(1, "100", "20", "100", "20"), self._line(2, "100", "20")]
        allocations = LoanServicingService.allocate(schedule, Decimal("30"))
        assert allocations[0].installment == 2


class TestOneOffCharge:
    """LPO / invoice financing: 7% once, repaid in one go when the contract is paid."""

    def test_end_of_term_is_one_repayment_with_the_charge_once(self):
        lines = build_schedule(
            principal=Decimal("500000"), monthly_rate_pct=Decimal("7"), tenure_months=4,
            cadence=RepaymentCadence.END_OF_TERM, method=InterestMethod.ONE_OFF, start=START,
        )
        assert len(lines) == 1
        assert lines[0].due_date == add_months(START, 4)
        assert (lines[0].principal, lines[0].interest) == (Decimal("500000.00"), Decimal("35000.00"))

    def test_one_off_doesnt_grow_with_the_tenure(self):
        lines = build_schedule(
            principal=Decimal("300000"), monthly_rate_pct=Decimal("7"), tenure_months=3,
            cadence=RepaymentCadence.MONTHLY, method=InterestMethod.ONE_OFF, start=START,
        )
        assert len(lines) == 3 and total(lines, "interest") == Decimal("21000.00")

    def test_end_of_term_counts_one_installment(self):
        assert installment_count(9, RepaymentCadence.END_OF_TERM) == 1
