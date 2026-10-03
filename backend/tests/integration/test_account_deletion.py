"""Customer account deletion (in the app and on the web) and the profile photo."""

import base64
from decimal import Decimal

from sqlalchemy import func, select

from app.core.config import get_settings
from app.models.base import TransactionStatus
from app.modules.auth.account_deletion import LOAN_BLOCK_MESSAGE, REMOVED_TEXT, AccountDeletionService
from app.modules.auth.models import AuthSession, CustomerDevice
from app.modules.loans.models import LoanApplication
from app.modules.notifications.models import Notification
from app.modules.payments.ledger_service import LedgerService
from app.modules.payments.models import PaymentDirection, PaymentProvider, PaymentTransaction
from app.modules.support.models import SupportMessage
from app.modules.users.models import Customer, CustomerStatus
from tests.conftest import TEST_BVN, TEST_LOGIN_PIN, TEST_OTP
from tests.integration.test_device_security import PHONE, PHONE_A, _auth, _register, _set_pin

JPEG = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x01" * 4000).decode()
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x02" * 4000).decode()


async def _customer_with_pin(api_client) -> dict:
    tokens = await _register(api_client, PHONE_A)
    assert (await _set_pin(api_client, tokens)).status_code == 200
    return tokens


async def _delete(api_client, tokens, pin=TEST_LOGIN_PIN, confirmation="DELETE"):
    return await api_client.request(
        "DELETE", "/api/v1/auth/me", json={"pin": pin, "confirmation": confirmation}, headers=_auth(tokens)
    )


async def _customer(db_session) -> Customer:
    db_session.expire_all()
    return (await db_session.execute(select(Customer))).scalar_one()


class TestInApp:
    async def test_needs_sign_in(self, api_client):
        res = await api_client.request("DELETE", "/api/v1/auth/me", json={"pin": "123456", "confirmation": "DELETE"})
        assert res.status_code == 401

    async def test_check_lists_what_happens(self, api_client):
        tokens = await _customer_with_pin(api_client)
        check = (await api_client.get("/api/v1/auth/me/account-deletion", headers=_auth(tokens))).json()
        assert check["can_delete"] is True and check["blockers"] == []
        assert check["will_delete"] and check["will_keep"]

    async def test_deletes_scrubs_and_signs_out_everywhere(self, api_client, db_session):
        tokens = await _customer_with_pin(api_client)
        customer = await _customer(db_session)
        cid = customer.id
        # Things that must go: a draft application, a notification, a support message, a photo.
        await api_client.post("/api/v1/support/tickets", json={"category": "app", "message": "The app is slow today."},
                              headers=_auth(tokens))
        await api_client.put("/api/v1/auth/me/photo", json={"image": JPEG}, headers=_auth(tokens))
        db_session.add(Notification(customer_id=cid, kind="test", title="t", body="b"))
        await db_session.commit()

        res = await _delete(api_client, tokens)
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "deleted"

        c = await _customer(db_session)
        assert c.status == CustomerStatus.DELETED and c.deleted_at is not None
        # No loan or payment ever: identity is scrubbed too.
        assert c.bvn.startswith("X") and c.first_name == "Deleted" and c.date_of_birth is None
        assert c.phone_primary.startswith("deleted-")
        assert c.email is None and c.residential_address is None and c.login_pin_hash is None
        photos = (await db_session.execute(
            select(Customer.profile_photo_base64, Customer.bvn_photo_base64).where(Customer.id == cid)
        )).one()
        assert photos == (None, None)
        assert await db_session.scalar(select(func.count()).select_from(Notification)) == 0
        assert await db_session.scalar(select(func.count()).select_from(CustomerDevice)) == 0
        assert {m.body for m in (await db_session.execute(select(SupportMessage))).scalars()} == {REMOVED_TEXT}
        sessions = (await db_session.execute(select(AuthSession))).scalars().all()
        assert sessions and all(s.revoked_at is not None and s.push_token is None for s in sessions)

        # The old access token, refresh token and SMS sign-in all stop working.
        assert (await api_client.get("/api/v1/auth/me", headers=_auth(tokens))).status_code == 401
        refreshed = await api_client.post("/api/v1/auth/token/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert refreshed.status_code == 401
        await api_client.post("/api/v1/auth/login/request-otp", json={"phone": PHONE})
        login = await api_client.post("/api/v1/auth/login/verify-otp", json={"phone": PHONE, "otp": TEST_OTP})
        assert login.status_code in (400, 401)
        # A retry after a timeout is refused by sign-in, not applied twice.
        assert (await _delete(api_client, tokens)).status_code == 401

    async def test_wrong_pin_or_missing_confirmation_keeps_the_account(self, api_client, db_session):
        tokens = await _customer_with_pin(api_client)
        assert (await _delete(api_client, tokens, confirmation="yes")).status_code == 422
        wrong = await _delete(api_client, tokens, pin="999999")
        assert wrong.status_code in (400, 401)
        assert (await _customer(db_session)).status == CustomerStatus.ACTIVE

    async def test_drafts_are_deleted_with_the_account(self, api_client, db_session):
        from tests.integration.test_loan_workflow_api import _seed

        await _seed(db_session)
        tokens = await _customer_with_pin(api_client)
        created = await api_client.post(
            "/api/v1/loans/me/applications", json={"product_code": "business_loan"}, headers=_auth(tokens)
        )
        assert created.status_code == 201, created.text
        assert (await _delete(api_client, tokens)).status_code == 200
        assert await db_session.scalar(select(func.count()).select_from(LoanApplication)) == 0

    async def test_other_customers_are_untouched(self, api_client, db_session):
        tokens = await _customer_with_pin(api_client)
        other = Customer(
            account_number="3099999999", branch="Lagos", bvn="22299999999", first_name="Ola", last_name="Ade",
            phone_primary="+2348099999999", status=CustomerStatus.ACTIVE,
        )
        db_session.add(other)
        await db_session.commit()
        other_id = other.id
        assert (await _delete(api_client, tokens)).status_code == 200
        db_session.expire_all()
        kept = await db_session.get(Customer, other_id)
        assert kept.status == CustomerStatus.ACTIVE and kept.first_name == "Ola"


class TestBlocked:
    async def test_outstanding_loan_blocks_deletion(self, api_client, db_session, admin_headers):
        from tests.integration.test_disbursement_lifecycle import _login, booked_loan

        await booked_loan(api_client, db_session, admin_headers)
        token = await _login(api_client)
        await api_client.post("/api/v1/auth/pin", json={"pin": TEST_LOGIN_PIN}, headers=_auth(token))
        check = (await api_client.get("/api/v1/auth/me/account-deletion", headers=_auth(token))).json()
        assert check["can_delete"] is False
        assert [b["code"] for b in check["blockers"]] == ["LOAN_OUTSTANDING"]

        res = await _delete(api_client, {"access_token": token})
        assert res.status_code == 409
        assert res.json()["code"] == "LOAN_OUTSTANDING"
        assert res.json()["detail"] == LOAN_BLOCK_MESSAGE
        assert (await _customer(db_session)).status == CustomerStatus.ACTIVE

    async def test_money_in_the_wallet_blocks_deletion(self, api_client, db_session):
        tokens = await _customer_with_pin(api_client)
        customer = await _customer(db_session)
        wallet = await LedgerService(db_session).get_or_create_wallet(customer.id)
        wallet.available_balance = Decimal("100.00")
        await db_session.commit()
        res = await _delete(api_client, tokens)
        assert res.status_code == 409 and res.json()["code"] == "WALLET_NOT_EMPTY"

    async def test_several_reasons_are_all_listed(self, api_client, db_session, admin_headers):
        from tests.integration.test_disbursement_lifecycle import _login, booked_loan

        loan = await booked_loan(api_client, db_session, admin_headers)
        wallet = await LedgerService(db_session).get_or_create_wallet(loan.customer_id)
        wallet.available_balance = Decimal("50.00")
        await db_session.commit()
        token = await _login(api_client)
        await api_client.post("/api/v1/auth/pin", json={"pin": TEST_LOGIN_PIN}, headers=_auth(token))
        res = await _delete(api_client, {"access_token": token})
        body = res.json()
        assert body["code"] == "ACCOUNT_DELETION_BLOCKED"
        assert {e["code"] for e in body["errors"]} == {"LOAN_OUTSTANDING", "WALLET_NOT_EMPTY"}


class TestRetention:
    async def test_identity_is_kept_with_financial_records(self, api_client, db_session):
        tokens = await _customer_with_pin(api_client)
        customer = await _customer(db_session)
        db_session.add(
            PaymentTransaction(
                provider=PaymentProvider.MONNIFY, provider_reference="ref-1", direction=PaymentDirection.INBOUND,
                amount=Decimal("1000"), currency="NGN", status=TransactionStatus.COMPLETED,
                customer_id=customer.id, raw_payload={},
            )
        )
        await db_session.commit()
        assert (await _delete(api_client, tokens)).status_code == 200
        c = await _customer(db_session)
        assert c.bvn == TEST_BVN and c.first_name != "Deleted"  # kept with the payment record
        assert c.phone_primary.startswith("deleted-") and c.email is None
        assert await db_session.scalar(select(func.count()).select_from(PaymentTransaction)) == 1

        # The BVN can't quietly open a fresh account over the kept records.
        again = await api_client.post("/api/v1/auth/register/bvn", json={"bvn": TEST_BVN})
        assert again.status_code == 409 and again.json()["code"] == "ACCOUNT_CLOSED"

    async def test_service_is_idempotent(self, api_client, db_session):
        await _customer_with_pin(api_client)
        customer = await _customer(db_session)
        service = AccountDeletionService(db_session)
        first = await service.delete(customer)
        second = await service.delete(await _customer(db_session))
        assert first.deleted_at and second.deleted_at
        assert (await _customer(db_session)).status == CustomerStatus.DELETED


class TestWeb:
    async def test_code_and_pin_delete_the_account(self, api_client, db_session):
        await _customer_with_pin(api_client)
        sent = await api_client.post("/api/v1/auth/account-deletion/request-otp", json={"phone": PHONE})
        assert sent.status_code == 200
        res = await api_client.post(
            "/api/v1/auth/account-deletion/confirm",
            json={"phone": PHONE, "otp": TEST_OTP, "pin": TEST_LOGIN_PIN, "confirmation": "DELETE"},
        )
        assert res.status_code == 200, res.text
        assert (await _customer(db_session)).status == CustomerStatus.DELETED

    async def test_unknown_number_gets_the_same_answer_and_no_code(self, api_client):
        known = await api_client.post("/api/v1/auth/account-deletion/request-otp", json={"phone": "08011110000"})
        assert known.status_code == 200
        res = await api_client.post(
            "/api/v1/auth/account-deletion/confirm",
            json={"phone": "08011110000", "otp": TEST_OTP, "pin": "123456", "confirmation": "DELETE"},
        )
        assert res.status_code == 400  # no code was ever issued

    async def test_wrong_code_or_pin_deletes_nothing(self, api_client, db_session):
        await _customer_with_pin(api_client)
        await api_client.post("/api/v1/auth/account-deletion/request-otp", json={"phone": PHONE})
        bad_code = await api_client.post(
            "/api/v1/auth/account-deletion/confirm",
            json={"phone": PHONE, "otp": "000000", "pin": TEST_LOGIN_PIN, "confirmation": "DELETE"},
        )
        assert bad_code.status_code == 400
        bad_pin = await api_client.post(
            "/api/v1/auth/account-deletion/confirm",
            json={"phone": PHONE, "otp": TEST_OTP, "pin": "999999", "confirmation": "DELETE"},
        )
        assert bad_pin.status_code in (400, 401)
        assert (await _customer(db_session)).status == CustomerStatus.ACTIVE


class TestPhoto:
    async def test_bvn_photo_then_custom_then_back(self, api_client, db_session):
        tokens = await _register(api_client, PHONE_A)
        customer = await _customer(db_session)
        customer.bvn_photo_base64 = PNG
        await db_session.commit()

        bvn = (await api_client.get("/api/v1/auth/me/photo", headers=_auth(tokens))).json()
        assert bvn["source"] == "bvn" and bvn["content_type"] == "image/png"

        me = (await api_client.put("/api/v1/auth/me/photo", json={"image": JPEG}, headers=_auth(tokens))).json()
        assert me["has_custom_photo"] is True and me["photo_version"]
        custom = (await api_client.get("/api/v1/auth/me/photo", headers=_auth(tokens))).json()
        assert custom["source"] == "custom" and custom["content_type"] == "image/jpeg"

        me = (await api_client.delete("/api/v1/auth/me/photo", headers=_auth(tokens))).json()
        assert me["has_custom_photo"] is False
        assert (await api_client.get("/api/v1/auth/me/photo", headers=_auth(tokens))).json()["source"] == "bvn"

    async def test_rejects_non_images_and_needs_sign_in(self, api_client):
        tokens = await _register(api_client, PHONE_A)
        bad = await api_client.put(
            "/api/v1/auth/me/photo", json={"image": base64.b64encode(b"%PDF-1.4" * 500).decode()}, headers=_auth(tokens)
        )
        assert bad.status_code == 422 and bad.json()["code"] == "PHOTO_INVALID"
        assert (await api_client.get("/api/v1/auth/me/photo")).status_code == 401
        none = (await api_client.get("/api/v1/auth/me/photo", headers=_auth(tokens))).json()
        assert none["image"] is None


def test_upload_dir_is_used_for_draft_files():
    assert get_settings().upload_dir
