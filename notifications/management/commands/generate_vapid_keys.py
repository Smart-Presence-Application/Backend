from cryptography.hazmat.primitives import serialization
from django.core.management.base import BaseCommand
from py_vapid import Vapid
from py_vapid.utils import b64urlencode


class Command(BaseCommand):
    """
    Print a new VAPID key pair for Web Push, ready to paste into .env.

    Both keys are base64url encoded: the public key as the uncompressed
    P-256 point browsers expect, the private key as the raw 32-byte scalar
    pywebpush accepts. Generate once per deployment; changing the keys later
    drops every existing browser subscription.
    """

    help = "Generate VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY for Web Push notifications."

    def handle(self, *args, **options):
        vapid = Vapid()
        vapid.generate_keys()
        public_key = vapid.public_key.public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
        private_key = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")

        self.stdout.write(f"VAPID_PUBLIC_KEY={b64urlencode(public_key)}")
        self.stdout.write(f"VAPID_PRIVATE_KEY={b64urlencode(private_key)}")
