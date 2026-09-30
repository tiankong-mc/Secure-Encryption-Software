"""Certificate-verified SMTP transport shared by every mail operation."""
import smtplib
import ssl
from contextlib import contextmanager


@contextmanager
def secure_smtp(host, port, timeout=20):
    context = ssl.create_default_context()
    port = int(port)
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=timeout)
    with server:
        if port != 465:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
        yield server
