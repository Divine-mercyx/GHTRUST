"""
Simulate a customer's bank transfer into their wallet on the dev server.

    python scripts/dev_credit_wallet.py 5000112233 185000

Sends the same signed webhook Monnify sends when money reaches a customer's
account number, so the real crediting path (ledger, idempotency) runs.
Only works against scripts/dev_server.py, which shares the dev signing secret.
"""

import argparse
import hashlib
import hmac
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dev_server import DEV_WEBHOOK_SECRET  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "account_number", help="the customer's wallet account number (Wallet tab)"
    )
    parser.add_argument("amount", type=float, help="naira")
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    args = parser.parse_args()

    ref = f"MNFY|DEV|{datetime.now(timezone.utc):%Y%m%d%H%M%S%f}"
    payload = {
        "eventType": "SUCCESSFUL_TRANSACTION",
        "eventData": {
            "product": {"type": "RESERVED_ACCOUNT"},
            "transactionReference": ref,
            "paymentReference": ref,
            "amountPaid": args.amount,
            "currency": "NGN",
            "paymentStatus": "PAID",
            "paymentMethod": "ACCOUNT_TRANSFER",
            "destinationAccountInformation": {"accountNumber": args.account_number},
        },
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(DEV_WEBHOOK_SECRET.encode(), body, hashlib.sha512).hexdigest()
    request = urllib.request.Request(
        f"{args.api}/webhooks/monnify",
        data=body,
        headers={"Content-Type": "application/json", "monnify-signature": signature},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as res:
            print(res.status, res.read().decode())
    except urllib.error.HTTPError as err:
        sys.exit(f"{err.code} {err.read().decode()}")


if __name__ == "__main__":
    main()
