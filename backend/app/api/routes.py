from __future__ import annotations
import logging
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import uuid
import aiofiles

from app.db.session import get_db, AsyncSessionLocal
from app.models.schemas import (
    ClipUploadResponse, ClipStatusResponse, VerdictResponse,
    HistoryResponse, HistoryItem, Clip, Claim, VerificationPackage,
    Verdict, ClaimVerdict, Source
)

from app.preprocessing import pipeline as preprocessing_pipeline
from app.mcie import (
    timeline_alignment, context_builder, visual_context, explicit_claim_detector,
    implied_claim_detector, entity_extraction, verification_target_selector,
    confidence_estimator
)
from app.vpg import query_generator, keyframe_selector, metadata_attachment
from app.reasoning import gemini_client
from app.config import (
    ALLOWED_VIDEO_TYPES,
    ENABLE_EXPERIMENTAL_STUB_VERIFICATION,
    MAX_UPLOAD_BYTES,
    UPLOAD_CHUNK_BYTES,
    UPLOADS_DIR,
)

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)


def _safe_filename(filename: str | None) -> str:
    """Remove client-supplied path components and keep a safe fallback name.

    Strips both POSIX and Windows-style separators regardless of the host
    OS: pathlib.Path only treats backslash as a separator on Windows, so a
    Windows-style path (e.g. from a client on Windows) would pass through
    unsanitized when this backend runs on Linux -- its typical deployment
    target, even if development happens on Windows.
    """
    raw = (filename or "clip.mp4").replace("\\", "/")
    candidate = Path(raw).name
    return candidate if candidate not in {"", ".", ".."} else "clip.mp4"

async def process_clip(clip_id: str):
    try:
        async with AsyncSessionLocal() as db:
            clip_res = await db.execute(select(Clip).where(Clip.clip_id == clip_id))
            clip = clip_res.scalar_one_or_none()
            if not clip:
                return

            # Stage: Preprocessing
            clip.stage = "preprocessing"
            clip.error_message = None
            await db.commit()
            preproc_out = await preprocessing_pipeline.run(clip.storage_path)
            clip.duration_sec = preproc_out["artifacts"]["duration_sec"]
            await db.commit()

            if not ENABLE_EXPERIMENTAL_STUB_VERIFICATION:
                raise RuntimeError(
                    "Preprocessing completed, but MCIE, VPG, and the reasoning provider are not yet "
                    "implemented. Verification was stopped to avoid returning a fabricated verdict."
                )

            # Stage: MCIE
            clip.stage = "mcie"
            await db.commit()
            ta_out = await timeline_alignment.run(preproc_out)
            cb_out = await context_builder.run(ta_out)
            vc_out = await visual_context.run(cb_out)
            ecd_out = await explicit_claim_detector.run(cb_out, vc_out)
            icd_out = await implied_claim_detector.run(cb_out, vc_out)
            ee_out = await entity_extraction.run(ecd_out, icd_out)
            vts_out = await verification_target_selector.run(ecd_out, ee_out)
            ce_out = await confidence_estimator.run(cb_out, ecd_out, icd_out)

            mcie_out = {
                "claim_id": str(uuid.uuid4()),
                **cb_out,
                **vts_out,
                **ecd_out,
                **icd_out,
                **ee_out,
                **vc_out,
                **ce_out,
                "keyframe_refs": [frame["frame_id"] for frame in preproc_out["candidate_keyframes"]],
            }

            # Persist the MCIE claim (was previously computed and discarded)
            explicit_claims = mcie_out.get("explicit_claims", [])
            primary_claim_text = explicit_claims[0]["text"] if explicit_claims else "No explicit claim detected."
            new_claim = Claim(
                claim_id=mcie_out["claim_id"],
                clip_id=clip_id,
                claim_type=mcie_out.get("claim_type"),
                verification_target=mcie_out.get("verification_target"),
                explicit_claims=mcie_out.get("explicit_claims", []),
                implied_claims=mcie_out.get("implied_claims", []),
                mcie_confidence=mcie_out.get("confidence"),
            )
            db.add(new_claim)
            await db.commit()

            # Stage: VPG
            clip.stage = "vpg"
            await db.commit()
            qg_out = await query_generator.run(mcie_out)
            ks_out = await keyframe_selector.run(mcie_out)
            vpg_out = await metadata_attachment.run(mcie_out, qg_out, ks_out)

            # Persist the Verification Package (was previously computed and discarded)
            new_package = VerificationPackage(
                claim_id=new_claim.claim_id,
                verification_query=vpg_out.get("verification_query"),
                priority_keyframes=vpg_out.get("priority_keyframes"),
                package_json=vpg_out,
            )
            db.add(new_package)
            await db.commit()

            # Stage: Reasoning
            clip.stage = "reasoning"
            await db.commit()
            reasoning_out = await gemini_client.get_verdict(vpg_out)

            # Save Results
            new_verdict = Verdict(
                clip_id=clip_id,
                package_id=new_package.package_id,
                claim_text=primary_claim_text,
                verdict=reasoning_out["verdict"],
                confidence=reasoning_out["confidence"],
                summary=reasoning_out["summary"],
                sources=reasoning_out["sources"]
            )
            db.add(new_verdict)
            clip.status = "completed"
            clip.stage = "completed"
            await db.commit()

    except Exception as exc:
        logger.exception("Error processing clip %s", clip_id)
        error_message = f"{type(exc).__name__}: {str(exc)}"[:1000]
        async with AsyncSessionLocal() as db:
            clip_res = await db.execute(select(Clip).where(Clip.clip_id == clip_id))
            clip = clip_res.scalar_one_or_none()
            if clip:
                clip.status = "failed"
                clip.stage = "failed"
                clip.error_message = error_message
                await db.commit()
        

@router.post("/clips", response_model=ClipUploadResponse, status_code=202)
async def upload_clip(background_tasks: BackgroundTasks, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    if file.content_type not in ALLOWED_VIDEO_TYPES:
        raise HTTPException(status_code=415, detail="Only MP4, MOV, and WebM video uploads are supported.")

    clip_id = str(uuid.uuid4())
    safe_filename = _safe_filename(file.filename)
    file_path = UPLOADS_DIR / f"{clip_id}_{safe_filename}"
    
    bytes_written = 0
    try:
        async with aiofiles.open(file_path, "wb") as out_file:
            while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                bytes_written += len(chunk)
                if bytes_written > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Video exceeds the upload size limit.")
                await out_file.write(chunk)
    except Exception:
        file_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    new_clip = Clip(clip_id=clip_id, storage_path=str(file_path))
    db.add(new_clip)
    await db.commit()

    background_tasks.add_task(process_clip, clip_id)

    return ClipUploadResponse(clip_id=clip_id)

@router.get("/clips/{clip_id}/status", response_model=ClipStatusResponse)
async def get_clip_status(clip_id: str, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Clip).where(Clip.clip_id == clip_id))
    clip = res.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    
    return ClipStatusResponse(
        clip_id=clip.clip_id,
        status=clip.status,
        stage=clip.stage,
        error_message=clip.error_message,
    )

@router.get("/clips/{clip_id}/verdict", response_model=VerdictResponse)
async def get_clip_verdict(clip_id: str, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Verdict).where(Verdict.clip_id == clip_id))
    verdicts = res.scalars().all()
    if not verdicts:
        raise HTTPException(status_code=404, detail="Verdict not found")
    
    claims = []
    for v in verdicts:
        claims.append(ClaimVerdict(
            claim_text=v.claim_text or "Unknown claim",
            verdict=v.verdict,
            confidence=v.confidence,
            summary=v.summary,
            sources=[Source(**s) for s in v.sources]
        ))
    return VerdictResponse(clip_id=clip_id, claims=claims)

@router.get("/history", response_model=HistoryResponse)
async def get_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    total = (await db.execute(select(func.count()).select_from(Verdict))).scalar_one()
    res = await db.execute(
        select(Verdict).order_by(Verdict.generated_at.desc()).offset(offset).limit(limit)
    )
    verdicts = res.scalars().all()
    
    results = []
    for v in verdicts:
        results.append(HistoryItem(
            clip_id=v.clip_id,
            verdict=v.verdict,
            generated_at=v.generated_at.isoformat()
        ))
    return HistoryResponse(total=total, results=results)