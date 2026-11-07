import base64
from io import BytesIO

import qrcode
from qrcode.image.svg import SvgPathImage

from django.conf import settings
from django.core import signing
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac


QR_CODE_ROTATION_SECONDS = 30
QR_CODE_SIGNING_SALT = "parking.reservation.qr"


def _time_bucket(now):
    return int(now.timestamp()) // QR_CODE_ROTATION_SECONDS


def _verification_code(reservation_id, bucket):
    digest = salted_hmac(
        QR_CODE_SIGNING_SALT,
        f"{reservation_id}:{bucket}",
        secret=settings.SECRET_KEY,
    ).digest()
    return base64.b32encode(digest).decode("ascii")[:8]


def create_reservation_qr_token(reservation_id, now=None):
    now = now or timezone.now()
    bucket = _time_bucket(now)
    code = _verification_code(reservation_id, bucket)
    token = signing.dumps(
        {
            "reservation_id": reservation_id,
            "bucket": bucket,
            "code": code,
        },
        salt=QR_CODE_SIGNING_SALT,
        compress=True,
    )
    return token, code, bucket


def create_reservation_qr(reservation_id, request, now=None):
    token, code, bucket = create_reservation_qr_token(reservation_id, now)
    verification_url = request.build_absolute_uri(
        reverse("parking:agent_qr_verify", kwargs={"token": token})
    )

    qr = qrcode.QRCode(box_size=5, border=2)
    qr.add_data(verification_url)
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    svg_buffer = BytesIO()
    image.save(svg_buffer)
    image_data = base64.b64encode(svg_buffer.getvalue()).decode("ascii")

    return {
        "bucket": bucket,
        "verification_code": code,
        "image_data_uri": f"data:image/svg+xml;base64,{image_data}",
        "expires_at": (bucket + 1) * QR_CODE_ROTATION_SECONDS,
        "refresh_url": reverse(
            "parking:reservation_qr_data",
            kwargs={"reservation_id": reservation_id},
        ),
    }


def verify_reservation_qr(token, now=None):
    if len(token) > 1024:
        return None

    try:
        payload = signing.loads(
            token,
            salt=QR_CODE_SIGNING_SALT,
            max_age=QR_CODE_ROTATION_SECONDS,
        )
    except signing.BadSignature:
        return None

    if not isinstance(payload, dict):
        return None

    reservation_id = payload.get("reservation_id")
    bucket = payload.get("bucket")
    code = payload.get("code")
    if (
        not isinstance(reservation_id, int)
        or isinstance(reservation_id, bool)
        or not isinstance(bucket, int)
        or isinstance(bucket, bool)
        or not isinstance(code, str)
    ):
        return None

    now = now or timezone.now()
    if bucket != _time_bucket(now) or code != _verification_code(reservation_id, bucket):
        return None

    return {
        "reservation_id": reservation_id,
        "bucket": bucket,
        "verification_code": code,
    }
