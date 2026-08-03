import os
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import SystemReferenceDocument
from app.schemas import ReferenceDocumentOut, ReferenceDocumentListOut, ReferenceDocumentUpdate
from app.storage import compute_sha256, save_file, read_file, file_exists
from app.species_exhibit.routes import router as species_exhibit_router

router = APIRouter()

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
CALYX_API_KEY = os.getenv("CALYX_API_KEY", "")

VALID_DOCUMENT_TYPES = [
    "AOS_JUDGING_SCORE_SHEET",
    "AOS_JUDGING_ENTRY_FORM",
    "AOS_AWARDS_CRITERIA_CCM_CCE_AQ",
    "AOS_JUDGES_STYLE_BOOK",
    "OTHER_REFERENCE"
]


def require_admin(api_key: str = None):
    effective_key = ADMIN_API_KEY or CALYX_API_KEY
    if not effective_key:
        raise HTTPException(status_code=503, detail="Admin API key not configured")
    if api_key != effective_key:
        raise HTTPException(status_code=403, detail="Admin access required")


@router.get("/reference-docs", response_model=list[ReferenceDocumentListOut])
def list_reference_docs(db: Session = Depends(get_db)):
    docs = db.execute(
        select(SystemReferenceDocument).where(SystemReferenceDocument.is_active == True)
    ).scalars().all()
    return docs


@router.get("/reference-docs/{doc_id}", response_model=ReferenceDocumentOut)
def get_reference_doc(doc_id: str, db: Session = Depends(get_db)):
    doc = db.get(SystemReferenceDocument, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/reference-docs/{doc_id}/download")
def download_reference_doc(doc_id: str, db: Session = Depends(get_db)):
    doc = db.get(SystemReferenceDocument, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not file_exists(doc.file_path):
        raise HTTPException(status_code=404, detail="File not found on storage")
    
    data = read_file(doc.file_path)
    filename = doc.title.replace(" ", "_") + ".pdf"
    return Response(
        content=data,
        media_type=doc.mime_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'}
    )


@router.post("/admin/reference-docs", response_model=ReferenceDocumentOut)
def upload_reference_doc(
    document_type: str = Form(...),
    title: str = Form(...),
    version_label: str = Form(...),
    source_org: str = Form("AOS"),
    source_url: str = Form(None),
    notes: str = Form(None),
    file: UploadFile = File(...),
    api_key: str = Form(None),
    db: Session = Depends(get_db)
):
    require_admin(api_key)
    
    if document_type not in VALID_DOCUMENT_TYPES:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid document_type. Must be one of: {VALID_DOCUMENT_TYPES}"
        )
    
    if not file.content_type or "pdf" not in file.content_type.lower():
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    
    file_data = file.file.read()
    sha256 = compute_sha256(file_data)
    
    existing = db.execute(
        select(SystemReferenceDocument).where(
            SystemReferenceDocument.document_type == document_type,
            SystemReferenceDocument.version_label == version_label,
            SystemReferenceDocument.sha256 == sha256
        )
    ).scalar_one_or_none()
    
    if existing:
        return existing
    
    file_path = save_file(file_data, file.filename or "document.pdf")
    
    doc = SystemReferenceDocument(
        document_type=document_type,
        title=title,
        version_label=version_label,
        source_org=source_org,
        source_url=source_url,
        file_path=file_path,
        mime_type=file.content_type or "application/pdf",
        file_size_bytes=len(file_data),
        sha256=sha256,
        notes=notes
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.patch("/admin/reference-docs/{doc_id}", response_model=ReferenceDocumentOut)
def update_reference_doc(
    doc_id: str,
    update: ReferenceDocumentUpdate,
    api_key: str = None,
    db: Session = Depends(get_db)
):
    require_admin(api_key)
    
    doc = db.get(SystemReferenceDocument, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if update.is_active is not None:
        doc.is_active = update.is_active
    if update.notes is not None:
        doc.notes = update.notes
    
    db.commit()
    db.refresh(doc)
    return doc


# Platform composition point: app.main already mounts this router. Keeping the
# species exhibit as a nested router avoids duplicate application bootstrapping.
router.include_router(species_exhibit_router)
