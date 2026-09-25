"""After submission, a customer can replace only the documents staff rejected."""

import io

from sqlalchemy import select

from app.modules.loans.workflow_models import ApplicationAuditLog, AuditEventType
from app.modules.users.models import Customer
from tests.conftest import TEST_BVN, TEST_OTP
from tests.integration.test_disbursement_lifecycle import (
    submitted_application,
    verify_all_documents,
)

PDF = ("replacement.pdf", io.BytesIO(b"%PDF-1.4 clearer scan"), "application/pdf")


async def _signed_in(api_client, db_session) -> dict:
    """The applicant signs in again (e.g. from the app) after submitting."""
    customer = (
        await db_session.execute(select(Customer).where(Customer.bvn == TEST_BVN))
    ).scalar_one()
    await api_client.post(
        "/api/v1/auth/login/request-otp", json={"phone": customer.phone_primary}
    )
    res = await api_client.post(
        "/api/v1/auth/login/verify-otp",
        json={"phone": customer.phone_primary, "otp": TEST_OTP},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _reject(api_client, app_id, admin_headers, document_type):
    detail = (
        await api_client.get(
            f"/api/v1/admin/loans/applications/{app_id}", headers=admin_headers
        )
    ).json()
    doc = next(d for d in detail["documents"] if d["document_type"] == document_type)
    res = await api_client.patch(
        f"/api/v1/admin/loans/applications/{app_id}/documents/{doc['id']}/verify",
        json={"status": "rejected", "rejection_note": "Photo is blurred"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text


async def test_customer_replaces_a_rejected_document(
    api_client, db_session, admin_headers
):
    app_id = await submitted_application(api_client, db_session)
    customer = await _signed_in(api_client, db_session)
    await _reject(api_client, app_id, admin_headers, "valid_id")
    before = (
        await api_client.get(
            f"/api/v1/loans/me/applications/{app_id}", headers=customer
        )
    ).json()["status"]

    res = await api_client.post(
        f"/api/v1/loans/me/applications/{app_id}/documents/valid_id",
        headers=customer,
        files={"file": PDF},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    replaced = next(d for d in body["documents"] if d["document_type"] == "valid_id")
    assert replaced["status"] == "pending"  # back in the staff review queue
    assert (
        body["status"] == before == "under_review"
    )  # still in the workflow; staff re-verify

    events = (
        (
            await db_session.execute(
                select(ApplicationAuditLog).where(
                    ApplicationAuditLog.application_id == app_id,
                    ApplicationAuditLog.event_type == AuditEventType.DOCUMENT_UPLOADED,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1 and events[0].event_metadata == {
        "document_type": "valid_id"
    }


async def test_documents_not_rejected_stay_locked_after_submission(
    api_client, db_session, admin_headers
):
    app_id = await submitted_application(api_client, db_session)
    customer = await _signed_in(api_client, db_session)

    res = await api_client.post(
        f"/api/v1/loans/me/applications/{app_id}/documents/valid_id",
        headers=customer,
        files={"file": PDF},
    )
    assert res.status_code == 409
    assert res.json()["code"] == "APPLICATION_NOT_EDITABLE"

    # Verified documents can't be swapped either.
    await verify_all_documents(api_client, app_id, admin_headers)
    res = await api_client.post(
        f"/api/v1/loans/me/applications/{app_id}/documents/valid_id",
        headers=customer,
        files={"file": PDF},
    )
    assert res.status_code == 409


async def test_no_replacements_once_the_application_is_decided(
    api_client, db_session, admin_headers
):
    app_id = await submitted_application(api_client, db_session)
    customer = await _signed_in(api_client, db_session)
    await _reject(api_client, app_id, admin_headers, "valid_id")
    rejected = await api_client.patch(
        f"/api/v1/admin/loans/applications/{app_id}/status",
        json={"status": "rejected", "note": "Does not meet criteria"},
        headers=admin_headers,
    )
    assert rejected.status_code == 200, rejected.text

    res = await api_client.post(
        f"/api/v1/loans/me/applications/{app_id}/documents/valid_id",
        headers=customer,
        files={"file": PDF},
    )
    assert res.status_code == 409
