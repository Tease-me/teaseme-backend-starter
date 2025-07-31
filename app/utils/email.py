import boto3
from botocore.exceptions import ClientError
from app.core.config import settings
from datetime import datetime
AWS_REGION = settings.AWS_REGION
SES_SENDER = settings.SES_SENDER
CONFIRM_BASE_URL = settings.SES_SERVER
AWS_ACCESS_KEY_ID = settings.AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY = settings.AWS_SECRET_ACCESS_KEY

ses_client = boto3.client("ses", region_name=AWS_REGION)

def send_verification_email(to_email: str, token: str):
    subject = "Confirm your email on TeaseMe!"
    confirm_url = f"{CONFIRM_BASE_URL}/verify-email?token={token}"
    logo_url = f"https://bucket-image-tease-me.s3.us-east-1.amazonaws.com/3D-LogoTeaseMe-Light+1.png"

    body_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Confirm your email</title>
    </head>
    <body style="background-color:#f7f8fc;font-family:Arial,sans-serif;margin:0;padding:20px;">
        <div style="max-width:600px;margin:auto;background:#ffffff;border-radius:8px;box-shadow:0 2px 5px rgba(0,0,0,0.15);overflow:hidden;">
            
            <!-- Logo -->
            <div style="padding:20px;text-align:center;background-color:#FDB4C2;">
                <img src="{logo_url}" alt="TeaseMe" width="120" style="display:block;margin:auto;">
            </div>
            
            <!-- Body -->
            <div style="padding:30px;text-align:center;">
                <h2 style="color:#333;">Welcome to TeaseMe!</h2>
                <p style="color:#555;">Click the button below to confirm your email address.</p>
                <a href="{confirm_url}" style="display:inline-block;margin-top:20px;padding:12px 24px;background-color:#FF5C74;color:#ffffff;text-decoration:none;border-radius:4px;font-weight:bold;">
                    Confirm Email
                </a>
                <p style="margin-top:30px;font-size:12px;color:#999;">
                    If you didn't sign up, you can safely ignore this email.
                </p>
            </div>

            <!-- Footer -->
            <div style="background-color:#f1f1f1;padding:15px;text-align:center;font-size:12px;color:#aaa;">
                © {datetime.now().year} TeaseMe. All rights reserved.
            </div>

        </div>
    </body>
    </html>
    """

    body_text = f"Welcome to TeaseMe!\nPlease confirm your email by clicking this link: {confirm_url}"
    return send_email_via_ses(to_email, subject, body_html, body_text)

def send_email_via_ses(to_email, subject, body_html, body_text=None):
    ses_client = boto3.client(
        "ses",
        region_name="us-east-1",
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

def send_password_reset_email(to_email: str, token: str):
    subject = "Redefine your TeaseMe password"
    reset_url = f"{CONFIRM_BASE_URL}/reset-password?token={token}"
    logo_url = f"https://bucket-image-tease-me.s3.us-east-1.amazonaws.com/3D-LogoTeaseMe-Light+1.png"

    body_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Reset your password</title>
    </head>
    <body style="background-color:#f7f8fc;font-family:Arial,sans-serif;margin:0;padding:20px;">
        <div style="max-width:600px;margin:auto;background:#ffffff;border-radius:8px;box-shadow:0 2px 5px rgba(0,0,0,0.15);overflow:hidden;">
            <div style="padding:20px;text-align:center;background-color:#FDB4C2;">
                <img src="{logo_url}" alt="TeaseMe" width="120" style="display:block;margin:auto;">
            </div>
            <div style="padding:30px;text-align:center;">
                <h2 style="color:#333;">Forgot your password?</h2>
                <p style="color:#555;">Click below to reset your password.</p>
                <a href="{reset_url}" style="display:inline-block;margin-top:20px;padding:12px 24px;background-color:#FF5C74;color:#ffffff;text-decoration:none;border-radius:4px;font-weight:bold;">
                    Reset Password
                </a>
                <p style="margin-top:30px;font-size:12px;color:#999;">
                    If you didn't request this, please ignore this email.
                </p>
            </div>
            <div style="background-color:#f1f1f1;padding:15px;text-align:center;font-size:12px;color:#aaa;">
                © {datetime.now().year} TeaseMe. All rights reserved.
            </div>
        </div>
    </body>
    </html>
    """

    body_text = f"Reset your TeaseMe password by clicking this link: {reset_url}"

    return send_email_via_ses(to_email, subject, body_html, body_text)