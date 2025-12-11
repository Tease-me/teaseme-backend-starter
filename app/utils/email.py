import logging
import boto3
from app.core.config import settings
from datetime import datetime

log = logging.getLogger(__name__)

AWS_REGION = settings.AWS_REGION
SES_SENDER = settings.SES_SENDER
CONFIRM_BASE_URL = settings.SES_SERVER
AWS_ACCESS_KEY_ID = settings.AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY = settings.AWS_SECRET_ACCESS_KEY

ses_client = boto3.client("ses", region_name=AWS_REGION)

def send_verification_email(to_email: str, token: str):
    subject = "Confirm your email on TeaseMe!"
    confirm_url = f"{CONFIRM_BASE_URL}/verify-email?token={token}"
    logo_url = f"https://bucket-image-tease-me.s3.us-east-1.amazonaws.com/email_verify_header.png"

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
    survey_url = f"{CONFIRM_BASE_URL}/profile-survey-form?token={token}"
    logo_url = (
        "https://bucket-image-tease-me.s3.us-east-1.amazonaws.com/email_verify_header.png"
    )

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

                  <p style="font-size:14px;color:#666;margin:12px 0 24px 0;">
                    Your temporary password to access your creator area:
                  </p>

                  <div style="display:inline-block;padding:10px 18px;border-radius:8px;background:#f3f4ff;
                              font-family:monospace;font-size:16px;color:#333;margin-bottom:16px;">
                    {temp_password}
                  </div>

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

Your temporary password: {temp_password}

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
    logo_url = f"https://bucket-image-tease-me.s3.us-east-1.amazonaws.com/reset_password_header.png"

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