"""Stanbic account opening client (sandbox spec shape)."""

import pytest

from app.integrations.stanbic.account_opening import StanbicAccountOpeningClient


@pytest.mark.asyncio
class TestStanbicAccountOpeningMock:
    async def test_create_and_status_mock(self):
        client = StanbicAccountOpeningClient()
        submitted = await client.create_account({"accountOpeningRefId": "ACCT-TEST-1", "customerBVN": "22222222222"})
        assert submitted.response_code == "00"
        status = await client.get_status(account_opening_ref_id="ACCT-TEST-1", request_date="05-OCT-26")
        assert status.account_number == "9901234567"
        assert status.pending is False
