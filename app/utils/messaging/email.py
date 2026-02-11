import logging
import boto3
from botocore.exceptions import ClientError
from app.core.config import settings
from datetime import datetime
from app.db.models import Influencer
import base64
import io
import uuid
import urllib.request
from PIL import Image
from app.utils.s3 import generate_user_presigned_url, s3
from app.core.config import settings


log = logging.getLogger(__name__)

AWS_REGION = settings.AWS_REGION
SES_SENDER = settings.SES_SENDER
CONFIRM_BASE_URL = settings.SES_SERVER
AWS_ACCESS_KEY_ID = settings.SES_AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY = settings.SES_AWS_SECRET_ACCESS_KEY

ses_client = boto3.client("ses", region_name=AWS_REGION)

EMAIL_VERIFY_HEADER_URL = "https://bucket-image-tease-me.s3.us-east-1.amazonaws.com/email_verify_header.png"
EMAIL_RESET_HEADER_URL = "https://bucket-image-tease-me.s3.us-east-1.amazonaws.com/reset_password_header.png"
# Email hero image size (width is fixed by template). Increase height here without changing face size
# because we render the overlay at a fixed scale (fit-to-width) and only crop vertically.
EMAIL_HEADER_SIZE = (520, 150)  # (width, height)

def send_verification_email(to_email: str, token: str):
    subject = "Confirm your email on TeaseMe!"
    confirm_url = f"{CONFIRM_BASE_URL}/verify-email?token={token}"
    logo_url = EMAIL_VERIFY_HEADER_URL

    body_html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Confirm your email</title>
</head>
<body style="background:#f7f8fc;padding:0;margin:0;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f7f8fc;padding:40px 0;">
    <tr>
      <td align="center">

        <!-- Card -->
        <table width="520" cellpadding="0" cellspacing="0" border="0" style="background:#fff;border-radius:24px;box-shadow:0 10px 32px 0 rgba(50,50,93,0.10),0 2px 4px 0 rgba(0,0,0,0.07);overflow:hidden;">
          <!-- Banner/Hero Image -->
          <tr>
            <td align="center" style="background:#23293b;padding:0;">
              <img 
                src="{logo_url}" 
                alt="TeaseMe" 
                style="width:100%;max-width:520px;display:block;border-top-left-radius:24px;border-top-right-radius:24px;"
              />
            </td>
          </tr>
          <!-- Main Content -->
          <tr>
            <td align="center" style="padding:32px 30px 8px 30px;">
              <h2 style="font-family: 'Arial Rounded MT Bold', Arial, sans-serif; font-size:32px; font-weight:bold; margin:0 0 12px 0; color:#444;">Hi! Welcome to TeaseMe</h2>
              <p style="font-size:16px;color:#666;margin:0 0 32px 0;">
                You are almost done! Before we get started, please verify your email address to activate your account. It's quick and helps us keep your account safe.
              </p>
              <a href="{confirm_url}"
                style="background:#FF5C74;border-radius:8px;color:#fff;text-decoration:none;display:inline-block;padding:18px 50px;font-size:22px;font-weight:bold;box-shadow:0 6px 24px #ffb5c7;margin-bottom:20px;">
                Confirm Email
              </a>
              <p style="margin:24px 0 0 0; font-size:14px; color:#bbb;">
                If you didn't sign up for TeaseMe, please ignore this message.<br/>
                Can't wait to talk to you!
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td align="center" style="padding:20px 0 12px 0;background:#e5e5e5;color:#bbb;font-size:14px;border-bottom-left-radius:24px;border-bottom-right-radius:24px;">
              © {datetime.now().year} TeaseMe. All rights reserved.
            </td>
          </tr>
        </table>
        <!-- /Card -->

      </td>
    </tr>
  </table>
</body>
</html>
"""

    body_text = f"Welcome to TeaseMe!\nPlease confirm your email by clicking this link: {confirm_url}"
    return send_email_via_ses(to_email, subject, body_html, body_text)

def send_profile_survey_email(to_email: str, token: str, temp_password: str):
    subject = "Complete Your TeaseMe Profile Survey"
    survey_url = f"{CONFIRM_BASE_URL}/profile-survey-form?token={token}&temp_password={temp_password}"
    logo_url = EMAIL_VERIFY_HEADER_URL

    body_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Complete Your Profile</title>
    </head>
    <body style="background:#f7f8fc;padding:0;margin:0;font-family:Arial,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f7f8fc;padding:40px 0;">
        <tr>
          <td align="center">

            <!-- Card -->
            <table width="520" cellpadding="0" cellspacing="0" border="0" style="background:#fff;border-radius:24px;box-shadow:0 10px 32px rgba(50,50,93,0.10),0 2px 4px rgba(0,0,0,0.07);overflow:hidden;">

              <!-- Banner -->
              <tr>
                <td align="center" style="background:#23293b;padding:0;">
                  <img 
                    src="{logo_url}" 
                    alt="TeaseMe" 
                    style="width:100%;max-width:520px;display:block;border-top-left-radius:24px;border-top-right-radius:24px;"
                  />
                </td>
              </tr>

              <!-- Main Content -->
              <tr>
                <td align="center" style="padding:32px 30px 8px 30px;">
                  <h2 style="font-family:'Arial Rounded MT Bold', Arial, sans-serif; font-size:30px; font-weight:bold; margin:0 0 14px 0; color:#444;">
                    Let's Build Your Perfect AI Persona
                  </h2>

                  <p style="font-size:16px;color:#666;margin:0 0 24px 0;">
                    You're all set! Before your AI companion goes live, we just need a
                    little more information from you.
                    This short survey helps us personalize your experience and tailor
                    the persona to your unique style.
                  </p>

                  <a href="{survey_url}"
                    style="background:#FF5C74; border-radius:8px; color:#fff; text-decoration:none; display:inline-block;
                          padding:18px 50px; font-size:22px; font-weight:bold; box-shadow:0 6px 24px #ffb5c7; margin-bottom:20px;">
                    Start Profile Survey
                  </a>

                  <p style="margin:24px 0 0 0; font-size:14px; color:#bbb;">
                    If you didn’t request this, you can safely ignore the email.<br/>
                    Your persona can't wait to meet you. ❤️
                  </p>
                </td>
              </tr>

              <!-- Footer -->
              <tr>
                <td align="center" style="padding:20px 0 12px 0;background:#e5e5e5;color:#bbb;font-size:14px;border-bottom-left-radius:24px;border-bottom-right-radius:24px;">
                  © {datetime.now().year} TeaseMe. All rights reserved.
                </td>
              </tr>
            </table>
            <!-- /Card -->

          </td>
        </tr>
      </table>
    </body>
    </html>
    """

    body_text = f"""
Complete Your TeaseMe Profile

You're all set! Before your AI companion goes live, we just need a little more info.

Start your profile survey here:
{survey_url}

If you didn’t request this, you can safely ignore this email.
Your persona can't wait to meet you. ❤️

© {datetime.now().year} TeaseMe. All rights reserved.
    """.strip()

    # Envia via SES (ou qualquer provider que você já usa)
    return send_email_via_ses(to_email, subject, body_html, body_text)

def send_email_via_ses(to_email, subject, body_html, body_text=None):
    try:
        ses_client = boto3.client(
            "ses",
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        )

        response = ses_client.send_email(
             Source=SES_SENDER,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": body_html, "Charset": "UTF-8"},
                    "Text": {"Data": body_text or subject, "Charset": "UTF-8"},
                },
            },
        )
        return response
    except ClientError as e:
        log.error("Failed to send email via SES to %s: %s", to_email, e)
        return None
    except Exception as e:
        log.error("Unexpected error sending email to %s: %s", to_email, e)
        return None

def send_password_reset_email(to_email: str, token: str):
    subject = "Redefine your TeaseMe password"
    reset_url = f"{CONFIRM_BASE_URL}/reset-password?token={token}"
    logo_url = EMAIL_RESET_HEADER_URL

    body_html = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>Reset your password</title>
        </head>
        <body style="background:#f7f8fc;padding:0;margin:0;font-family:Arial,sans-serif;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f7f8fc;padding:40px 0;">
            <tr>
            <td align="center">

                <!-- Card -->
                <table width="520" cellpadding="0" cellspacing="0" border="0" style="background:#fff;border-radius:24px;box-shadow:0 10px 32px 0 rgba(50,50,93,0.10),0 2px 4px 0 rgba(0,0,0,0.07);overflow:hidden;">
                <!-- Banner/Hero Image -->
                <tr>
                    <td align="center" style="padding:0;">
                    <img 
                        src="{logo_url}" 
                        alt="TeaseMe" 
                        style="width:100%;max-width:520px;display:block;border-top-left-radius:24px;border-top-right-radius:24px;"
                    />
                    </td>
                </tr>
                <!-- Main Content -->
                <tr>
                    <td align="center" style="padding:32px 30px 8px 30px;">
                    <h2 style="font-family: 'Arial Rounded MT Bold', Arial, sans-serif; font-size:28px; font-weight:bold; margin:0 0 12px 0; color:#444;">Forgot Your Password?</h2>
                    <p style="font-size:16px;color:#666;margin:0 0 32px 0;">
                        We received a request to reset the password for your TeaseMe account.<br/>
                        To create a new password, just click the button below:
                    </p>
                    <a href="{reset_url}"
                        style="background:#FF5C74;border-radius:8px;color:#fff;text-decoration:none;display:inline-block;padding:18px 50px;font-size:22px;font-weight:bold;box-shadow:0 6px 24px #ffb5c7;margin-bottom:20px;">
                        Reset My Password
                    </a>
                    <p style="margin:24px 0 0 0; font-size:14px; color:#bbb;">
                        This link will expire in 30 minutes to keep your account safe.<br/>
                        If you didn't request a password reset, you can safely ignore this email.
                    </p>
                    </td>
                </tr>
                <!-- Footer -->
                <tr>
                    <td align="center" style="padding:20px 0 12px 0;background:#e5e5e5;color:#bbb;font-size:14px;border-bottom-left-radius:24px;border-bottom-right-radius:24px;">
                    © {datetime.now().year} TeaseMe. All rights reserved.
                    </td>
                </tr>
                </table>
                <!-- /Card -->

            </td>
            </tr>
        </table>
        </body>
        </html>
        """

    body_text = f"Reset your TeaseMe password by clicking this link: {reset_url}"

    return send_email_via_ses(to_email, subject, body_html, body_text)

def image_data_url(key: str) -> str:
    """
    Return an image URL for email templates.

    NOTE:
    - Many email clients (incl. Gmail) don't reliably render `data:` URLs.
    - So we generate a long-lived presigned HTTPS URL instead.
    """
    try:
        expires = 60 * 60 * 24 * 7  # 7 days (max for SigV4 presign)
        url = generate_user_presigned_url(key, expires=expires)
        log.info(
            f"image_data_url: generated presigned url bucket={settings.BUCKET_NAME} key={key} expires={expires}"
        )
        return url
    except Exception:
        log.exception(
            f"image_data_url: failed to generate presigned url bucket={settings.BUCKET_NAME} key={key}",
            extra={"bucket": settings.BUCKET_NAME, "key": key},
        )
        raise


def _fetch_image_bytes_from_url(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=10) as resp:  # nosec - url is controlled by our code
        return resp.read()


def _fetch_image_bytes_from_s3(key: str) -> bytes:
    obj = s3.get_object(Bucket=settings.BUCKET_NAME, Key=key)
    return obj["Body"].read()


def _image_cover(img: Image.Image, size: tuple[int, int], *, mode: str = "RGB") -> Image.Image:
    """
    Resize+crop to fill size (cover), similar to CSS object-fit: cover.
    """
    target_w, target_h = size
    img = img.convert(mode)
    src_w, src_h = img.size
    if src_w == 0 or src_h == 0:
        return Image.new(mode, size, (0, 0, 0, 0) if mode == "RGBA" else (0, 0, 0))
    scale = max(target_w / src_w, target_h / src_h)
    new_w = int(round(src_w * scale))
    new_h = int(round(src_h * scale))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = max(0, (new_w - target_w) // 2)
    top = max(0, (new_h - target_h) // 2)
    return img.crop((left, top, left + target_w, top + target_h))


def _resize_to_width(img: Image.Image, target_w: int, *, mode: str = "RGBA") -> Image.Image:
    img = img.convert(mode)
    w, h = img.size
    if w == 0 or h == 0:
        return Image.new(mode, (target_w, 1), (0, 0, 0, 0) if mode == "RGBA" else (0, 0, 0))
    scale = target_w / w
    new_h = max(1, int(round(h * scale)))
    return img.resize((target_w, new_h), Image.LANCZOS)


def _image_fit_height_center(
    img: Image.Image, *, size: tuple[int, int], mode: str = "RGBA"
) -> Image.Image:
    """
    Resize image to match target height (no vertical crop), keep aspect ratio,
    and center it on a canvas of the target size.

    This avoids the "zoomed in" look you get from cover-cropping portrait photos.
    """
    target_w, target_h = size
    img = img.convert(mode)
    src_w, src_h = img.size
    if src_w == 0 or src_h == 0:
        return Image.new(mode, size, (0, 0, 0, 0) if mode == "RGBA" else (0, 0, 0))

    scale = target_h / src_h
    new_w = int(round(src_w * scale))
    new_h = target_h
    resized = img.resize((new_w, new_h), Image.LANCZOS)

    # If width exceeds canvas, center-crop horizontally.
    if new_w > target_w:
        left = (new_w - target_w) // 2
        resized = resized.crop((left, 0, left + target_w, target_h))
        return resized

    # Otherwise, paste centered with transparent padding.
    canvas = Image.new(mode, (target_w, target_h), (0, 0, 0, 0))
    x = (target_w - new_w) // 2
    canvas.paste(resized, (x, 0))
    return canvas


def compose_email_header_image_url(*, photo_key: str, background_url: str, influencer_id: str) -> str:
    """
    Compose a single email header image (520x800) so email clients don't need to support layered backgrounds.
    Uploads to S3 and returns a presigned URL.
    """
    size = EMAIL_HEADER_SIZE
    try:
        log.info(
            "compose_email_header_image_url: composing header "
            f"influencer_id={influencer_id} photo_key={photo_key}"
        )

        bg_raw = _fetch_image_bytes_from_url(background_url)
        photo_raw = _fetch_image_bytes_from_s3(photo_key)

        # Render overlay at a fixed scale (fit-to-width) so changing HEIGHT does not change face size.
        overlay_scaled = _resize_to_width(Image.open(io.BytesIO(bg_raw)), size[0], mode="RGBA")

        # Detect the transparent "hole" on the scaled overlay
        alpha_scaled = overlay_scaled.split()[-1]
        hole_bbox_scaled = alpha_scaled.point(lambda a: 255 if a < 10 else 0).getbbox()
        if not hole_bbox_scaled:
            hole_bbox_scaled = (60, 80, size[0] - 60, max(1, overlay_scaled.size[1] - 80))

        # Crop vertically around the hole so we always keep it visible.
        target_h = size[1]
        scaled_h = overlay_scaled.size[1]
        if scaled_h <= target_h:
            crop_top = 0
        else:
            hole_cy = (hole_bbox_scaled[1] + hole_bbox_scaled[3]) // 2
            crop_top = hole_cy - (target_h // 2)
            crop_top = max(0, min(crop_top, scaled_h - target_h))

        overlay = overlay_scaled.crop((0, crop_top, size[0], crop_top + target_h))

        # Hole bbox relative to cropped overlay
        hole_bbox = (
            hole_bbox_scaled[0],
            max(0, hole_bbox_scaled[1] - crop_top),
            hole_bbox_scaled[2],
            max(0, hole_bbox_scaled[3] - crop_top),
        )

        alpha = overlay.split()[-1]
        # Recompute bbox on cropped alpha as a safety net (e.g. if crop clipped edges)
        hole_bbox2 = alpha.point(lambda a: 255 if a < 10 else 0).getbbox()
        if hole_bbox2:
            hole_bbox = hole_bbox2

        if not hole_bbox:
            # Fallback: assume a centered hole
            hole_bbox = (60, 80, size[0] - 60, size[1] - 80)

        hole_w = max(1, hole_bbox[2] - hole_bbox[0])
        hole_h = max(1, hole_bbox[3] - hole_bbox[1])

        photo_img = Image.open(io.BytesIO(photo_raw))
        photo_fit = _image_cover(photo_img, (hole_w, hole_h), mode="RGBA")

        # Base layer: solid background; paste photo only where the hole is
        base = Image.new("RGBA", size, (0, 0, 0, 255))

        # Mask is inverse alpha: 255 in hole, 0 outside
        hole_mask_full = Image.eval(alpha, lambda a: 255 - a)
        hole_mask = hole_mask_full.crop(hole_bbox)
        base.paste(photo_fit, (hole_bbox[0], hole_bbox[1]), mask=hole_mask)

        # Put overlay OVER photo so its alpha hole reveals the photo underneath
        composed = Image.alpha_composite(base, overlay).convert("RGB")
        out = io.BytesIO()
        composed.save(out, format="JPEG", quality=90, optimize=True, progressive=True)
        out.seek(0)

        key = f"email-assets/headers/{influencer_id}/{uuid.uuid4()}.jpg"
        s3.upload_fileobj(out, settings.BUCKET_NAME, key, ExtraArgs={"ContentType": "image/jpeg"})

        url = generate_user_presigned_url(key, expires=60 * 60 * 24 * 7)
        log.info(f"compose_email_header_image_url: uploaded header key={key}")
        return url
    except Exception:
        log.exception(
            "compose_email_header_image_url: failed to compose header "
            f"influencer_id={influencer_id} photo_key={photo_key}"
        )
        raise
  
def send_new_influencer_email(
    to_email: str,
    influencer: Influencer,
    fp_ref_id: str | None = None,
):
    subject = "🎉 Your TeaseMe profile is live!"
    public_url = f"https://teaseme.live/{influencer.id}"
    referral_url = f"{public_url}?fpr={fp_ref_id}" if fp_ref_id else None

    logo_url = EMAIL_VERIFY_HEADER_URL
    if influencer.profile_picture_key:
        try:
            logo_url = image_data_url(influencer.profile_picture_key)
        except Exception:
            log.warning("Failed to load pre-influencer image for email", exc_info=True)


    referral_block = ""
    if referral_url:
        referral_block = f"""
          <p style="font-size:14px;color:#666;margin:8px 0 10px 0;">
            Your referral link:
          </p>
          <div style="display:inline-block;padding:10px 18px;border-radius:10px;background:#f3f4ff;
                      font-family:monospace;font-size:13px;color:#333;word-break:break-all;max-width:460px;">
            {referral_url}
          </div>
          <p style="font-size:12px;color:#777;margin:10px 0 0 0;">
            Share this link if you want your manager / parent promoter to get credit too.
          </p>
        """

    temp_pw_block = ""

    body_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <title>Your TeaseMe profile is live</title>
    </head>
    <body style="background:#f7f8fc;padding:0;margin:0;font-family:Arial,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f7f8fc;padding:40px 0;">
        <tr>
          <td align="center">

            <table width="520" cellpadding="0" cellspacing="0" border="0"
              style="background:#fff;border-radius:24px;box-shadow:0 10px 32px rgba(50,50,93,0.10),0 2px 4px rgba(0,0,0,0.07);overflow:hidden;">

              <tr>
                <td align="center" style="background:#23293b;padding:0;">
                  <img src="{logo_url}" alt="TeaseMe"
                    style="width:100%;max-width:520px;display:block;border-top-left-radius:24px;border-top-right-radius:24px;" />
                </td>
              </tr>

              <tr>
                <td align="center" style="padding:32px 30px 16px 30px;">
                  <h2 style="font-family:'Arial Rounded MT Bold', Arial, sans-serif; font-size:30px; font-weight:bold; margin:0 0 12px 0; color:#444;">
                    You’re live on TeaseMe 🎉
                  </h2>

                  <p style="font-size:16px;color:#666;margin:0 0 22px 0;">
                    Your influencer profile is now active. Fans can find you and join your page instantly.
                  </p>

                  <a href="{public_url}"
                    style="background:#FF5C74; border-radius:10px; color:#fff; text-decoration:none; display:inline-block;
                           padding:16px 44px; font-size:20px; font-weight:bold; box-shadow:0 6px 24px #ffb5c7; margin-bottom:18px;">
                    Open My Profile
                  </a>

                  <div style="margin-top:10px; font-size:13px; color:#777; word-break:break-all;">
                    {public_url}
                  </div>

                  {referral_block}
                  {temp_pw_block}

                  <p style="margin:26px 0 0 0; font-size:14px; color:#bbb;">
                    If you didn’t request this, you can safely ignore the email.<br/>
                    Let’s get you discovered. ❤️
                  </p>
                </td>
              </tr>

              <tr>
                <td align="center" style="padding:20px 0 12px 0;background:#e5e5e5;color:#bbb;font-size:14px;border-bottom-left-radius:24px;border-bottom-right-radius:24px;">
                  © {datetime.now().year} TeaseMe. All rights reserved.
                </td>
              </tr>
            </table>

          </td>
        </tr>
      </table>
    </body>
    </html>
    """

    body_text = f"""
Your TeaseMe profile is live 🎉

Open your profile:
{public_url}
""" + (f"\nReferral link:\n{referral_url}\n" if referral_url else "") + f"""

© {datetime.now().year} TeaseMe. All rights reserved.
""".strip()

    return send_email_via_ses(to_email, subject, body_html, body_text)

def send_new_influencer_email_with_picture(
    to_email: str,
    influencer: Influencer,
):
    subject = "🎉 Your TeaseMe profile is live!"
    public_url = f"https://teaseme.live/{influencer.id}"
    image_background_url = "https://bucket-image-tease-me.s3.us-east-1.amazonaws.com/influencer_header_background.png"
    key = getattr(influencer, "profile_photo_key", None)
    log.info(
        f"send_new_influencer_email_with_picture: building email influencer_id={influencer.id} has_profile_photo_key={bool(key)}",
        extra={
            "to_email": to_email,
            "influencer_id": str(influencer.id),
            "has_profile_photo_key": bool(key),
            "profile_photo_key": key,
        },
    )
    # Default header image (static). If we have a profile photo, we’ll try to compose a single 520x800 image.
    logo_url = EMAIL_VERIFY_HEADER_URL
    if key:
        try:
            logo_url = compose_email_header_image_url(
                photo_key=key,
                background_url=image_background_url,
                influencer_id=str(influencer.id),
            )
            log.info(
                f"send_new_influencer_email_with_picture: using influencer profile photo influencer_id={influencer.id} key={key}",
                extra={"influencer_id": str(influencer.id), "key": key},
            )
        except Exception:
            log.warning("Failed to load influencer image for email", exc_info=True)
    else:
        log.info(
            f"send_new_influencer_email_with_picture: using default header image influencer_id={influencer.id}",
            extra={"influencer_id": str(influencer.id)},
        )

    temp_pw_block = ""

    body_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <title>Your TeaseMe profile is live</title>
    </head>
    <body style="background:#f7f8fc;padding:0;margin:0;font-family:Arial,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f7f8fc;padding:40px 0;">
        <tr>
          <td align="center">

            <table width="520" cellpadding="0" cellspacing="0" border="0"
              style="background:#fff;border-radius:24px;box-shadow:0 10px 32px rgba(50,50,93,0.10),0 2px 4px rgba(0,0,0,0.07);overflow:hidden;">

              <tr>
                <td align="center" style="background:#23293b;padding:0;">
                  <img
                    src="{logo_url}"
                    alt="TeaseMe"
                    height="{EMAIL_HEADER_SIZE[1]}"
                    style="width:100%;max-width:520px;height:{EMAIL_HEADER_SIZE[1]}px;display:block;border-top-left-radius:24px;border-top-right-radius:24px;object-fit:cover;"
                  />
                </td>
              </tr>

              <tr>
                <td align="center" style="padding:32px 30px 16px 30px;">
                  <h2 style="font-family:'Arial Rounded MT Bold', Arial, sans-serif; font-size:30px; font-weight:bold; margin:0 0 12px 0; color:#444;">
                    You’re live on TeaseMe 🎉
                  </h2>

                  <p style="font-size:16px;color:#666;margin:0 0 22px 0;">
                    Your influencer profile is now active. Fans can find you and join your page instantly.
                  </p>

                  {temp_pw_block}

                  <a href="{public_url}"
                    style="background:#FF5C74;border-radius:8px;color:#fff;text-decoration:none;display:inline-block;padding:16px 42px;font-size:20px;font-weight:bold;box-shadow:0 6px 24px #ffb5c7;margin:10px 0 6px 0;">
                    View my profile
                  </a>

                  <p style="margin:26px 0 0 0; font-size:14px; color:#bbb;">
                    If you didn’t request this, you can safely ignore the email.<br/>
                    Let’s get you discovered. ❤️
                  </p>
                </td>
              </tr>

              <tr>
                <td align="center" style="padding:20px 0 12px 0;background:#e5e5e5;color:#bbb;font-size:14px;border-bottom-left-radius:24px;border-bottom-right-radius:24px;">
                  © {datetime.now().year} TeaseMe. All rights reserved.
                </td>
              </tr>
            </table>

          </td>
        </tr>
      </table>
    </body>
    </html>
    """

    body_text = f"""
Your TeaseMe profile is live 🎉

Open your profile:
{public_url}

© {datetime.now().year} TeaseMe. All rights reserved.
""".strip()

    return send_email_via_ses(to_email, subject, body_html, body_text)

def send_influencer_survey_completed_email_to_promoter(
    *,
    to_email: str,
    influencer_username: str,
    influencer_full_name: str | None = None,
    influencer_email: str | None = None,
):
    subject = "Influencer completed TeaseMe survey"
    public_url = f"https://teaseme.live/{influencer_username}"

    influencer_line = influencer_username
    if influencer_full_name:
        influencer_line = f"{influencer_full_name} (@{influencer_username})"

    body_html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Influencer survey completed</title>
</head>
<body style="background:#f7f8fc;padding:0;margin:0;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f7f8fc;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="520" cellpadding="0" cellspacing="0" border="0"
          style="background:#fff;border-radius:24px;box-shadow:0 10px 32px rgba(50,50,93,0.10),0 2px 4px rgba(0,0,0,0.07);overflow:hidden;">
          <tr>
            <td align="center" style="padding:28px 30px 10px 30px;">
              <h2 style="font-family:'Arial Rounded MT Bold', Arial, sans-serif; font-size:26px; font-weight:bold; margin:0 0 12px 0; color:#444;">
                Influencer survey completed
              </h2>
              <p style="font-size:16px;color:#666;margin:0 0 16px 0;">
                {influencer_line} has finished their TeaseMe profile survey.
              </p>
              <p style="font-size:14px;color:#666;margin:0 0 16px 0;">
                Profile link: <a href="{public_url}" style="color:#FF5C74;text-decoration:none;">{public_url}</a>
              </p>
              {f'<p style="font-size:14px;color:#666;margin:0 0 16px 0;">Influencer email: {influencer_email}</p>' if influencer_email else ''}
              <p style="margin:22px 0 0 0; font-size:12px; color:#999;">
                This is an automated message from TeaseMe.
              </p>
            </td>
          </tr>
          <tr>
            <td align="center" style="padding:18px 0 12px 0;background:#e5e5e5;color:#bbb;font-size:14px;border-bottom-left-radius:24px;border-bottom-right-radius:24px;">
              © {datetime.now().year} TeaseMe. All rights reserved.
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    lines = [
        "Influencer survey completed",
        "",
        f"Influencer: {influencer_line}",
        f"Profile link: {public_url}",
    ]
    if influencer_email:
        lines.append(f"Influencer email: {influencer_email}")
    body_text = "\n".join(lines)

    return send_email_via_ses(to_email, subject, body_html, body_text)
