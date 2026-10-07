"""
End-to-end loan disbursement: submit → approve every stage → disburse →
provider webhook → loan booked + ledger posted. Also covers reconciliation
(missed webhook) and failure paths.
"""

import hashlib
import hmac
import io
import json

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.base import TransactionStatus
from tests.conftest import TEST_TXN_PIN, set_transaction_pin
from app.modules.loans.models import Loan, LoanApplication
from app.modules.loans.schemas import ApplicationStatus
from app.modules.payments.models import (
    JournalType,
    LedgerJournal,
    LoanDisbursement,
    PaymentDirection,
    PaymentTransaction,
)
from app.integrations.monnify.client import MonnifyClient
from app.integrations.payments.schemas import DisbursementResult, PaymentRailError, TransientRailError
from app.modules.loans.models import LoanRepayment, RepaymentSchedule
from app.modules.loans.schemas import InstallmentStatus, LoanStatus
from tests.integration.test_loan_workflow_api import _customer_token, _seed


@pytest.fixture
def pending_rail(monkeypatch):
    """Rail accepts the transfer but settles later (webhook / reconciliation)."""

    async def initiate(self, *, amount, reference, **_):
        return DisbursementResult(reference=reference, status="PENDING", amount=amount, transaction_id="MFDS-P")

    monkeypatch.setattr(MonnifyClient, "initiate_disbursement", initiate)


def rail_raising(monkeypatch, exc: Exception):
    async def initiate(self, **_):
        raise exc

    monkeypatch.setattr(MonnifyClient, "initiate_disbursement", initiate)

async def _login(api_client) -> str:
    """Existing (already registered) customer signs in."""
    from tests.conftest import TEST_OTP

    await api_client.post("/api/v1/auth/login/request-otp", json={"phone": "08035794364"})
    res = await api_client.post(
        "/api/v1/auth/login/verify-otp", json={"phone": "08035794364", "otp": TEST_OTP}
    )
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


UNIVERSAL_FORM = {
    "residential_address": "52 Ijaye Road",
    "bank_name": "GTBank",
    "bank_code": "058",
    "bank_account_name": "Adaeze Okafor",
    "bank_account_number": "0123456789",
    "next_of_kin_name": "John Okafor",
    "next_of_kin_phone": "08030000000",
    "next_of_kin_relationship": "Brother",
    "requested_amount": "500000",
    "purpose": "Stock",
    "monthly_income": "300000",
    "repayment_period": "6 months",
    "source_of_repayment": "Sales",
}

BUSINESS_DOCS = (
    "valid_id", "bvn", "passport_photo", "passport_photo_2", "shop_rent_receipt",
    "cash_flow_proof", "guarantor_id", "guarantor_photo", "collateral_original",
)


def monnify_signed(payload: dict) -> tuple[bytes, dict]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    sig = hmac.new(b"test_monnify_secret", body, hashlib.sha512).hexdigest()
    return body, {"monnify-signature": sig, "Content-Type": "application/json"}


async def submitted_application(api_client, db_session, form=UNIVERSAL_FORM, tenure=6) -> str:
    app_id, headers = await complete_draft(api_client, db_session, form=form, tenure=tenure)
    submitted = await api_client.post(f"/api/v1/loans/me/applications/{app_id}/submit", headers=headers)
    assert submitted.status_code == 200, submitted.text
    return app_id


async def complete_draft(api_client, db_session, form=UNIVERSAL_FORM, tenure=6) -> tuple[str, dict]:
    """A business-loan draft with every field and document in place, not yet submitted."""
    await _seed(db_session)
    headers = {"Authorization": f"Bearer {await _customer_token(api_client)}"}
    app_id = (
        await api_client.post(
            "/api/v1/loans/me/applications", json={"product_code": "business_loan"}, headers=headers
        )
    ).json()["id"]
    patched = await api_client.patch(
        f"/api/v1/loans/me/applications/{app_id}",
        json={
            "step": 6,
            "total_steps": 6,
            "universal_form": form,
            "product_data": {
                "years_in_operation": 5,
                "trade_type": "provisions",
                **({"tenure_months": tenure} if tenure else {}),
            },
            "guarantors": [{"full_name": "Jane Guarantor", "phone": "08021112222", "relationship": "Friend"}],
        },
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    for doc in BUSINESS_DOCS:
        await api_client.post(
            f"/api/v1/loans/me/applications/{app_id}/documents/{doc}",
            headers=headers,
            files={"file": ("d.pdf", io.BytesIO(b"%PDF-1.4 doc"), "application/pdf")},
        )
    return app_id, headers


async def approved_application(
    api_client, db_session, admin_headers, form=UNIVERSAL_FORM, tenure=6, accept_offer=True
) -> str:
    """
    Approved by staff with the offer accepted by the customer, ready to pay out.

    The credit stage sends the offer and the workflow waits for the customer. With
    accept_offer=False this stops there (status offer_sent); finish_approval continues.
    """
    app_id = await submitted_application(api_client, db_session, form=form, tenure=tenure)
    await verify_all_documents(api_client, app_id, admin_headers)
    return await finish_approval(api_client, app_id, admin_headers, accept_offer=accept_offer)


async def finish_approval(api_client, app_id: str, admin_headers, *, accept_offer: bool = True) -> str:
    """Approve the remaining stages, accepting the offer when the workflow waits for it."""
    for _ in range(10):
        status = (
            await api_client.get(f"/api/v1/admin/loans/applications/{app_id}", headers=admin_headers)
        ).json()["status"]
        if status == "approved":
            break
        if status == "offer_sent":
            if not accept_offer:
                return app_id
            await accept_loan_offer(api_client, app_id)
            continue
        res = await api_client.post(
            f"/api/v1/admin/loans/applications/{app_id}/stage-action",
            json={"action": "approved", "note": "ok"},
            headers=admin_headers,
        )
        assert res.status_code == 200, res.text
    else:
        raise AssertionError("workflow did not reach approved")
    final = (
        await api_client.get(f"/api/v1/admin/loans/applications/{app_id}", headers=admin_headers)
    ).json()
    if accept_offer and not final.get("offer_accepted_at"):
        await accept_loan_offer(api_client, app_id)
    return app_id


async def accept_loan_offer(api_client, app_id: str) -> dict:
    """The customer reviews the offer and accepts it with their transaction PIN."""
    headers = {"Authorization": f"Bearer {await _login(api_client)}"}
    me = (await api_client.get("/api/v1/auth/me", headers=headers)).json()
    if not me["transaction_pin_set"]:
        await set_transaction_pin(api_client, headers)
    offer = (await api_client.get(f"/api/v1/loans/me/applications/{app_id}/offer", headers=headers)).json()
    res = await api_client.post(
        f"/api/v1/loans/me/applications/{app_id}/offer/accept",
        json={"terms_hash": offer["terms_hash"], "transaction_pin": TEST_TXN_PIN},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return res.json()


async def verify_all_documents(api_client, app_id, admin_headers, status="verified"):
    detail = (await api_client.get(f"/api/v1/admin/loans/applications/{app_id}", headers=admin_headers)).json()
    for doc in detail["documents"]:
        res = await api_client.patch(
            f"/api/v1/admin/loans/applications/{app_id}/documents/{doc['id']}/verify",
            json={"status": status, **({"rejection_note": "Unreadable"} if status == "rejected" else {})},
            headers=admin_headers,
        )
        assert res.status_code == 200, res.text


async def disburse(api_client, app_id, admin_headers):
    return await api_client.post(
        f"/api/v1/admin/loans/applications/{app_id}/disburse",
        json={"note": "Disburse"},
        headers=admin_headers,
    )


async def disbursement_for(db_session, app_id) -> LoanDisbursement:
    result = await db_session.execute(
        select(LoanDisbursement).where(LoanDisbursement.application_id == app_id)
    )
    return result.scalar_one()


class TestTenureLimit:
    async def test_submit_rejects_tenure_over_product_maximum(self, api_client, db_session):
        from app.modules.loans.models import LoanProduct

        app_id, headers = await complete_draft(api_client, db_session, tenure=6)
        product = (
            await db_session.execute(select(LoanProduct).where(LoanProduct.code == "business_loan"))
        ).scalar_one()
        product.max_tenure_days = 120
        await db_session.flush()

        res = await api_client.post(f"/api/v1/loans/me/applications/{app_id}/submit", headers=headers)
        assert res.status_code == 422, res.text
        body = res.json()
        assert body["code"] == "APPLICATION_INCOMPLETE"
        assert any("maximum of 4 months" in e for e in body["errors"])


class TestBankCodeCapture:
    async def test_bank_code_is_persisted_on_the_application(self, api_client, db_session, admin_headers):
        app_id = await approved_application(api_client, db_session, admin_headers)
        application = await db_session.get(LoanApplication, app_id)
        await db_session.refresh(application)
        assert application.universal_form["bank_code"] == "058"

    async def test_submission_requires_bank_code(self, api_client, db_session):
        await _seed(db_session)
        headers = {"Authorization": f"Bearer {await _customer_token(api_client)}"}
        app_id = (
            await api_client.post(
                "/api/v1/loans/me/applications", json={"product_code": "business_loan"}, headers=headers
            )
        ).json()["id"]
        form = {k: v for k, v in UNIVERSAL_FORM.items() if k != "bank_code"}
        await api_client.patch(
            f"/api/v1/loans/me/applications/{app_id}",
            json={"step": 6, "total_steps": 6, "universal_form": form},
            headers=headers,
        )
        res = await api_client.post(f"/api/v1/loans/me/applications/{app_id}/submit", headers=headers)
        assert res.status_code == 422
        assert any("bank_code" in e for e in res.json()["errors"])


class TestDisbursementCompletion:
    async def test_webhook_completes_disbursement_and_books_loan(self, api_client, db_session, admin_headers, pending_rail):
        app_id = await approved_application(api_client, db_session, admin_headers)
        res = await disburse(api_client, app_id, admin_headers)
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "ready_to_disburse"

        disbursement = await disbursement_for(db_session, app_id)
        body, headers = monnify_signed(
            {
                "eventType": "SUCCESSFUL_DISBURSEMENT",
                "eventData": {
                    "reference": disbursement.transfer_reference,
                    "amount": "500000.00",
                    "status": "SUCCESS",
                    "transactionReference": "MFDS-1",
                },
            }
        )
        webhook = await api_client.post("/api/v1/webhooks/monnify", content=body, headers=headers)
        assert webhook.status_code == 200

        application = await db_session.get(LoanApplication, app_id)
        await db_session.refresh(application)
        assert application.status == ApplicationStatus.DISBURSED
        assert application.disbursed_at is not None

        loans = (await db_session.execute(select(Loan).where(Loan.application_id == app_id))).scalars().all()
        assert len(loans) == 1
        assert loans[0].principal == 500000

        journals = await db_session.scalar(
            select(func.count()).select_from(LedgerJournal).where(
                LedgerJournal.journal_type == JournalType.LOAN_DISBURSEMENT
            )
        )
        assert journals == 1

    async def test_duplicate_success_webhook_books_once(self, api_client, db_session, admin_headers, pending_rail):
        app_id = await approved_application(api_client, db_session, admin_headers)
        await disburse(api_client, app_id, admin_headers)
        disbursement = await disbursement_for(db_session, app_id)
        payload = {
            "eventType": "SUCCESSFUL_DISBURSEMENT",
            "eventData": {"reference": disbursement.transfer_reference, "amount": "500000.00"},
        }
        body, headers = monnify_signed(payload)
        await api_client.post("/api/v1/webhooks/monnify", content=body, headers=headers)
        await api_client.post("/api/v1/webhooks/monnify", content=body, headers=headers)
        count = await db_session.scalar(
            select(func.count()).select_from(Loan).where(Loan.application_id == app_id)
        )
        assert count == 1

    async def test_failed_disbursement_returns_application_to_approved(
        self, api_client, db_session, admin_headers, pending_rail
    ):
        app_id = await approved_application(api_client, db_session, admin_headers)
        await disburse(api_client, app_id, admin_headers)
        disbursement = await disbursement_for(db_session, app_id)
        body, headers = monnify_signed(
            {
                "eventType": "FAILED_DISBURSEMENT",
                "eventData": {
                    "reference": disbursement.transfer_reference,
                    "transactionDescription": "Beneficiary account closed",
                },
            }
        )
        await api_client.post("/api/v1/webhooks/monnify", content=body, headers=headers)

        application = await db_session.get(LoanApplication, app_id)
        await db_session.refresh(application)
        await db_session.refresh(disbursement)
        assert application.status == ApplicationStatus.APPROVED
        assert disbursement.status == TransactionStatus.FAILED
        assert "closed" in (disbursement.failure_reason or "")

        # A failed disbursement can be retried by staff.
        retry = await disburse(api_client, app_id, admin_headers)
        assert retry.status_code == 200, retry.text
        await db_session.refresh(disbursement)
        assert disbursement.status == TransactionStatus.PENDING
        assert disbursement.failure_reason is None

    async def test_cannot_disburse_twice_while_pending(self, api_client, db_session, admin_headers, pending_rail):
        app_id = await approved_application(api_client, db_session, admin_headers)
        assert (await disburse(api_client, app_id, admin_headers)).status_code == 200
        second = await disburse(api_client, app_id, admin_headers)
        assert second.status_code == 409


class TestReconciliation:
    async def test_missed_webhook_is_completed_by_reconciliation(
        self, api_client, db_session, admin_headers, monkeypatch, pending_rail
    ):
        app_id = await approved_application(api_client, db_session, admin_headers)
        await disburse(api_client, app_id, admin_headers)
        await db_session.commit()

        from app.modules.payments import worker_service

        class _SessionCtx:
            async def __aenter__(self):
                return db_session

            async def __aexit__(self, *exc):
                return False

        monkeypatch.setattr(worker_service, "worker_session", lambda: _SessionCtx())
        result = await worker_service.run_reconcile_payments()
        assert result["matched"] >= 1

        application = await db_session.get(LoanApplication, app_id)
        await db_session.refresh(application)
        assert application.status == ApplicationStatus.DISBURSED
        tx = (
            await db_session.execute(
                select(PaymentTransaction).where(
                    PaymentTransaction.application_id == app_id,
                    PaymentTransaction.direction == PaymentDirection.OUTBOUND,
                )
            )
        ).scalars().all()
        assert all(t.status == TransactionStatus.COMPLETED for t in tx)


class TestRailOutcomes:
    async def test_synchronous_success_completes_immediately(self, api_client, db_session, admin_headers):
        app_id = await approved_application(api_client, db_session, admin_headers)
        res = await disburse(api_client, app_id, admin_headers)  # mock Monnify reports SUCCESS
        assert res.status_code == 200, res.text
        application = await db_session.get(LoanApplication, app_id)
        await db_session.refresh(application)
        assert application.status == ApplicationStatus.DISBURSED
        loan = (await db_session.execute(select(Loan).where(Loan.application_id == app_id))).scalar_one()
        assert loan.status == LoanStatus.ACTIVE

    async def test_unknown_outcome_stays_pending_and_blocks_redisbursal(
        self, api_client, db_session, admin_headers, monkeypatch
    ):
        """Timeout after the bank may have paid: must NOT allow a second payout."""
        app_id = await approved_application(api_client, db_session, admin_headers)
        rail_raising(monkeypatch, TransientRailError("Monnify unreachable", status_code=502))
        res = await disburse(api_client, app_id, admin_headers)
        assert res.status_code == 200
        assert res.json()["status"] == "ready_to_disburse"
        disbursement = await disbursement_for(db_session, app_id)
        assert disbursement.status == TransactionStatus.PENDING

        again = await disburse(api_client, app_id, admin_headers)
        assert again.status_code == 409  # previously: a fresh reference and a second payout

    async def test_rejection_marks_failed_and_allows_retry(
        self, api_client, db_session, admin_headers, monkeypatch
    ):
        app_id = await approved_application(api_client, db_session, admin_headers)
        rail_raising(monkeypatch, PaymentRailError("Invalid beneficiary account", status_code=400))
        res = await disburse(api_client, app_id, admin_headers)
        assert res.status_code == 502
        assert res.json()["code"] == "PAYMENT_PROVIDER_ERROR"

        disbursement = await disbursement_for(db_session, app_id)
        application = await db_session.get(LoanApplication, app_id)
        await db_session.refresh(disbursement)
        await db_session.refresh(application)
        assert disbursement.status == TransactionStatus.FAILED  # persisted despite the error response
        assert application.status == ApplicationStatus.APPROVED

    async def test_disbursement_requires_tenure(self, api_client, db_session, admin_headers):
        """No offer (and so no payout) until staff set the tenure: the credit stage refuses."""
        form = {**UNIVERSAL_FORM, "repayment_period": "as agreed"}
        app_id = await submitted_application(api_client, db_session, form=form, tenure=None)
        await verify_all_documents(api_client, app_id, admin_headers)
        refused = None
        for _ in range(4):
            res = await api_client.post(
                f"/api/v1/admin/loans/applications/{app_id}/stage-action",
                json={"action": "approved", "note": "ok"},
                headers=admin_headers,
            )
            if res.status_code != 200:
                refused = res
                break
        assert refused is not None and refused.status_code == 409
        assert "tenure" in refused.json()["detail"].lower()

        # Staff confirm terms, the customer accepts the offer, then it disburses.
        await api_client.patch(
            f"/api/v1/admin/loans/applications/{app_id}/status",
            json={"tenure_months": 3},
            headers=admin_headers,
        )
        await finish_approval(api_client, app_id, admin_headers)
        assert (await disburse(api_client, app_id, admin_headers)).status_code == 200


class TestManualDisbursement:
    async def test_manual_disbursement_books_loan(self, api_client, db_session, admin_headers):
        app_id = await approved_application(api_client, db_session, admin_headers)
        res = await api_client.post(
            f"/api/v1/admin/loans/applications/{app_id}/disbursements/manual",
            json={"external_reference": "NIP-000123456789", "note": "Sent from GTB corporate app"},
            headers=admin_headers,
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "disbursed"
        loan = (await db_session.execute(select(Loan).where(Loan.application_id == app_id))).scalar_one()
        assert loan.installments_count == 6

        duplicate = await api_client.post(
            f"/api/v1/admin/loans/applications/{app_id}/disbursements/manual",
            json={"external_reference": "NIP-000123456789"},
            headers=admin_headers,
        )
        assert duplicate.status_code == 409

    async def test_future_date_rejected(self, api_client, db_session, admin_headers):
        app_id = await approved_application(api_client, db_session, admin_headers)
        res = await api_client.post(
            f"/api/v1/admin/loans/applications/{app_id}/disbursements/manual",
            json={"external_reference": "NIP-999", "disbursed_on": "2999-01-01"},
            headers=admin_headers,
        )
        assert res.status_code == 422


async def booked_loan(api_client, db_session, admin_headers) -> Loan:
    app_id = await approved_application(api_client, db_session, admin_headers)
    await api_client.post(
        f"/api/v1/admin/loans/applications/{app_id}/disbursements/manual",
        json={"external_reference": f"NIP-{app_id[:8]}"},
        headers=admin_headers,
    )
    return (await db_session.execute(select(Loan).where(Loan.application_id == app_id))).scalar_one()


class TestLoanBook:
    async def test_flat_schedule_numbers(self, api_client, db_session, admin_headers):
        loan = await booked_loan(api_client, db_session, admin_headers)
        # 500,000 at 8%/month flat over 6 months → 240,000 interest.
        assert loan.principal == Decimal("500000.00")
        assert loan.total_interest == Decimal("240000.00")
        assert loan.total_repayable == Decimal("740000.00")
        assert loan.outstanding == Decimal("740000.00")
        assert loan.monthly_payment == Decimal("123333.33")

        detail = (
            await api_client.get(f"/api/v1/admin/loans/loans/{loan.id}", headers=admin_headers)
        ).json()
        assert len(detail["schedule"]) == 6
        assert sum(Decimal(i["amount"]) for i in detail["schedule"]) == Decimal("740000.00")

    async def test_customer_sees_own_loan_only(self, api_client, db_session, admin_headers):
        loan = await booked_loan(api_client, db_session, admin_headers)
        token = await _login(api_client)
        mine = await api_client.get("/api/v1/loans/me/loans", headers={"Authorization": f"Bearer {token}"})
        assert mine.status_code == 200
        assert mine.json()["total"] == 1
        detail = await api_client.get(
            f"/api/v1/loans/me/loans/{loan.id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert detail.status_code == 200
        assert len(detail.json()["schedule"]) == 6


class TestRepayments:
    async def test_staff_repayment_allocates_interest_first_and_is_idempotent(
        self, api_client, db_session, admin_headers
    ):
        loan = await booked_loan(api_client, db_session, admin_headers)
        body = {"amount": "50000.00", "channel": "bank_transfer", "reference": "GTB-REF-001"}
        url = f"/api/v1/admin/loans/loans/{loan.id}/repayments"
        first = await api_client.post(url, json=body, headers=admin_headers)
        assert first.status_code == 201, first.text
        # Installment 1 = 83,333.33 principal + 40,000 interest; interest is paid first.
        assert Decimal(first.json()["interest_amount"]) == Decimal("40000.00")
        assert Decimal(first.json()["principal_amount"]) == Decimal("10000.00")

        again = await api_client.post(url, json=body, headers=admin_headers)
        assert again.status_code == 201
        assert again.json()["id"] == first.json()["id"]  # replay, not a second payment

        count = await db_session.scalar(select(func.count()).select_from(LoanRepayment))
        assert count == 1
        await db_session.refresh(loan)
        assert loan.amount_paid == Decimal("50000.00")
        assert loan.outstanding == Decimal("690000.00")

        conflicting = await api_client.post(
            url, json={**body, "amount": "60000.00"}, headers=admin_headers
        )
        assert conflicting.status_code == 409

    async def test_full_repayment_closes_loan_and_balances_ledger(
        self, api_client, db_session, admin_headers
    ):
        loan = await booked_loan(api_client, db_session, admin_headers)
        res = await api_client.post(
            f"/api/v1/admin/loans/loans/{loan.id}/repayments",
            json={"amount": "740000.00", "channel": "cash", "reference": "TELLER-777"},
            headers=admin_headers,
        )
        assert res.status_code == 201, res.text
        await db_session.refresh(loan)
        assert loan.status == LoanStatus.COMPLETED
        assert loan.outstanding == 0
        assert loan.principal_outstanding == 0
        lines = (
            await db_session.execute(select(RepaymentSchedule).where(RepaymentSchedule.loan_id == loan.id))
        ).scalars().all()
        assert all(line.status == InstallmentStatus.PAID for line in lines)

        from app.modules.payments.models import LedgerAccountCode, LedgerDirection, LedgerEntry

        async def balance(code):
            rows = (
                await db_session.execute(select(LedgerEntry).where(LedgerEntry.account_code == code))
            ).scalars().all()
            return sum(
                (r.amount if r.direction == LedgerDirection.DEBIT else -r.amount for r in rows), Decimal("0")
            )

        assert await balance(LedgerAccountCode.LOAN_RECEIVABLE) == 0  # principal fully recovered
        assert await balance(LedgerAccountCode.INTEREST_INCOME) == Decimal("-240000.00")

    async def test_overpayment_rejected(self, api_client, db_session, admin_headers):
        loan = await booked_loan(api_client, db_session, admin_headers)
        res = await api_client.post(
            f"/api/v1/admin/loans/loans/{loan.id}/repayments",
            json={"amount": "999999.00", "channel": "cash", "reference": "TOO-MUCH"},
            headers=admin_headers,
        )
        assert res.status_code == 422

    async def test_wallet_repayment_requires_key_and_funds(self, api_client, db_session, admin_headers):
        loan = await booked_loan(api_client, db_session, admin_headers)
        token = await _login(api_client)
        headers = {"Authorization": f"Bearer {token}"}
        # The transaction PIN was created when the customer accepted the loan offer.
        url = f"/api/v1/loans/me/loans/{loan.id}/repayments"

        missing_key = await api_client.post(
            url, json={"amount": "1000", "transaction_pin": TEST_TXN_PIN}, headers=headers
        )
        assert missing_key.status_code == 422

        broke = await api_client.post(
            url,
            json={"amount": "1000", "transaction_pin": TEST_TXN_PIN},
            headers={**headers, "Idempotency-Key": "repay-key-0001"},
        )
        assert broke.status_code == 409
        assert broke.json()["code"] == "INSUFFICIENT_FUNDS"

    async def test_wallet_repayment_debits_wallet_once(self, api_client, db_session, admin_headers):
        from app.modules.payments.ledger_service import LedgerService
        from app.modules.payments.models import PaymentTransaction as PT, PaymentDirection as PD, PaymentProvider as PP

        loan = await booked_loan(api_client, db_session, admin_headers)
        ledger = LedgerService(db_session)
        wallet = await ledger.get_or_create_wallet(loan.customer_id)
        funding = PT(
            provider=PP.MONNIFY, provider_reference="FUND-1", direction=PD.INBOUND,
            amount=Decimal("20000"), status=TransactionStatus.COMPLETED, customer_id=loan.customer_id,
        )
        db_session.add(funding)
        await db_session.flush()
        await ledger.credit_wallet_from_paystack(
            customer_id=loan.customer_id, amount=Decimal("20000"), idempotency_key="wf:FUND-1",
            reference="FUND-1", payment_transaction=funding,
        )
        await db_session.commit()

        token = await _login(api_client)
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "repay-key-0002"}
        # The transaction PIN was created when the customer accepted the loan offer.
        url = f"/api/v1/loans/me/loans/{loan.id}/repayments"
        body = {"amount": "15000", "transaction_pin": TEST_TXN_PIN}
        first = await api_client.post(url, json=body, headers=headers)
        second = await api_client.post(url, json=body, headers=headers)
        assert first.status_code == second.status_code == 201
        assert first.json()["id"] == second.json()["id"]
        await db_session.refresh(wallet)
        assert wallet.available_balance == Decimal("5000.00")

        # The wallet history shows it once, linked to the loan.
        history = (
            await api_client.get("/api/v1/wallet/transactions?direction=out", headers=headers)
        ).json()["items"]
        assert len(history) == 1
        repayment = history[0]
        assert repayment["kind"] == "repayment" and repayment["amount"] == 15000
        assert repayment["loan_id"] == loan.id and repayment["loan_product"] == loan.product_type


class TestOverdue:
    async def test_daily_job_marks_overdue(self, api_client, db_session, admin_headers):
        from app.modules.loans.servicing import LoanServicingService

        loan = await booked_loan(api_client, db_session, admin_headers)
        processed = await LoanServicingService(db_session).refresh_open_loans(
            today=date(loan.disbursement_date.year + 1, 1, 1)
        )
        assert processed == 1
        await db_session.refresh(loan)
        assert loan.status == LoanStatus.OVERDUE
