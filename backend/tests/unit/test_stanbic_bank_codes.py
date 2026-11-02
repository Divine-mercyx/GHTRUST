"""Stanbic bank code conversion: 3-digit CBN codes to Stanbic's 6-digit institution codes."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.integrations.payments.schemas import PaymentRailError
from app.integrations.stanbic import bank_codes
from app.integrations.stanbic.bank_codes import BankDirectory, BankEntry, UnknownBankCode

PORTAL = "app.integrations.stanbic.portal_sandbox._portal_request"


def _bank(code, v1, name):
    return {"id": 1, "institutionCode": code, "institutionName": name, "v1InstitutionCode": v1, "category": "2"}


def _page(items, number, total_pages):
    return {"code": "00", "message": "Successful", "data": {"content": items, "number": number, "totalPages": total_pages}}


@pytest.fixture(autouse=True)
def _fresh_cache():
    bank_codes.clear_cache()
    yield
    bank_codes.clear_cache()


DIRECTORY = BankDirectory(
    [
        BankEntry(code="999058", v1_code="058", name="GTBank"),
        BankEntry(code="999221", v1_code="221", name="Stanbic IBTC Bank"),
        BankEntry(code="999044", v1_code="044", name="Access Bank"),
        BankEntry(code="090267", v1_code=None, name="Kuda Microfinance Bank"),
    ]
)


class TestConversion:
    @pytest.mark.parametrize(
        ("given", "expected"),
        [("058", "999058"), ("221", "999221"), ("44", "999044"), ("999058", "999058"), ("090267", "090267")],
    )
    def test_known_codes(self, given, expected):
        assert DIRECTORY.to_institution_code(given) == expected

    @pytest.mark.parametrize("given", ["999", "123456", "50211", "", "abc"])
    def test_unknown_codes_are_refused_never_guessed(self, given):
        with pytest.raises(UnknownBankCode) as exc:
            DIRECTORY.to_institution_code(given)
        assert exc.value.provider_code == "UNKNOWN_BANK_CODE"
        assert not exc.value.outcome_unknown  # a definite failure: nothing was sent


class TestFetching:
    async def test_one_based_pages_are_all_read(self):
        """page=1 echoed back as number 0: pages count from 1."""
        pages = {
            1: _page([_bank("999058", "058", "GTBank")], number=0, total_pages=2),
            2: _page([_bank("999221", "221", "Stanbic IBTC Bank")], number=1, total_pages=2),
        }
        request = AsyncMock(side_effect=lambda method, url, params: pages[params["page"]])
        with patch(PORTAL, request):
            directory = await bank_codes.get_bank_directory()
        assert {e.code for e in directory.entries} == {"999058", "999221"}
        assert sorted(c.kwargs["params"]["page"] for c in request.await_args_list) == [1, 2]

    async def test_zero_based_pages_include_page_zero(self):
        """page=1 echoed back as number 1: pages count from 0, so page 0 is fetched too."""
        pages = {
            0: _page([_bank("999058", "058", "GTBank")], number=0, total_pages=2),
            1: _page([_bank("999221", "221", "Stanbic IBTC Bank")], number=1, total_pages=2),
        }
        with patch(PORTAL, AsyncMock(side_effect=lambda method, url, params: pages[params["page"]])):
            directory = await bank_codes.get_bank_directory()
        assert directory.to_institution_code("058") == "999058"
        assert directory.to_institution_code("221") == "999221"

    async def test_cached_and_reused(self):
        request = AsyncMock(return_value=_page([_bank("999058", "058", "GTBank")], number=0, total_pages=1))
        with patch(PORTAL, request):
            await bank_codes.get_bank_directory()
            await bank_codes.get_bank_directory()
        assert request.await_count == 1

    async def test_failed_refresh_keeps_the_last_good_list(self, monkeypatch):
        with patch(PORTAL, AsyncMock(return_value=_page([_bank("999058", "058", "GTBank")], 0, 1))):
            await bank_codes.get_bank_directory()
        monkeypatch.setattr(bank_codes, "CACHE_SECONDS", -1)  # force a refresh
        with patch(PORTAL, AsyncMock(side_effect=PaymentRailError("down", status_code=502))):
            directory = await bank_codes.get_bank_directory()
        assert directory.to_institution_code("058") == "999058"

    async def test_no_list_at_all_is_a_definite_failure(self):
        with patch(PORTAL, AsyncMock(side_effect=PaymentRailError("down", status_code=502))):
            with pytest.raises(PaymentRailError) as exc:
                await bank_codes.get_bank_directory()
        assert exc.value.provider_code == "BANK_LIST_UNAVAILABLE"
        assert not exc.value.outcome_unknown


class TestStanbicTransfers:
    @pytest.fixture
    def portal_client(self, monkeypatch):
        from tests.conftest import refresh_settings

        monkeypatch.setenv("STANBIC_MOCK", "false")
        monkeypatch.setenv("STANBIC_CLIENT_ID", "id")
        monkeypatch.setenv("STANBIC_CLIENT_SECRET", "secret")
        monkeypatch.setenv("STANBIC_PORTAL_SANDBOX", "true")
        monkeypatch.setenv("STANBIC_SETTLEMENT_ACCOUNT_NUMBER", "0011223344")
        refresh_settings()
        import app.integrations.stanbic.client as client_module
        from app.core.config import get_settings

        monkeypatch.setattr(client_module, "settings", get_settings())
        monkeypatch.setattr(bank_codes, "settings", get_settings())
        bank_codes._cache = (DIRECTORY, __import__("time").monotonic())
        return client_module.StanbicClient()

    async def test_transfer_sends_the_six_digit_code(self, portal_client):
        sent = AsyncMock(return_value={"responseCode": "00", "responseMsg": "SUCCESS", "destAcctCredited": "Y"})
        with patch("app.integrations.stanbic.portal_sandbox.single_transfer", sent):
            await portal_client.initiate_disbursement(
                amount=Decimal("5000"),
                reference="ghtrust_wdr_1",
                bank_code="058",
                account_number="0123456789",
                account_name="Ada Obi",
                narration="GH Trust withdrawal",
            )
        assert sent.await_args.args[0]["destinationAccountBankCode"] == "999058"

    async def test_recipient_sees_the_customers_note_and_our_statement_ours(self, portal_client):
        sent = AsyncMock(return_value={"responseCode": "00", "responseMsg": "SUCCESS", "destAcctCredited": "Y"})
        with patch("app.integrations.stanbic.portal_sandbox.single_transfer", sent):
            await portal_client.initiate_disbursement(
                amount=Decimal("5000"),
                reference="ghtrust_wdr_3",
                bank_code="058",
                account_number="0123456789",
                account_name="Ada Obi",
                narration="Rent for May",
                source_narration="GH Trust wallet withdrawal",
            )
        payload = sent.await_args.args[0]
        assert payload["destAcctNarration"] == "Rent for May"
        assert payload["srcAcctNarration"] == "GH Trust wallet withdrawal"

    async def test_unknown_bank_never_reaches_stanbic(self, portal_client):
        sent = AsyncMock(side_effect=AssertionError("must not send"))
        with patch("app.integrations.stanbic.portal_sandbox.single_transfer", sent):
            with pytest.raises(UnknownBankCode):
                await portal_client.initiate_disbursement(
                    amount=Decimal("5000"),
                    reference="ghtrust_wdr_2",
                    bank_code="50211",
                    account_number="0123456789",
                    account_name="Ada Obi",
                    narration="GH Trust withdrawal",
                )

    async def test_name_check_converts_and_bank_picker_lists_stanbic_codes(self, portal_client):
        lookup = AsyncMock(return_value={"responseCode": "00", "accountName": "ADA OBI", "accountNumber": "0123456789"})
        with patch("app.integrations.stanbic.portal_sandbox.name_enquiry", lookup):
            resolved = await portal_client.validate_bank_account("0123456789", "221")
        assert lookup.await_args.args == ("0123456789", "999221")
        assert resolved.account_name == "ADA OBI" and resolved.bank_code == "221"
        banks = await portal_client.supported_banks()
        assert ("999058", "GTBank") in [(b.code, b.name) for b in banks]


async def test_live_sandbox_response_shape():
    """What Stanbic's sandbox actually returns (Oct 2026), unlike the spec file."""

    def live(page):
        rows = {
            1: [{"bankId": 1, "bankCode": "000013", "bankName": "GTBank", "v1InstitutionCode": "058", "category": "2", "bankShortName": "GTB"}],
            2: [{"bankId": 2, "bankCode": "110005", "bankName": "3line Card management Limited", "v1InstitutionCode": "110005", "category": "11", "bankShortName": "3line"}],
        }[page]
        return {"responseCode": "00", "responseMsg": "Successful",
                "responseDetails": {"content": rows, "pageNumber": page, "size": 200, "totalRecords": 2, "totalPages": 2}}

    request = AsyncMock(side_effect=lambda method, url, params: live(params["page"]))
    with patch(PORTAL, request):
        directory = await bank_codes.get_bank_directory()
    assert sorted(c.kwargs["params"]["page"] for c in request.await_args_list) == [1, 2]  # no page 0
    assert directory.to_institution_code("058") == "000013"
    assert directory.to_institution_code("110005") == "110005"


def test_a_three_digit_code_shared_by_several_banks_is_refused():
    shared = BankDirectory(
        [
            BankEntry(code="999559", v1_code="559", name="Coronation"),
            BankEntry(code="999359", v1_code="559", name="CreditorCorp"),
        ]
    )
    with pytest.raises(UnknownBankCode):
        shared.to_institution_code("559")
    assert shared.to_institution_code("999559") == "999559"  # the full code still works


class TestStanbicResponseCodes:
    """00 successful, 99 failed, 55/56 pending (confirmed by Stanbic). Pending must never refund."""

    @pytest.mark.parametrize(
        ("payload", "status"),
        [
            ({"responseCode": "00", "responseMsg": "SUCCESS", "destAcctCredited": "Y"}, "SUCCESS"),
            ({"responseCode": "55", "responseMsg": "Pending"}, "PENDING"),
            ({"responseCode": "56", "responseMsg": "Pending"}, "PENDING"),
            ({"responseCode": "99", "responseMsg": "Failed"}, "FAILED"),
            ({"responseCode": "99", "responseMsg": "Duplicate request"}, "PENDING"),
            ({"responseCode": "42", "responseMsg": "Something new"}, "PENDING"),
            ({}, "PENDING"),
        ],
    )
    def test_transfer_status_mapping(self, payload, status):
        from app.integrations.stanbic.portal_sandbox import map_nps_transfer_status

        assert map_nps_transfer_status(payload) == status

    def test_pending_and_duplicate_replies_are_not_errors(self):
        from app.integrations.stanbic.portal_sandbox import _check_response_code

        _check_response_code({"responseCode": "55", "responseMsg": "Pending"})
        _check_response_code({"responseCode": "99", "responseMsg": "Duplicate transaction"})
        with pytest.raises(PaymentRailError):
            _check_response_code({"responseCode": "99", "responseMsg": "Failed"})

    async def test_sending_a_transfer_is_never_retried(self):
        """A retry with the same clientRefId would be refused as a duplicate and look like a failure."""
        import httpx

        from app.integrations.stanbic import portal_sandbox

        calls = []

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def request(self, *args, **kwargs):
                calls.append(1)
                raise httpx.ConnectError("connection reset")

        with patch("app.integrations.stanbic.portal_sandbox.httpx.AsyncClient", lambda **kw: Client()):
            with pytest.raises(PaymentRailError) as exc:
                await portal_sandbox.single_transfer({"clientRefId": "ghtrust_wdr_9"})
        assert len(calls) == 1
        assert exc.value.outcome_unknown  # the caller waits for the status check, no refund
