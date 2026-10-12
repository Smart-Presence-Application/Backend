"""
Email helpers: render templates, send HTML with a plain-text part, and send
in background threads. Delivery goes through the SMTP settings (Brevo in
production); the <head> of a template is dropped from the text version.
"""
import html as html_lib
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from email.mime.image import MIMEImage
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=getattr(settings, "EMAIL_ASYNC_WORKERS", 4))

HEAD_RE = re.compile(r"<head\b.*?</head>", re.IGNORECASE | re.DOTALL)
BLANK_LINES_RE = re.compile(r"\n{3,}")

LOGO_PATH = Path(__file__).resolve().parent / "email_assets" / "logo.png"
LOGO_CID = "smartpresence-logo"


@lru_cache(maxsize=1)
def _logo_bytes() -> bytes:
    return LOGO_PATH.read_bytes()


def attach_inline_logo(email: EmailMultiAlternatives) -> None:
    """
    Embed the logo PNG in the message itself, so it shows without hosting it
    anywhere; templates use it via "cid:smartpresence-logo" because email
    clients ignore the site's web font. The multipart/related subtype keeps
    the image with the HTML instead of listing it as an attachment.
    """

    image = MIMEImage(_logo_bytes(), _subtype="png")
    image.add_header("Content-ID", f"<{LOGO_CID}>")
    image.add_header("Content-Disposition", "inline", filename="smartpresence-logo.png")
    email.mixed_subtype = "related"
    email.attach(image)


def render_email_template(template_name: str, context: dict) -> str:
    return render_to_string(template_name, context)


def _submit_email(func: Callable, *args, **kwargs) -> None:
    def runner() -> None:
        try:
            func(*args, **kwargs)
        except Exception:
            logger.exception("Async email delivery failed.")
    _executor.submit(runner)


def send_email(subject: str, message: str, recipient_list: Iterable[str]) -> int:
    return send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, list(recipient_list), fail_silently=False)


def send_email_async(subject: str, message: str, recipient_list: Iterable[str]) -> None:
    _submit_email(send_email, subject, message, list(recipient_list))


def html_to_text(html: str) -> str:
    """
    Readable plain-text version of an HTML email, for clients that do not
    show HTML: the <head> is dropped and the indentation and blank lines
    left behind by the markup are collapsed.
    """

    text = html_lib.unescape(strip_tags(HEAD_RE.sub("", html)))
    lines = (" ".join(line.split()) for line in text.splitlines())

    return BLANK_LINES_RE.sub("\n\n", "\n".join(lines)).strip()


def login_url() -> str:
    """The app's sign-in page, for the button in account emails; empty hides it."""

    base = getattr(settings, "FRONTEND_URL", "").rstrip("/")

    return f"{base}/login" if base else ""


def send_html_email(
    subject: str,
    template_name: str,
    context: dict,
    recipient_list: Iterable[str],
    reply_to: Iterable[str] | None = None,
) -> int:
    """
    Send the rendered template as HTML with a plain-text alternative.

    The HTML must go out as the message's HTML part; sending the
    tag-stripped text marked as HTML is what made these emails arrive
    with no styling.
    """

    context = {"login_url": login_url(), **context}
    html = render_email_template(template_name, context)
    email = EmailMultiAlternatives(
        subject,
        html_to_text(html),
        settings.DEFAULT_FROM_EMAIL,
        list(recipient_list),
        reply_to=list(reply_to or []),
    )
    email.attach_alternative(html, "text/html")

    if f"cid:{LOGO_CID}" in html:
        attach_inline_logo(email)

    return email.send(fail_silently=False)


def send_html_email_async(subject: str, template_name: str, context: dict, recipient_list: Iterable[str]) -> None:
    _submit_email(send_html_email, subject, template_name, context, list(recipient_list))


def send_account_created_email(
    sender,
    user,
    raw_password=None,
    **kwargs,
):
    send_html_email_async(
        subject="Your account has been created",
        template_name="emails/account_created.html",
        context={
            "user": user,
            "password": raw_password,
        },
        recipient_list=(user.email,),
    )


def send_account_deactivated_email(
    sender,
    user,
    changed_by=None,
    **kwargs,
):
    send_html_email_async(
        subject="Your account has been deactivated",
        template_name="emails/account_deactivated.html",
        context={
            "user": user,
            "changed_by": changed_by,
        },
        recipient_list=(user.email,),
    )
