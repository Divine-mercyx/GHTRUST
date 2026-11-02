"""Saved recipients for "Send money", and the wallet Insights summary."""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from sqlalchemy import select, update

from app.integrations.payments.schemas import DisbursementResult
from app.modules.payments.models import LedgerJournal, PayoutRecipient, WithdrawalRequest, WithdrawalStatus
from app.modules.payments.transactions import WalletTransactionService
from app.modules.payments.wallet_service import WalletService
from tests.conftest import TEST_TXN_PIN
from tests.integration.test_wallet_history import _customer, _fund, _refs

GTB = {"bank_code": "058", "bank_name": "GTBank", "account_number": "0123456789", "account_name": "Ada Okafor"}
ACCESS = {"bank_code": "044", "bank_name": "Access Bank", "account_number": "0987654321", "account_name": "Ada Okafor"}


async def _save(api_client, headers, account: dict):
    res = await api_client.post(
        "/api/v1/wallet/payout-account", json={**account, "transaction_pin": TEST_TXN_PIN}, headers=headers
    )
    assert res.status_code == 200, res.text
    return res


async def _recipients(api_client, headers) -> list[dict]:
    res = await api_client.get("/api/v1/wallet/recipients", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


async def _send(api_client, headers, amount: str, recipient_id: str | None = None, narration: str | None = None):
    body = {"amount": amount, "transaction_pin": TEST_TXN_PIN}
    if recipient_id:
        body["recipient_id"] = recipient_id
    if narration is not None:
        body["narration"] = narration
    return await api_client.post(
        "/api/v1/wallet/withdraw",
        json=body,
        headers={**headers, "Idempotency-Key": f"send-{next(_refs):06d}"},
    )


class TestRecipients:
    async def test_each_saved_account_is_remembered_once(self, api_client):
        _, headers = await _customer(api_client)
        assert await _recipients(api_client, headers) == []

        await _save(api_client, headers, GTB)
        await _save(api_client, headers, ACCESS)
        await _save(api_client, headers, GTB)  # saved again: same recipient, now the current one

        saved = await _recipients(api_client, headers)
        assert [r["bank_name"] for r in saved] == ["GTBank", "Access Bank"]
        assert [r["current"] for r in saved] == [True, False]
        assert saved[0]["account_number_masked"] == "******6789"
        assert "account_number" not in saved[0]

    async def test_sending_to_a_saved_account_pays_it_and_makes_it_current(self, api_client, db_session):
        customer_id, headers = await _customer(api_client)
        await _fund(db_session, customer_id)
        await _save(api_client, headers, GTB)
        await _save(api_client, headers, ACCESS)
        gtb = next(r for r in await _recipients(api_client, headers) if r["bank_name"] == "GTBank")

        res = await _send(api_client, headers, "2000", gtb["id"])
        assert res.status_code == 200, res.text
        withdrawal = (await db_session.execute(select(WithdrawalRequest))).scalar_one()
        assert (withdrawal.bank_code, withdrawal.account_number) == ("058", "0123456789")
        wallet = (await api_client.get("/api/v1/wallet", headers=headers)).json()
        assert wallet["payout_account"]["bank_name"] == "GTBank"
        assert (await _recipients(api_client, headers))[0]["id"] == gtb["id"]

    async def test_another_customers_recipient_is_refused(self, api_client, db_session):
        customer_id, headers = await _customer(api_client)
        await _fund(db_session, customer_id)
        await _save(api_client, headers, GTB)
        stranger = PayoutRecipient(
            customer_id=customer_id, bank_code="011", account_number="5555555555", account_name="Not Ada"
        )
        db_session.add(stranger)
        await db_session.flush()
        stranger.customer_id = "00000000-0000-0000-0000-000000000000"
        await db_session.commit()

        res = await _send(api_client, headers, "1000", stranger.id)
        assert res.status_code == 404 and res.json()["code"] == "RECIPIENT_NOT_FOUND"
        assert (await db_session.execute(select(WithdrawalRequest))).scalar_one_or_none() is None

    async def test_sending_still_needs_the_pin(self, api_client, db_session):
        customer_id, headers = await _customer(api_client)
        await _fund(db_session, customer_id)
        await _save(api_client, headers, GTB)
        recipient = (await _recipients(api_client, headers))[0]
        res = await api_client.post(
            "/api/v1/wallet/withdraw",
            json={"amount": "1000", "transaction_pin": "0000", "recipient_id": recipient["id"]},
            headers={**headers, "Idempotency-Key": "send-wrong-pin-1"},
        )
        assert res.status_code >= 400 and res.json()["code"].startswith("TRANSACTION_PIN_")
        assert (await db_session.execute(select(WithdrawalRequest))).scalar_one_or_none() is None

    async def test_remove_a_saved_account_but_not_the_current_one(self, api_client):
        _, headers = await _customer(api_client)
        await _save(api_client, headers, GTB)
        await _save(api_client, headers, ACCESS)
        current, older = await _recipients(api_client, headers)

        res = await api_client.delete(f"/api/v1/wallet/recipients/{current['id']}", headers=headers)
        assert res.status_code == 409 and res.json()["code"] == "RECIPIENT_IN_USE"
        res = await api_client.delete(f"/api/v1/wallet/recipients/{older['id']}", headers=headers)
        assert res.status_code == 204
        assert [r["id"] for r in await _recipients(api_client, headers)] == [current["id"]]


class TestWithdrawalNote:
    async def test_note_goes_to_the_recipient_and_shows_in_history(self, api_client, db_session):
        customer_id, headers = await _customer(api_client)
        await _fund(db_session, customer_id)
        await _save(api_client, headers, GTB)

        res = await _send(api_client, headers, "2000", narration="  Rent   for May ")
        assert res.status_code == 200, res.text
        withdrawal = (await db_session.execute(select(WithdrawalRequest))).scalar_one()
        assert withdrawal.narration == "Rent for May"

        rail = AsyncMock(return_value=DisbursementResult(reference="r", status="PENDING", amount=Decimal("2000")))
        with patch("app.integrations.monnify.client.MonnifyClient.initiate_disbursement", rail):
            await WalletService(db_session).process_withdrawal(withdrawal)
        sent = rail.await_args.kwargs
        assert sent["narration"] == "Rent for May"
        assert sent["source_narration"] == "GH Trust wallet withdrawal"

        detail = await api_client.get(f"/api/v1/wallet/transactions/w_{withdrawal.id}", headers=headers)
        assert detail.json()["narration"] == "Rent for May"

    async def test_without_a_note_the_recipient_sees_ours(self, api_client, db_session):
        customer_id, headers = await _customer(api_client)
        await _fund(db_session, customer_id)
        await _save(api_client, headers, GTB)

        assert (await _send(api_client, headers, "2000", narration="   ")).status_code == 200
        withdrawal = (await db_session.execute(select(WithdrawalRequest))).scalar_one()
        assert withdrawal.narration is None
        rail = AsyncMock(return_value=DisbursementResult(reference="r", status="PENDING", amount=Decimal("2000")))
        with patch("app.integrations.monnify.client.MonnifyClient.initiate_disbursement", rail):
            await WalletService(db_session).process_withdrawal(withdrawal)
        assert rail.await_args.kwargs["narration"] == "GH Trust wallet withdrawal"

    async def test_long_or_unusual_notes_are_refused_and_nothing_is_held(self, api_client, db_session):
        customer_id, headers = await _customer(api_client)
        await _fund(db_session, customer_id)
        await _save(api_client, headers, GTB)

        for note in ("x" * 31, "School fees 🎓", "<b>Rent</b>", "50% deposit"):
            res = await _send(api_client, headers, "2000", narration=note)
            assert res.status_code == 422, (note, res.text)
        assert (await db_session.execute(select(WithdrawalRequest))).first() is None


class TestInsights:
    async def test_money_in_and_out_by_month_and_kind(self, api_client, db_session):
        customer_id, headers = await _customer(api_client)
        await _fund(db_session, customer_id, "10000")
        await _fund(db_session, customer_id, "5000")
        await _save(api_client, headers, GTB)
        assert (await _send(api_client, headers, "3000")).status_code == 200
        assert (await _send(api_client, headers, "1000")).status_code == 200
        # A failed withdrawal moved no money (it's back in the wallet): not counted.
        await db_session.execute(
            update(WithdrawalRequest)
            .where(WithdrawalRequest.amount == 1000)
            .values(status=WithdrawalStatus.FAILED)
        )
        await db_session.commit()

        res = await api_client.get("/api/v1/wallet/insights?range=6m", headers=headers)
        assert res.status_code == 200, res.text
        body = res.json()
        assert (body["money_in"], body["money_out"]) == (15000, 3000)
        assert len(body["series"]) == 6 and body["series"][-1]["money_in"] == 15000
        assert {(c["kind"], c["amount"], c["count"]) for c in body["categories"]} == {
            ("funding", 15000, 2),
            ("withdrawal", 3000, 1),
        }

    async def test_last_month_is_by_day_and_older_money_is_left_out(self, api_client, db_session):
        customer_id, headers = await _customer(api_client)
        await _fund(db_session, customer_id, "4000")
        await db_session.execute(update(LedgerJournal).values(created_at=datetime(2020, 1, 15, tzinfo=timezone.utc)))
        await db_session.commit()
        await _fund(db_session, customer_id, "2500")

        body = (await api_client.get("/api/v1/wallet/insights?range=1m", headers=headers)).json()
        assert len(body["series"]) == 30
        assert (body["money_in"], body["money_out"]) == (2500, 0)
        assert body["series"][-1]["money_in"] == 2500

    async def test_month_buckets_cross_the_year(self, db_session):
        result = await WalletTransactionService(db_session).insights(
            "00000000-0000-0000-0000-000000000000", "6m", today=date(2027, 2, 10)
        )
        assert [p["start"] for p in result["series"]] == [
            date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 1),
            date(2026, 12, 1), date(2027, 1, 1), date(2027, 2, 1),
        ]  # fmt: skip
        assert result["start"] == date(2026, 9, 1)

    async def test_unknown_range_is_rejected(self, api_client):
        _, headers = await _customer(api_client)
        assert (await api_client.get("/api/v1/wallet/insights?range=5y", headers=headers)).status_code == 422
