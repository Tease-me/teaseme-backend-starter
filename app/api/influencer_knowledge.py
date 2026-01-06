from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.db.models import InfluencerKnowledgeFile, Influencer
from app.utils.s3 import save_knowledge_file_to_s3, delete_file_from_s3
from app.services.knowledge_processor import process_knowledge_file
from sqlalchemy import select
import io
import asyncio
import logging

router = APIRouter(prefix="/influencer/{influencer_id}/knowledge", tags=["influencer_knowledge"])

log = logging.getLogger("influencer_knowledge")

ALLOWED_EXTENSIONS = {"pdf", "docx", "doc", "txt"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

@router.post("/upload")
async def upload_knowledge_file(
    influencer_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    # TODO: Add auth dependency here
):
    """
    Upload a knowledge file (PDF, Word, TXT) for an influencer.
    The file will be processed asynchronously in the background.
    """
    
    # 1. Validate influencer exists
    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise HTTPException(status_code=404, detail="Influencer not found")
    
    # 2. Validate file type
    file_ext = file.filename.split(".")[-1].lower() if "." in file.filename else ""
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400, 
            detail=f"File type not allowed. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    # 3. Read file
    content = await file.read()
    file_size = len(content)
    
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400, 
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE / 1024 / 1024}MB"
        )
    
    if file_size == 0:
        raise HTTPException(status_code=400, detail="File is empty")
    
    # 4. Upload to S3
    file_obj = io.BytesIO(content)
    try:
        s3_key = await save_knowledge_file_to_s3(
            file_obj, 
            file.filename, 
            file.content_type or "application/octet-stream",
            influencer_id
        )
    except Exception as e:
        log.error(f"Failed to upload file to S3: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to upload file to storage")
    
    # 5. Create database record
    knowledge_file = InfluencerKnowledgeFile(
        influencer_id=influencer_id,
        filename=file.filename,
        file_type=file_ext,
        s3_key=s3_key,
        file_size_bytes=file_size,
        status="processing"
    )
    db.add(knowledge_file)
    await db.commit()
    await db.refresh(knowledge_file)
    
    # 6. Process asynchronously (in background)
    # Create a new file object for processing (file_obj was already used for S3 upload)
    processing_file_obj = io.BytesIO(content)
    
    # Use asyncio.create_task to process in background
    async def process_file_task():
        # Create a new database session for the background task
        from app.db.session import SessionLocal

        try:
            async with SessionLocal() as task_db:
                await process_knowledge_file(
                    task_db, 
                    knowledge_file.id, 
                    processing_file_obj, 
                    file_ext, 
                    influencer_id
                )
        except Exception as e:
            log.error(f"Background processing failed for file {knowledge_file.id}: {e}", exc_info=True)
        finally:
            await task_db.close()
    
    asyncio.create_task(process_file_task())
    
    return {
        "file_id": knowledge_file.id,
        "filename": file.filename,
        "status": "processing",
        "message": "File uploaded successfully. Processing in background."
    }

@router.get("")
async def list_knowledge_files(
    influencer_id: str,
    db: AsyncSession = Depends(get_db)
):
    """List all knowledge files for an influencer"""
    # Validate influencer exists
    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise HTTPException(status_code=404, detail="Influencer not found")
    
    result = await db.execute(
        select(InfluencerKnowledgeFile)
        .where(InfluencerKnowledgeFile.influencer_id == influencer_id)
        .order_by(InfluencerKnowledgeFile.created_at.desc())
    )
    files = result.scalars().all()
    
    return [
        {
            "id": f.id,
            "filename": f.filename,
            "file_type": f.file_type,
            "file_size_bytes": f.file_size_bytes,
            "status": f.status,
            "error_message": f.error_message,
            "created_at": f.created_at,
            "updated_at": f.updated_at,
        }
        for f in files
    ]

@router.get("/test-search")
async def test_knowledge_search(
    influencer_id: str,
    query: str = Query(..., description="Search query to test"),
    db: AsyncSession = Depends(get_db),
    top_k: int = Query(5, description="Number of results to return")
):
    """
    Test endpoint to see what knowledge chunks are retrieved for a query.
    Useful for debugging and verifying the knowledge base is working.
    
    Example:
    GET /influencer/anna/knowledge/test-search?query=Glauco&top_k=3
    """
    from app.api.utils import get_embedding, search_influencer_knowledge
    
    # Validate influencer exists
    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise HTTPException(status_code=404, detail="Influencer not found")
    
    try:
        # Get embedding for the query
        query_embedding = await get_embedding(query)
        
        # Search knowledge base
        results = await search_influencer_knowledge(db, influencer_id, query_embedding, top_k=top_k)
        
        # Get chunk count for this influencer
        from sqlalchemy import func, select
        from app.db.models import InfluencerKnowledgeChunk
        chunk_count_result = await db.execute(
            select(func.count(InfluencerKnowledgeChunk.id))
            .where(InfluencerKnowledgeChunk.influencer_id == influencer_id)
        )
        total_chunks = chunk_count_result.scalar() or 0
        
        return {
            "query": query,
            "influencer_id": influencer_id,
            "total_chunks_available": total_chunks,
            "chunks_retrieved": len(results),
            "results": [
                {
                    "content": r["content"],
                    "content_length": len(r["content"]),
                    "content_preview": r["content"][:200] + "..." if len(r["content"]) > 200 else r["content"],
                    "metadata": r.get("metadata")
                }
                for r in results
            ]
        }
    except Exception as e:
        log.error(f"Error testing knowledge search: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error testing search: {str(e)}")

@router.get("/{file_id}")
async def get_knowledge_file(
    influencer_id: str,
    file_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get details of a specific knowledge file"""
    file_record = await db.get(InfluencerKnowledgeFile, file_id)
    if not file_record or file_record.influencer_id != influencer_id:
        raise HTTPException(status_code=404, detail="File not found")
    
    return {
        "id": file_record.id,
        "filename": file_record.filename,
        "file_type": file_record.file_type,
        "file_size_bytes": file_record.file_size_bytes,
        "status": file_record.status,
        "error_message": file_record.error_message,
        "created_at": file_record.created_at,
        "updated_at": file_record.updated_at,
    }

@router.delete("/{file_id}")
async def delete_knowledge_file(
    influencer_id: str,
    file_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Delete a knowledge file and all its chunks"""
    file_record = await db.get(InfluencerKnowledgeFile, file_id)
    if not file_record or file_record.influencer_id != influencer_id:
        raise HTTPException(status_code=404, detail="File not found")
    
    # Get S3 key before deletion
    s3_key = file_record.s3_key
    
    # Cascade delete will handle chunks
    await db.delete(file_record)
    await db.commit()
    
    # Delete from S3 (non-blocking, log errors but don't fail)
    try:
        await delete_file_from_s3(s3_key)
    except Exception as e:
        log.warning(f"Failed to delete S3 file {s3_key}: {e}")
    
    return {"ok": True, "message": "File deleted successfully"}

