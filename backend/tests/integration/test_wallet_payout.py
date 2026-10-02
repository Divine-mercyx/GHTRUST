"""With the wallet on, a loan is paid into the customer's GH Trust wallet, not a bank account."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.modules.loans.models import Loan, LoanApplication
from app.modules.notifications.models import Notification
from app.modules.payments.models import CustomerWallet, PaymentProvider, PaymentTransaction
from tests.conftest import refresh_settings
from tests.integration.test_disbursement_lifecycle import (
    _login,
    approved_application,
    disburse,
    disbursement_for,
)


@pytest.fixture
def wallet_on(monkeypatch):
    monkeypatch.setenv("FEATURE_FLAGS", "wallet")
    refresh_settings()


async def test_loan_is_paid_into_the_wallet_at_once(api_client, db_session, admin_headers, wallet_on):
    app_id = await approved_application(api_client, db_session, admin_headers)
    rail = AsyncMock(side_effect=AssertionError("no bank transfer when paying into the wallet"))
    with patch("app.integrations.monnify.client.MonnifyClient.initiate_disbursement", rail):
        res = await disburse(api_client, app_id, admin_headers)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "disbursed"

    application = await db_session.get(LoanApplication, app_id)
    disbursement = await disbursement_for(db_session, app_id)
    tx = await db_session.get(PaymentTransaction, disbursement.payment_transaction_id)
    assert tx.provider == PaymentProvider.WALLET
    wallet = (
        await db_session.execute(select(CustomerWallet).where(CustomerWallet.customer_id == application.customer_id))
    ).scalar_one()
    await db_session.refresh(wallet)
    assert wallet.available_balance == disbursement.amount
    loan = (await db_session.execute(select(Loan).where(Loan.application_id == app_id))).scalar_one()

    # The customer sees it: balance, a "Loan paid out" history row linked to the loan, a notification.
    headers = {"Authorization": f"Bearer {await _login(api_client)}"}
    summary = (await api_client.get("/api/v1/wallet", headers=headers)).json()
    assert Decimal(str(summary["available_balance"])) == disbursement.amount
    items = (await api_client.get("/api/v1/wallet/transactions?direction=in", headers=headers)).json()["items"]
    assert [(i["kind"], i["loan_id"]) for i in items] == [("loan_payout", loan.id)]
    note = (
        await db_session.execute(select(Notification).where(Notification.kind == "loan_disbursed"))
    ).scalar_one()
    assert "wallet" in note.body


async def test_paying_twice_is_refused(api_client, db_session, admin_headers, wallet_on):
    app_id = await approved_application(api_client, db_session, admin_headers)
    assert (await disburse(api_client, app_id, admin_headers)).status_code == 200
    again = await disburse(api_client, app_id, admin_headers)
    assert again.status_code == 409
    application = await db_session.get(LoanApplication, app_id)
    wallet = (
        await db_session.execute(select(CustomerWallet).where(CustomerWallet.customer_id == application.customer_id))
    ).scalar_one()
    await db_session.refresh(wallet)
    assert wallet.available_balance == (await disbursement_for(db_session, app_id)).amount
