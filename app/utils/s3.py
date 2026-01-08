import boto3
import uuid
import io
import json
import logging
import botocore.exceptions

from app.core.config import settings
from app.schemas.chat import MessageSchema

 
log = logging.getLogger("s3")

s3 = boto3.client(
    "s3",
    aws_access_key_id=settings.S3_AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.SES_AWS_SECRET_ACCESS_KEY,
    region_name=getattr(settings, "AWS_REGION", None) or "us-east-1",
)

# Save audio file to S3 and return the S3 key
async def save_audio_to_s3(file_obj, filename, content_type, user_id):
    ext = filename.split('.')[-1] if '.' in filename else 'webm'
    key = f"useraudio/{user_id}/{uuid.uuid4()}.{ext}"
    file_obj.seek(0)
    s3.upload_fileobj(file_obj, settings.BUCKET_NAME, key, ExtraArgs={"ContentType": content_type})
    return key
 
# Save IA-generated audio to S3 and return the S3 key
async def save_ia_audio_to_s3(audio_bytes: bytes, user_id: str) -> str:
    filename = f"iaudio/{user_id}/{uuid.uuid4()}.mp3"
    s3.upload_fileobj(io.BytesIO(audio_bytes), settings.BUCKET_NAME, filename, ExtraArgs={"ContentType": "audio/mpeg"})
    return filename  # Return the S3 key, not URL

# Generate a presigned URL for accessing an S3 object
def generate_presigned_url(key: str, expires: int = 3600) -> str:
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.BUCKET_NAME, "Key": key},
        ExpiresIn=expires
    )

def message_to_schema_with_presigned(msg):
    audio_url = msg.audio_url
    if audio_url:
        audio_url = generate_presigned_url(audio_url)
    return MessageSchema(
        id=msg.id,
        chat_id=msg.chat_id,
        sender=msg.sender,
        content=msg.content,
        created_at=msg.created_at,
        audio_url=audio_url,
        channel=msg.channel,
        conversation_id=msg.conversation_id,
    )

# Save knowledge file to S3 and return the S3 key
async def save_knowledge_file_to_s3(file_obj, filename: str, content_type: str, influencer_id: str) -> str:
    """Save a knowledge file (PDF, DOCX, TXT) to S3"""
    ext = filename.split('.')[-1].lower() if '.' in filename else 'txt'
    key = f"knowledge/{influencer_id}/{uuid.uuid4()}.{ext}"
    file_obj.seek(0)
    s3.upload_fileobj(
        file_obj, 
        settings.BUCKET_NAME, 
        key, 
        ExtraArgs={"ContentType": content_type}
    )
    return key

# Delete file from S3
async def delete_file_from_s3(key: str) -> None:
    """Delete a file from S3"""
    try:
        s3.delete_object(Bucket=settings.BUCKET_NAME, Key=key)
    except botocore.exceptions.ClientError as e:
        error = e.response.get("Error", {})
        code = error.get("Code")
        msg = error.get("Message")

        if code == "NoSuchKey":
            log.info(f"S3 key {key} not found when deleting, ignoring.")
            return

        log.error(f"Failed to delete S3 file {key}: {code} - {msg}")
        raise
    except Exception as e:
        # fallback pra erros inesperados
        log.error(f"Unexpected error deleting S3 file {key}: {e}", exc_info=True)
        raise

async def save_influencer_audio_to_s3(file_obj, filename: str, content_type: str, influencer_id: str) -> str:
    ext = filename.split(".")[-1] if "." in filename else "webm"
    key = f"influencer-audio/{influencer_id}/{uuid.uuid4()}.{ext}"
    file_obj.seek(0)
    s3.upload_fileobj(
        file_obj,
        settings.BUCKET_NAME,
        key,
        ExtraArgs={"ContentType": content_type},
    )
    return key


async def save_influencer_ia_audio_to_s3(audio_bytes: bytes, influencer_id: str) -> str:
    key = f"influencer-iaudio/{influencer_id}/{uuid.uuid4()}.mp3"
    s3.upload_fileobj(
        io.BytesIO(audio_bytes),
        settings.BUCKET_NAME,
        key,
        ExtraArgs={"ContentType": "audio/mpeg"},
    )
    return key


def get_influencer_audio_download_url(key: str, expires: int = 3600) -> str:
    return generate_presigned_url(key, expires)

async def list_influencer_audio_keys(influencer_id: str) -> list[str]:
    prefix = f"influencer-audio/{influencer_id}/"
    resp = s3.list_objects_v2(Bucket=settings.BUCKET_NAME, Prefix=prefix)

    contents = resp.get("Contents")
    if not contents:
        return []

    return [obj["Key"] for obj in contents]

def generate_presigned_urls_for_keys(keys: list[str], expires: int = 3600) -> list[str]:
    return [generate_presigned_url(key, expires) for key in keys]
        
def _influencer_key(influencer_id: str, suffix: str) -> str:
    return f"{settings.INFLUENCER_PREFIX}/{influencer_id}/{suffix}"

def _normalize_image_ext(filename: str | None, content_type: str | None) -> str:
    ext = (filename.rsplit(".", 1)[-1] if filename and "." in filename else "").lower()
    if ext == "jpeg":
        return "jpg"
    if ext in {"jpg", "png", "webp"}:
        return ext

    if content_type:
        ct = content_type.lower().split(";", 1)[0].strip()
        if ct == "image/jpeg":
            return "jpg"
        if ct == "image/png":
            return "png"
        if ct == "image/webp":
            return "webp"

    return "jpg"

async def save_influencer_photo_to_s3(file_obj, filename: str, content_type: str, influencer_id: str) -> str:
    ext = _normalize_image_ext(filename, content_type)
    key = _influencer_key(influencer_id, f"profile.{ext}")
    file_obj.seek(0)
    s3.upload_fileobj(file_obj, settings.BUCKET_NAME, key, ExtraArgs={"ContentType": content_type})
    return key

async def save_influencer_video_to_s3(file_obj, filename: str, content_type: str, influencer_id: str) -> str:
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "mp4").lower()
    key = _influencer_key(influencer_id, f"video.{ext}")
    file_obj.seek(0)
    s3.upload_fileobj(file_obj, settings.BUCKET_NAME, key, ExtraArgs={"ContentType": content_type})
    return key

async def save_influencer_profile_to_s3(
    influencer_id: str,
    *,
    about: str | None = None,
    native_language: str | None = None,
    extras: dict | None = None,
) -> str:
    payload = {"about": about, "native_language": native_language, "extras": extras or {}}
    key = _influencer_key(influencer_id, "profile.json")
    s3.put_object(
        Bucket=settings.BUCKET_NAME,
        Key=key,
        Body=json.dumps(payload).encode("utf-8"),
        ContentType="application/json",
    )
    return key

async def get_influencer_profile_from_s3(influencer_id: str) -> dict:
    key = _influencer_key(influencer_id, "profile.json")
    try:
        obj = s3.get_object(Bucket=settings.BUCKET_NAME, Key=key)
        return json.loads(obj["Body"].read().decode("utf-8"))
    except Exception:
        return {}


async def save_user_photo_to_s3(file_obj, filename: str, content_type: str, user_id: int) -> str:
    """Save user profile photo to S3"""
    ext = _normalize_image_ext(filename, content_type)
    key = f"{settings.USER_PREFIX}/{user_id}/profile.{ext}"
    file_obj.seek(0)
    s3.upload_fileobj(file_obj, settings.BUCKET_NAME, key, ExtraArgs={"ContentType": content_type})
    return key


def generate_user_presigned_url(key: str, expires: int = 3600) -> str:
    """Generate presigned URL for user content (photos)"""
    return generate_presigned_url(key, expires)
