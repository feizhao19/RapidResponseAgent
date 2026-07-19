"""FastAPI entry point for RapidResponseAgent web UI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from web.api.models import (
    AskRequest,
    AskResponse,
    AssessmentJobResponse,
    SessionCreateRequest,
    SessionResponse,
    VlmPreferenceRequest,
    VlmReviewRequest,
)
from web.api.sessions import create_session, get_session_payload, list_episodes
from web.api.upload_service import get_job_payload, submit_assessment_upload
from web.api.jobs import cancel_job, start_vlm_review_job
from web.api.services import (
    get_aoi_detail,
    get_building_chip,
    get_buildings_geojson_wgs84,
    get_imagery_preview,
    list_aois,
    remove_aoi,
    resolve_data_file,
    run_ask,
    submit_vlm_preference,
)

app = FastAPI(
    title="RapidResponseAgent API",
    description="Interactive API for historical assessment QA, weather context, and AOI browsing.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/aois")
def api_list_aois() -> dict:
    try:
        return list_aois()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/aois/{aoi_id}")
def api_aoi_detail(aoi_id: str) -> dict:
    try:
        return get_aoi_detail(aoi_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/aois/{aoi_id}")
def api_delete_aoi(aoi_id: str, delete_files: bool = True) -> dict:
    try:
        return remove_aoi(aoi_id, delete_files=delete_files)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/aois/{aoi_id}/buildings")
def api_aoi_buildings(aoi_id: str) -> JSONResponse:
    try:
        payload = get_buildings_geojson_wgs84(aoi_id)
        return JSONResponse(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/aois/{aoi_id}/imagery/{which}")
def api_aoi_imagery(aoi_id: str, which: str) -> FileResponse:
    if which not in ("pre", "post"):
        raise HTTPException(status_code=400, detail="Imagery type must be 'pre' or 'post'")
    try:
        path = get_imagery_preview(aoi_id, which)  # type: ignore[arg-type]
        return FileResponse(path, media_type="image/jpeg")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/aois/{aoi_id}/buildings/{bld_id}/chip/{which}")
def api_building_chip(aoi_id: str, bld_id: str, which: str) -> FileResponse:
    if which not in ("pre", "post"):
        raise HTTPException(status_code=400, detail="Chip type must be 'pre' or 'post'")
    try:
        path = get_building_chip(aoi_id, bld_id, which)  # type: ignore[arg-type]
        return FileResponse(path, media_type="image/jpeg")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/data/{rel_path:path}")
def api_data_file(rel_path: str) -> FileResponse:
    try:
        path = resolve_data_file(rel_path)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    media = "application/octet-stream"
    suffix = path.suffix.lower()
    if suffix == ".png":
        media = "image/png"
    elif suffix == ".json":
        media = "application/json"
    elif suffix == ".geojson":
        media = "application/geo+json"
    elif suffix in {".jpg", ".jpeg"}:
        media = "image/jpeg"
    return FileResponse(path, media_type=media)


@app.post("/api/sessions", response_model=SessionResponse)
def api_create_session(body: SessionCreateRequest) -> SessionResponse:
    try:
        payload = create_session(title=body.title, session_id=body.session_id)
        return SessionResponse(**payload, messages=[])
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/sessions/{session_id}", response_model=SessionResponse)
def api_get_session(session_id: str) -> SessionResponse:
    try:
        return SessionResponse(**get_session_payload(session_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/sessions/{session_id}/episodes")
def api_session_episodes(session_id: str) -> dict:
    try:
        return {"session_id": session_id, "episodes": list_episodes(session_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/ask", response_model=AskResponse)
def api_ask(body: AskRequest) -> AskResponse:
    try:
        payload = run_ask(
            body.question.strip(),
            history=[turn.model_dump() for turn in body.history],
            session_id=body.session_id,
            active_aoi_id=body.active_aoi_id,
            use_llm=body.use_llm,
            retrieve_only=body.retrieve_only,
            intent_only=body.intent_only,
            model=body.model,
        )
        return AskResponse(**payload)
    except Exception as exc:  # noqa: BLE001 — surface orchestration errors to UI
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/assessments/upload", response_model=AssessmentJobResponse)
async def api_assessment_upload(
    post: UploadFile = File(..., description="Post-disaster GeoTIFF"),
    pre: UploadFile | None = File(None, description="Pre-disaster GeoTIFF (optional if auto_match_pre)"),
    auto_match_pre: bool = Form(False),
    session_id: str | None = Form(None),
    message: str | None = Form(None),
) -> AssessmentJobResponse:
    if pre is None and not auto_match_pre:
        raise HTTPException(
            status_code=400,
            detail="Upload a pre GeoTIFF or set auto_match_pre=true to search the local Maxar catalog.",
        )
    try:
        payload = await submit_assessment_upload(
            post=post,
            pre=pre,
            auto_match_pre=auto_match_pre,
            session_id=session_id,
            message=message,
        )
        return AssessmentJobResponse(**payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface upload/align failures to UI
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/assessments/jobs/{job_id}", response_model=AssessmentJobResponse)
def api_assessment_job(job_id: str) -> AssessmentJobResponse:
    try:
        return AssessmentJobResponse(**get_job_payload(job_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/assessments/jobs/{job_id}/cancel", response_model=AssessmentJobResponse)
def api_cancel_assessment_job(job_id: str) -> AssessmentJobResponse:
    try:
        cancel_job(job_id)
        return AssessmentJobResponse(**get_job_payload(job_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/aois/{aoi_id}/vlm-review", response_model=AssessmentJobResponse)
def api_start_vlm_review(aoi_id: str, body: VlmReviewRequest | None = None) -> AssessmentJobResponse:
    request = body or VlmReviewRequest()
    try:
        payload = start_vlm_review_job(
            aoi_id,
            mode=request.mode,  # type: ignore[arg-type]
            limit=request.limit,
            damaged_only=request.damaged_only,
            session_id=request.session_id,
        )
        return AssessmentJobResponse(**get_job_payload(str(payload["job_id"])))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface queue/start failures
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/aois/{aoi_id}/vlm-preference")
def api_vlm_preference(aoi_id: str, body: VlmPreferenceRequest) -> dict:
    """Record human agree/disagree on the default VLM answer for DPO training pairs."""
    try:
        return submit_vlm_preference(
            aoi_id,
            review_type=body.review_type,
            feature_id=body.feature_id,
            decision=body.decision,
            session_id=body.session_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
FRONTEND_ASSETS = FRONTEND_DIST / "assets"

if FRONTEND_ASSETS.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS), name="frontend-assets")


@app.get("/")
def spa_root() -> FileResponse:
    index = FRONTEND_DIST / "index.html"
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    raise HTTPException(
        status_code=503,
        detail="Frontend not built. Run `npm run build` in web/frontend or use Vite dev server on :5173.",
    )
