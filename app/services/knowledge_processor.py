import logging
import io
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import InfluencerKnowledgeFile, InfluencerKnowledgeChunk
from app.utils.document_parser import extract_text_from_pdf, extract_text_from_docx, chunk_text
from app.api.utils import get_embedding
from sqlalchemy import insert
from datetime import datetime, timezone

log = logging.getLogger("knowledge_processor")

async def process_knowledge_file(
    db: AsyncSession,
    file_id: int,
    file_obj: io.BytesIO,
    file_type: str,
    influencer_id: str
) -> None:
    """
    Process uploaded file: extract text, chunk, embed, and store.
    
    Args:
        db: Database session
        file_id: ID of the InfluencerKnowledgeFile record
        file_obj: BytesIO object containing file content
        file_type: File type ('pdf', 'docx', 'txt')
        influencer_id: ID of the influencer
    """
    try:
        log.info(f"Starting processing for file {file_id} (type: {file_type})")
        
        # 1. Extract text
        if file_type == "pdf":
            text = await extract_text_from_pdf(file_obj)
        elif file_type in ["docx", "doc"]:
            text = await extract_text_from_docx(file_obj)
        elif file_type == "txt":
            file_obj.seek(0)
            text = file_obj.read().decode("utf-8")
        else:
            raise ValueError(f"Unsupported file type: {file_type}")
        
        if not text or not text.strip():
            raise ValueError("No text extracted from file")
        
        log.info(f"Extracted {len(text)} characters from file {file_id}")
        
        # 2. Chunk text
        # Use smaller chunks for better semantic search (300 words with 50 word overlap)
        # This creates more chunks, improving retrieval accuracy
        chunks = chunk_text(text, chunk_size=300, overlap=50)
        if not chunks:
            raise ValueError("No chunks created from extracted text")
        
        log.info(f"Created {len(chunks)} chunks from file {file_id}")
        
        # 3. Embed and store chunks
        chunk_count = 0
        for chunk_data in chunks:
            try:
                embedding = await get_embedding(chunk_data["content"])
                
                await db.execute(
                    insert(InfluencerKnowledgeChunk).values(
                        file_id=file_id,
                        influencer_id=influencer_id,
                        chunk_index=chunk_data["metadata"]["chunk_index"],
                        content=chunk_data["content"],
                        embedding=embedding,
                        chunk_metadata=chunk_data["metadata"]
                    )
                )
                chunk_count += 1
            except Exception as e:
                log.error(f"Error embedding chunk {chunk_data['metadata']['chunk_index']} of file {file_id}: {e}")
                # Continue with other chunks even if one fails
                continue
        
        if chunk_count == 0:
            raise ValueError("Failed to embed any chunks")
        
        # 4. Update file status
        file_record = await db.get(InfluencerKnowledgeFile, file_id)
        if file_record:
            file_record.status = "completed"
            file_record.updated_at = datetime.now(timezone.utc)
            db.add(file_record)
        
        await db.commit()
        log.info(f"Successfully processed file {file_id}: {chunk_count} chunks stored")
        
    except Exception as e:
        log.exception(f"Error processing file {file_id}: {e}")
        # Update file status to failed
        try:
            file_record = await db.get(InfluencerKnowledgeFile, file_id)
            if file_record:
                file_record.status = "failed"
                file_record.error_message = str(e)
                file_record.updated_at = datetime.now(timezone.utc)
                db.add(file_record)
                await db.commit()
        except Exception as commit_error:
            log.error(f"Failed to update file status to failed: {commit_error}")
        raise

