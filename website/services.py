"""Contact form: Cloudflare Turnstile spam check, then store and email the enquiry."""

import logging

import requests
from django.conf import settings

from common.emails import send_html_email
from common.throttling import client_ip

from .models import ContactMessage

logger = logging.getLogger(__name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def turnstile_enabled() -> bool:
    return bool(getattr(settings, "TURNSTILE_SECRET_KEY", ""))


def verify_turnstile(token: str, ip: str) -> bool:
    """
    Ask Cloudflare whether the widget's token is from a real visitor.
    Without a secret configured the check is skipped (local development).
    """

    if not turnstile_enabled():
        logger.warning("TURNSTILE_SECRET_KEY is not set; contact form spam check skipped.")
        return True

    if not token:
        return False

    try:
        response = requests.post(
            TURNSTILE_VERIFY_URL,
            data={"secret": settings.TURNSTILE_SECRET_KEY, "response": token, "remoteip": ip},
            timeout=10,
        )
        return bool(response.json().get("success"))
    except (requests.RequestException, ValueError):
        logger.exception("Turnstile verification failed to complete")
        return False


def submit_contact(*, data: dict, request) -> ContactMessage:
    """
    Save the enquiry, then email it to the team (reply goes to the
    visitor). A failed email is only logged: the enquiry is safe in the
    database and Super Admins can still read it.
    """

    message = ContactMessage.objects.create(
        name=data["name"],
        email=data["email"],
        phone=data.get("phone", ""),
        school=data.get("school", ""),
        message=data["message"],
        ip_address=client_ip(request)[:64],
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
    )

    recipient = getattr(settings, "CONTACT_RECIPIENT_EMAIL", "")

    if not recipient:
        logger.warning("CONTACT_RECIPIENT_EMAIL is not set; enquiry %s saved but not emailed.", message.pk)
        return message

    try:
        send_html_email(
            subject=f"New enquiry from {message.name}" + (f" ({message.school})" if message.school else ""),
            template_name="emails/contact_message.html",
            context={"message": message},
            recipient_list=[recipient],
            reply_to=[message.email],
        )
        message.email_sent = True
        message.save(update_fields=["email_sent"])
    except Exception:
        logger.exception("Could not email contact enquiry %s", message.pk)

    return message
