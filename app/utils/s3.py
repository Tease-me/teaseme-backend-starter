import boto3
import uuid
import io
from app.schemas.chat import MessageSchema
import logging
log = logging.getLogger("s3")

s3 = boto3.client("s3")
BUCKET_NAME = "bucket-audio-message-tease-me"

# Save audio file to S3 and return the S3 key
async def save_audio_to_s3(file_obj, filename, content_type, user_id):
    ext = filename.split('.')[-1] if '.' in filename else 'webm'
    key = f"useraudio/{user_id}/{uuid.uuid4()}.{ext}"
    file_obj.seek(0)
    s3.upload_fileobj(file_obj, BUCKET_NAME, key, ExtraArgs={"ContentType": content_type})
    return key

# Save IA-generated audio to S3 and return the S3 key
async def save_ia_audio_to_s3(audio_bytes: bytes, user_id: str) -> str:
    filename = f"iaudio/{user_id}/{uuid.uuid4()}.mp3"
    s3.upload_fileobj(io.BytesIO(audio_bytes), BUCKET_NAME, filename, ExtraArgs={"ContentType": "audio/mpeg"})
    return filename  # Return the S3 key, not URL

# Generate a presigned URL for accessing an S3 object
def generate_presigned_url(key: str, expires: int = 3600) -> str:
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET_NAME, "Key": key},
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
        channel=msg.channel
    )

# Save knowledge file to S3 and return the S3 key
async def save_knowledge_file_to_s3(file_obj, filename: str, content_type: str, influencer_id: str) -> str:
    """Save a knowledge file (PDF, DOCX, TXT) to S3"""
    ext = filename.split('.')[-1].lower() if '.' in filename else 'txt'
    key = f"knowledge/{influencer_id}/{uuid.uuid4()}.{ext}"
    file_obj.seek(0)
    s3.upload_fileobj(
        file_obj, 
        BUCKET_NAME, 
        key, 
        ExtraArgs={"ContentType": content_type}
    )
    return key

# Delete file from S3
async def delete_file_from_s3(key: str) -> None:
    """Delete a file from S3"""
    try:
        s3.delete_object(Bucket=BUCKET_NAME, Key=key)
    except Exception as e:
        # Log error but don't fail if file doesn't exist
        import logging
        log = logging.getLogger("s3")
        log.warning(f"Failed to delete S3 file {key}: {e}")

async def save_influencer_audio_to_s3(file_obj, filename: str, content_type: str, influencer_id: str) -> str:
    ext = filename.split(".")[-1] if "." in filename else "webm"
    key = f"influencer-audio/{influencer_id}/{uuid.uuid4()}.{ext}"
    file_obj.seek(0)
    s3.upload_fileobj(
        file_obj,
        BUCKET_NAME,
        key,
        ExtraArgs={"ContentType": content_type},
    )
    return key


async def save_influencer_ia_audio_to_s3(audio_bytes: bytes, influencer_id: str) -> str:
    key = f"influencer-iaudio/{influencer_id}/{uuid.uuid4()}.mp3"
    s3.upload_fileobj(
        io.BytesIO(audio_bytes),
        BUCKET_NAME,
        key,
        ExtraArgs={"ContentType": "audio/mpeg"},
    )
    return key


def get_influencer_audio_download_url(key: str, expires: int = 3600) -> str:
    return generate_presigned_url(key, expires)

async def list_influencer_audio_keys(influencer_id: str) -> list[str]:
    prefix = f"influencer-audio/{influencer_id}/"
    resp = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=prefix)

    contents = resp.get("Contents")
    if not contents:
        return []

    return [obj["Key"] for obj in contents]

def generate_presigned_urls_for_keys(keys: list[str], expires: int = 3600) -> list[str]:
    return [generate_presigned_url(key, expires) for key in keys]