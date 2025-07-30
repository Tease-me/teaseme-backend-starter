import boto3
from botocore.exceptions import ClientError
from app.core.config import settings

AWS_REGION = settings.AWS_REGION
SES_SENDER = settings.SES_SENDER
CONFIRM_BASE_URL = settings.SES_SERVER
AWS_ACCESS_KEY_ID = settings.AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY = settings.AWS_SECRET_ACCESS_KEY

ses_client = boto3.client("ses", region_name=AWS_REGION)

def send_verification_email(to_email: str, token: str):
    subject = "Confirm your email on TeaseMe!"
    confirm_url = f"{CONFIRM_BASE_URL}/auth/verify-email?token={token}"
    
    body_html = f"""
    <h2>Welcome to TeaseMe!</h2>
    <p>Click the link below to confirm your email address:</p>
    <a href="{confirm_url}">Confirm Email</a>
    """
    
    body_text = f"Welcome to TeaseMe!\nPlease confirm your email by clicking this link: {confirm_url}"

    return send_email_via_ses(to_email, subject, body_html, body_text)

def send_email_via_ses_old(to_email: str, subject: str, body_html: str, body_text: str = None):
    try:
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
        message_id = response["MessageId"]
        print(f"[SES] Email sent successfully! Message ID: {message_id}")
        return response
    except ClientError as e:
        print(f"[SES] Email sending failed: {e.response['Error']['Message']}")
        raise

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