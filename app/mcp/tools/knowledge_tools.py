"""MCP Tools for Influencer Knowledge Base functionality."""

import logging
import io
import base64
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.mcp.server import mcp_server
from app.mcp.types import MCPTool
from app.db.models import InfluencerKnowledgeFile, InfluencerKnowledgeChunk, Influencer
from app.utils.s3 import save_knowledge_file_to_s3, delete_file_from_s3
from app.services.knowledge_processor import process_knowledge_file
from app.api.utils import get_embedding, search_influencer_knowledge
from typing import Any
import asyncio

log = logging.getLogger("mcp.tools.knowledge")

ALLOWED_EXTENSIONS = {"pdf", "docx", "doc", "txt"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


# Tool: List Knowledge Files
async def list_knowledge_files_tool(
    influencer_id: str,
    db: AsyncSession = None
) -> dict[str, Any]:
    """
    List all knowledge files for an influencer.

    Args:
        influencer_id: Influencer ID
        db: Database session (injected by dependency)

    Returns:
        Dictionary with list of knowledge files
    """
    if not db:
        raise ValueError("Database session required")

    # Validate influencer exists
    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise ValueError(f"Influencer '{influencer_id}' not found")

    result = await db.execute(
        select(InfluencerKnowledgeFile)
        .where(InfluencerKnowledgeFile.influencer_id == influencer_id)
        .order_by(InfluencerKnowledgeFile.created_at.desc())
    )
    files = result.scalars().all()

    return {
        "influencer_id": influencer_id,
        "files": [
            {
                "id": f.id,
                "filename": f.filename,
                "file_type": f.file_type,
                "file_size_bytes": f.file_size_bytes,
                "status": f.status,
                "error_message": f.error_message,
                "created_at": f.created_at.isoformat() if f.created_at else None,
                "updated_at": f.updated_at.isoformat() if f.updated_at else None,
            }
            for f in files
        ],
        "count": len(files),
    }


LIST_KNOWLEDGE_FILES_SCHEMA = MCPTool(
    name="list_knowledge_files",
    description="List all knowledge files (PDF, Word, TXT) uploaded for an influencer",
    inputSchema={
        "type": "object",
        "properties": {
            "influencer_id": {
                "type": "string",
                "description": "Influencer ID"
            }
        },
        "required": ["influencer_id"]
    }
)


# Tool: Get Knowledge File Details
async def get_knowledge_file_tool(
    influencer_id: str,
    file_id: int,
    db: AsyncSession = None
) -> dict[str, Any]:
    """
    Get details of a specific knowledge file.

    Args:
        influencer_id: Influencer ID
        file_id: Knowledge file ID
        db: Database session (injected by dependency)

    Returns:
        Dictionary with file details
    """
    if not db:
        raise ValueError("Database session required")

    file_record = await db.get(InfluencerKnowledgeFile, file_id)
    if not file_record or file_record.influencer_id != influencer_id:
        raise ValueError(f"Knowledge file '{file_id}' not found for influencer '{influencer_id}'")

    # Get chunk count for this file
    chunk_count_result = await db.execute(
        select(func.count(InfluencerKnowledgeChunk.id))
        .where(InfluencerKnowledgeChunk.file_id == file_id)
    )
    chunk_count = chunk_count_result.scalar() or 0

    return {
        "id": file_record.id,
        "influencer_id": file_record.influencer_id,
        "filename": file_record.filename,
        "file_type": file_record.file_type,
        "file_size_bytes": file_record.file_size_bytes,
        "status": file_record.status,
        "error_message": file_record.error_message,
        "chunk_count": chunk_count,
        "created_at": file_record.created_at.isoformat() if file_record.created_at else None,
        "updated_at": file_record.updated_at.isoformat() if file_record.updated_at else None,
    }


GET_KNOWLEDGE_FILE_SCHEMA = MCPTool(
    name="get_knowledge_file",
    description="Get details of a specific knowledge file including chunk count",
    inputSchema={
        "type": "object",
        "properties": {
            "influencer_id": {
                "type": "string",
                "description": "Influencer ID"
            },
            "file_id": {
                "type": "integer",
                "description": "Knowledge file ID"
            }
        },
        "required": ["influencer_id", "file_id"]
    }
)


# Tool: Delete Knowledge File
async def delete_knowledge_file_tool(
    influencer_id: str,
    file_id: int,
    db: AsyncSession = None
) -> dict[str, Any]:
    """
    Delete a knowledge file and all its chunks.

    Args:
        influencer_id: Influencer ID
        file_id: Knowledge file ID
        db: Database session (injected by dependency)

    Returns:
        Dictionary with deletion result
    """
    if not db:
        raise ValueError("Database session required")

    file_record = await db.get(InfluencerKnowledgeFile, file_id)
    if not file_record or file_record.influencer_id != influencer_id:
        raise ValueError(f"Knowledge file '{file_id}' not found for influencer '{influencer_id}'")

    # Get S3 key before deletion
    s3_key = file_record.s3_key
    filename = file_record.filename

    # Cascade delete will handle chunks
    await db.delete(file_record)
    await db.commit()

    # Delete from S3 (non-blocking, log errors but don't fail)
    try:
        await delete_file_from_s3(s3_key)
    except Exception as e:
        log.warning(f"Failed to delete S3 file {s3_key}: {e}")

    return {
        "ok": True,
        "message": f"Knowledge file '{filename}' deleted successfully",
        "file_id": file_id,
        "influencer_id": influencer_id,
    }


DELETE_KNOWLEDGE_FILE_SCHEMA = MCPTool(
    name="delete_knowledge_file",
    description="Delete a knowledge file and all its embedded chunks",
    inputSchema={
        "type": "object",
        "properties": {
            "influencer_id": {
                "type": "string",
                "description": "Influencer ID"
            },
            "file_id": {
                "type": "integer",
                "description": "Knowledge file ID to delete"
            }
        },
        "required": ["influencer_id", "file_id"]
    }
)


# Tool: Search Knowledge Base
async def search_knowledge_base_tool(
    influencer_id: str,
    query: str,
    top_k: int = 5,
    db: AsyncSession = None
) -> dict[str, Any]:
    """
    Search an influencer's knowledge base by semantic similarity.

    Args:
        influencer_id: Influencer ID
        query: Search query text
        top_k: Number of results to return (default: 5)
        db: Database session (injected by dependency)

    Returns:
        Dictionary with search results
    """
    if not db:
        raise ValueError("Database session required")

    # Validate influencer exists
    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise ValueError(f"Influencer '{influencer_id}' not found")

    try:
        # Get embedding for the query
        query_embedding = await get_embedding(query)

        # Search knowledge base
        results = await search_influencer_knowledge(db, influencer_id, query_embedding, top_k=top_k)

        # Get total chunk count for this influencer
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
        log.error(f"Error searching knowledge base: {e}", exc_info=True)
        raise ValueError(f"Error searching knowledge base: {str(e)}")


SEARCH_KNOWLEDGE_BASE_SCHEMA = MCPTool(
    name="search_knowledge_base",
    description="Search an influencer's knowledge base using semantic similarity. Useful for testing what information is available.",
    inputSchema={
        "type": "object",
        "properties": {
            "influencer_id": {
                "type": "string",
                "description": "Influencer ID"
            },
            "query": {
                "type": "string",
                "description": "Search query text"
            },
            "top_k": {
                "type": "integer",
                "description": "Number of results to return",
                "default": 5,
                "minimum": 1,
                "maximum": 20
            }
        },
        "required": ["influencer_id", "query"]
    }
)


# Tool: Upload Knowledge File (base64 encoded)
async def upload_knowledge_file_tool(
    influencer_id: str,
    filename: str,
    file_content_base64: str,
    file_type: str | None = None,
    db: AsyncSession = None
) -> dict[str, Any]:
    """
    Upload a knowledge file (PDF, Word, TXT) for an influencer.
    File content should be base64-encoded.

    Args:
        influencer_id: Influencer ID
        filename: Original filename (e.g., "cv.pdf")
        file_content_base64: Base64-encoded file content
        file_type: File type override (optional, auto-detected from filename if not provided)
        db: Database session (injected by dependency)

    Returns:
        Dictionary with upload result
    """
    if not db:
        raise ValueError("Database session required")

    # Validate influencer exists
    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise ValueError(f"Influencer '{influencer_id}' not found")

    # Determine file type
    if not file_type:
        file_ext = filename.split(".")[-1].lower() if "." in filename else ""
        if file_ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"File type not allowed. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}")
        file_type = file_ext
    else:
        file_type = file_type.lower()
        if file_type not in ALLOWED_EXTENSIONS:
            raise ValueError(f"File type not allowed. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}")

    # Decode base64 content
    try:
        content = base64.b64decode(file_content_base64)
    except Exception as e:
        raise ValueError(f"Invalid base64 content: {str(e)}")

    file_size = len(content)

    if file_size > MAX_FILE_SIZE:
        raise ValueError(f"File too large. Maximum size: {MAX_FILE_SIZE / 1024 / 1024}MB")

    if file_size == 0:
        raise ValueError("File is empty")

    # Upload to S3
    file_obj = io.BytesIO(content)
    try:
        s3_key = await save_knowledge_file_to_s3(
            file_obj,
            filename,
            f"application/{file_type}" if file_type != "txt" else "text/plain",
            influencer_id
        )
    except Exception as e:
        log.error(f"Failed to upload file to S3: {e}", exc_info=True)
        raise ValueError(f"Failed to upload file to storage: {str(e)}")

    # Create database record
    knowledge_file = InfluencerKnowledgeFile(
        influencer_id=influencer_id,
        filename=filename,
        file_type=file_type,
        s3_key=s3_key,
        file_size_bytes=file_size,
        status="processing"
    )
    db.add(knowledge_file)
    await db.commit()
    await db.refresh(knowledge_file)

    # Process asynchronously (in background)
    processing_file_obj = io.BytesIO(content)

    async def process_file_task():
        # Create a new database session for the background task
        from app.db.session import SessionLocal
        task_db = SessionLocal()
        try:
            await process_knowledge_file(
                task_db,
                knowledge_file.id,
                processing_file_obj,
                file_type,
                influencer_id
            )
        except Exception as e:
            log.error(f"Background processing failed for file {knowledge_file.id}: {e}", exc_info=True)
        finally:
            await task_db.close()

    asyncio.create_task(process_file_task())

    return {
        "file_id": knowledge_file.id,
        "filename": filename,
        "file_type": file_type,
        "file_size_bytes": file_size,
        "status": "processing",
        "message": "File uploaded successfully. Processing in background.",
        "influencer_id": influencer_id,
    }


UPLOAD_KNOWLEDGE_FILE_SCHEMA = MCPTool(
    name="upload_knowledge_file",
    description="Upload a knowledge file (PDF, Word, TXT) for an influencer. File content must be base64-encoded.",
    inputSchema={
        "type": "object",
        "properties": {
            "influencer_id": {
                "type": "string",
                "description": "Influencer ID"
            },
            "filename": {
                "type": "string",
                "description": "Original filename (e.g., 'cv.pdf', 'resume.docx')"
            },
            "file_content_base64": {
                "type": "string",
                "description": "Base64-encoded file content"
            },
            "file_type": {
                "type": "string",
                "description": "File type override (optional, auto-detected from filename)",
                "enum": ["pdf", "docx", "doc", "txt"]
            }
        },
        "required": ["influencer_id", "filename", "file_content_base64"]
    }
)


# Register tools with MCP server
def register_tools():
    """Register all knowledge base tools with the MCP server."""
    mcp_server.register_tool(
        "list_knowledge_files",
        list_knowledge_files_tool,
        LIST_KNOWLEDGE_FILES_SCHEMA
    )
    mcp_server.register_tool(
        "get_knowledge_file",
        get_knowledge_file_tool,
        GET_KNOWLEDGE_FILE_SCHEMA
    )
    mcp_server.register_tool(
        "delete_knowledge_file",
        delete_knowledge_file_tool,
        DELETE_KNOWLEDGE_FILE_SCHEMA
    )
    mcp_server.register_tool(
        "search_knowledge_base",
        search_knowledge_base_tool,
        SEARCH_KNOWLEDGE_BASE_SCHEMA
    )
    mcp_server.register_tool(
        "upload_knowledge_file",
        upload_knowledge_file_tool,
        UPLOAD_KNOWLEDGE_FILE_SCHEMA
    )
    log.info("Registered knowledge base tools")


# Auto-register on module import
register_tools()

