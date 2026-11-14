"""Additive workspace routes. The ASGI context includes response background tasks."""
import json
import shutil
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from starlette.datastructures import Headers, MutableHeaders, QueryParams, UploadFile

from app.core import config, llm
from app.core.store import store
from . import storage
from .importer import Proposal, propose, source_text, project_model

router = APIRouter(include_in_schema=False)


def reject(error: Exception) -> HTTPException:
    if isinstance(error, ValidationError):
        details = [{"loc": list(item["loc"]), "msg": item["msg"], "type": item["type"]}
                   for item in error.errors()]
        return HTTPException(422, detail=details)
    return HTTPException(422, detail=str(error))


@router.get("/api/workspace/projects")
def list_projects():
    return {"projects": storage.projects(), "deleted_projects": storage.deleted_projects()}


@router.delete("/api/workspace/projects/{project_id}")
def delete_workspace_project(project_id: str):
    try:
        return storage.delete_project(project_id)
    except ValueError as error:
        raise HTTPException(404, detail=str(error)) from None


@router.post("/api/workspace/projects/{project_id}/restore")
def restore_workspace_project(project_id: str):
    try:
        return storage.restore_project(project_id)
    except ValueError as error:
        raise HTTPException(404, detail=str(error)) from None


@router.get("/api/workspace/connections")
def list_connections():
    from .connections import snapshot
    return snapshot()


@router.get("/api/workspace/channel-target")
def channel_target():
    from .channels import snapshot
    return snapshot()


@router.post("/api/workspace/channel-target")
def set_channel_target(body: dict):
    from .channels import bind
    try:
        return bind(body)
    except ValueError as error:
        raise reject(error) from None


@router.post("/api/workspace/robot-programme")
def prepare_robot_programme():
    from .robot_programme import prepare
    try:
        return prepare()
    except llm.LLMError as error:
        raise HTTPException(503, detail=f"DeepSeek robot planning unavailable ({error.category}). No programme was changed.") from None
    except ValueError as error:
        raise reject(error) from None


@router.post("/api/workspace/projects/{project_id}/logo")
def project_logo(project_id: str):
    from .branding import generate
    try:
        return generate(project_id)
    except llm.LLMError as error:
        raise HTTPException(503, detail=f"DeepSeek logo generation unavailable ({error.category}).") from None
    except ValueError as error:
        raise reject(error) from None


@router.post("/api/workspace/import")
async def import_project(request: Request):
    form = await request.form()
    name, description = str(form.get("name", "")).strip(), str(form.get("description", "")).strip()
    files = [item for item in form.getlist("files") if isinstance(item, UploadFile)]
    if not name and not description and not files:
        raise HTTPException(422, detail="Describe the project or attach a source file")
    draft_id = storage.identifier("draft-")
    folder = storage.root() / "drafts" / draft_id
    folder.mkdir(parents=True)
    sources, contents, structured, warnings = [], [], None, []
    try:
        for index, upload in enumerate(files):
            original = Path(upload.filename or "source").name
            # The filename is only a display label; disk paths use generated safe names.
            path = folder / f"source-{index}{Path(original).suffix.lower()}"
            body = await upload.read(20 * 1024 * 1024 + 1)
            if len(body) > 20 * 1024 * 1024:
                raise ValueError("Each source file must be at most 20 MB")
            path.write_bytes(body)
            text = source_text(path)
            sources.append({"name": original, "kind": path.suffix.lstrip("."), "file": path.name})
            contents.append(f"Source: {original}\n{text}")
            if not text.strip():
                warnings.append(f"{original}: no extractable text. Scanned plans need a structured JSON geometry export.")
            if path.suffix == ".json":
                candidate = json.loads(body.decode("utf-8-sig"))
                if isinstance(candidate, dict) and "project" in candidate and "plan" in candidate:
                    if structured is not None:
                        raise ValueError("Import one structured project JSON at a time")
                    structured = candidate
        # Offload the synchronous provider call, preserving ContextVar isolation.
        from starlette.concurrency import run_in_threadpool
        supplied_geometry = bool(structured and any((drawing.get("geometry") or {}).get("walls") for drawing in structured.get("drawings", [])))
        if str(form.get("design_building", "false")).lower() == "true" and not supplied_geometry:
            from .concept import generate
            base = Proposal.model_validate({key: structured[key] for key in ("project", "plan", "drawings", "machines", "assumptions") if key in structured}) if structured else None
            proposal, design = await run_in_threadpool(generate, name, description, sources, contents, base)
            model_used = True
        else:
            proposal, model_used = await run_in_threadpool(propose, name, description, sources, contents, structured)
            if supplied_geometry:
                warnings.append("Supplied floor geometry was preserved, including differences between storeys. DeepSeek analysed the project without replacing those coordinates.")
        result = {"draft_id": draft_id, **proposal.model_dump(mode="json"), "warnings": warnings,
                  "sources": sources, "model_used": model_used,
                  "model_name": project_model() if model_used else None,
                  "input": {"name": name, "description": description}}
        if model_used:
            result["warnings"].append("DeepSeek-assisted setup requires review. Generated geometry is conceptual; uploaded source documents are preserved.")
        from .branding import propose as propose_brand
        try:
            result["brand"] = await run_in_threadpool(propose_brand, proposal.project)
        except (llm.LLMError, ValueError):
            result["warnings"].append("Project logo could not be prepared. You can generate it from the project card later.")
        storage.write_json(folder / "draft.json", result)
        return result
    except llm.LLMError as error:
        shutil.rmtree(folder)
        raise HTTPException(503, detail=f"Project setup model unavailable ({error.category}). No project was created.") from None
    except (ValueError, OSError) as error:
        shutil.rmtree(folder)
        raise reject(error) from None


@router.get("/api/workspace/import/{draft_id}")
def get_draft(draft_id: str):
    try:
        path = storage.root() / "drafts" / storage.safe(draft_id) / "draft.json"
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, detail="Import draft not found") from None


@router.post("/api/workspace/projects", status_code=201)
def create_project(body: dict):
    draft_id = body.get("draft_id")
    if not isinstance(draft_id, str):
        raise HTTPException(422, detail="draft_id is required")
    draft = get_draft(draft_id)
    with storage.LOCK:
        catalog = storage.catalog()
        previous = catalog.get("draft_projects", draft_id)
        if previous:
            return catalog.get("projects", previous["id"])
        try:
            fields = {key: body.get(key, draft.get(key, [])) for key in ("project", "plan", "drawings", "machines", "assumptions")}
            proposal = Proposal.model_validate(fields)
            project_id = storage.identifier("p-")
            proposal.project.id = project_id
            created = storage.now()
            seed = {**proposal.model_dump(mode="json"), "created_at": created,
                    "import": {key: draft.get(key) for key in ("draft_id", "model_used", "model_name", "warnings", "sources", "input")}}
            folder = storage.directory(project_id)
            storage.write_json(folder / "seed.json", seed)
            source_folder = folder / "files" / "import"
            source_folder.mkdir(parents=True, exist_ok=True)
            for source in draft.get("sources", []):
                shutil.copyfile(storage.root() / "drafts" / draft_id / storage.safe(source["file"]),
                                source_folder / storage.safe(source["file"]))
            for drawing in proposal.drawings:
                target = folder / "files" / "drawings" / drawing.sheet / drawing.revision
                target.mkdir(parents=True, exist_ok=True)
                if drawing.geometry:
                    geometry = drawing.geometry.model_dump(mode="json")
                    storage.write_json(target / "geometry.json", geometry)
                    _render_geometry(geometry, target)
                if drawing.source_file:
                    source = next((item for item in draft["sources"]
                                   if drawing.source_file in (item["file"], item["name"])), None)
                    if source is None:
                        raise ValueError("Drawing source_file must name an imported source")
                    if source["kind"] == "pdf":
                        shutil.copyfile(storage.root() / "drafts" / draft_id / source["file"], target / "sheet.pdf")
                        _render_pdf(target)
            with storage.selected(project_id, folder):
                storage.seed_current()
            result = storage.metadata(seed["project"], created)
            if draft.get("brand"):
                from .branding import save as save_brand
                save_brand(project_id, draft["brand"])
            catalog.put("projects", project_id, result)
            catalog.put("draft_projects", draft_id, {"id": project_id})
            return result
        except (ValueError, OSError) as error:
            if "folder" in locals() and folder.exists():
                shutil.rmtree(folder)
            raise reject(error) from None


def _render_geometry(geometry: dict, target: Path):
    from PIL import Image, ImageDraw, ImageFont
    scale = min(1200 / geometry["width"], 900 / geometry["height"])
    width, height = max(1, round(geometry["width"] * scale)), max(1, round(geometry["height"] * scale))
    levels = sorted({str(item.get("level") or geometry.get("level") or "")
                     for item in geometry["walls"] + geometry["rooms"]}) or [""]
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except OSError:
        font = ImageFont.load_default()
    pages = []
    for level in levels:
        image = Image.new("RGB", (width + 48, height + 88), "white")
        draw = ImageDraw.Draw(image)
        draw.text((24, 12), f'{geometry["sheet"]} / Rev {geometry["revision"]}' + (f" / Level {level}" if level else ""), font=font, fill="#263f4c")
        draw.text((24, 34), "Generated from structured geometry. Dimensions in millimetres.", font=font, fill="#444444")
        def point(x, y):
            return (24 + x * scale, 64 + y * scale)
        for wall in geometry["walls"]:
            if str(wall.get("level") or geometry.get("level") or "") != level:
                continue
            x1, y1, x2, y2 = (wall[key] for key in ("x1", "y1", "x2", "y2"))
            length = ((x2-x1)**2 + (y2-y1)**2)**.5
            ux, uy = (x2-x1)/length, (y2-y1)/length
            cursor = 0
            for opening in sorted((item for item in geometry["openings"] if item["wall"] == wall["id"]), key=lambda item: item["offset"]):
                start, end = opening["offset"], opening["offset"] + opening["width"]
                if start > cursor:
                    draw.line((*point(x1+ux*cursor, y1+uy*cursor), *point(x1+ux*start, y1+uy*start)), fill="#353839", width=max(1, round(wall["thickness"] * scale)))
                if opening["kind"] == "window":
                    draw.line((*point(x1+ux*start, y1+uy*start), *point(x1+ux*end, y1+uy*end)), fill="#216f89", width=1)
                cursor = max(cursor, end)
            if cursor < length:
                draw.line((*point(x1+ux*cursor, y1+uy*cursor), *point(x2, y2)), fill="#353839", width=max(1, round(wall["thickness"] * scale)))
        for room in geometry["rooms"]:
            if str(room.get("level") or geometry.get("level") or "") == level:
                draw.text(point(room["x"], room["y"]), room["label"], font=font, fill="#444444", anchor="mm")
        pages.append(image)
    columns = min(2, len(pages))
    rows = (len(pages) + columns - 1) // columns
    contact = Image.new("RGB", (pages[0].width * columns, pages[0].height * rows), "#edf0f2")
    for index, image in enumerate(pages):
        contact.paste(image, ((index % columns) * image.width, (index // columns) * image.height))
    contact.save(target / "sheet.png")
    pages[0].save(target / "sheet.pdf", "PDF", save_all=True, append_images=pages[1:], resolution=96)


def _render_pdf(target: Path):
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(target / "sheet.pdf") as document:
        if len(document):
            page = document[0]
            bitmap = page.render(scale=1.5)
            bitmap.to_pil().save(target / "sheet.png")
            bitmap.close()
            page.close()


@router.get("/api/workspace/drawings")
def drawing_register():
    from .drawings import register
    project_id = (store().get("project", "current") or storage.default_project())["id"]
    result = register(project_id)
    seed_file = config.data_dir() / "seed.json"
    if config.project_directory.get() is not None and seed_file.is_file():
        seed = json.loads(seed_file.read_text(encoding="utf-8"))
        result["model_name"] = (seed.get("import") or {}).get("model_name")
        result["model_summary"] = next((item for item in seed.get("assumptions", []) if item.startswith("DeepSeek building design:")), None)
    return result


@router.get("/media/projects/{project_id}/{kind}/{path:path}")
def project_media(project_id: str, kind: str, path: str):
    if storage.is_deleted(project_id):
        raise HTTPException(404, detail="Project was deleted. Restore it from Projects to open its files.")
    default = storage.default_project()["id"]
    if project_id != default and storage.catalog().get("projects", project_id) is None:
        raise HTTPException(404, detail="Project not found")
    if kind == "files":
        base = config.base_data_dir() / "files" if project_id == default else storage.directory(project_id) / "files"
    elif kind == "drawings":
        base = config.ROOT / "data" / "drawings" if project_id == default else storage.directory(project_id) / "files" / "drawings"
    elif kind == "mock" and project_id == default:
        base = config.ROOT / "mocks" / "assets"
    else:
        raise HTTPException(404, detail="Media not found")
    target = (base / path).resolve()
    if base.resolve() not in target.parents or not target.is_file():
        raise HTTPException(404, detail="Media not found")
    return FileResponse(target)


def _scoped_urls(value, project_id):
    if isinstance(value, dict):
        return {key: _scoped_urls(item, project_id) for key, item in value.items()}
    if isinstance(value, list):
        return [_scoped_urls(item, project_id) for item in value]
    if isinstance(value, str):
        for prefix, kind in (("/media/files/", "files"), ("/media/mock/", "mock")):
            if value.startswith(prefix):
                return f"/media/projects/{project_id}/{kind}/{value[len(prefix):]}"
    return value


class WorkspaceMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        channel = next((name for name in ("telegram", "email")
                        if scope["path"].startswith(f"/api/channels/{name}/")), None)
        if channel:
            from . import channels
            with channels.selected(channel) as enabled:
                if not enabled:
                    return await JSONResponse({"detail": "This channel's project binding is disabled or unavailable."}, status_code=409)(scope, receive, send)
                identity = channels.target_id(channel)
                return await self._run(scope, receive, send, identity, config.project_directory.get() is not None)
        selected = Headers(scope=scope).get("x-aurora-project")
        if not selected and scope["method"] == "GET" and scope["path"].startswith("/api/"):
            selected = QueryParams(scope.get("query_string", b"")).get("project")
        default = storage.default_project()["id"]
        identity = selected or default
        if scope["path"].startswith("/api/") and not scope["path"].startswith("/api/workspace/") and storage.is_deleted(identity):
            return await JSONResponse({"detail": "Project was deleted. Restore it from Projects."}, status_code=404)(scope, receive, send)
        if selected and selected != default:
            if storage.catalog().get("projects", selected) is None or storage.is_deleted(selected):
                return await JSONResponse({"detail": "Project not found"}, status_code=404)(scope, receive, send)
            with storage.selected(selected, storage.directory(selected)):
                return await self._run(scope, receive, send, selected, True)
        return await self._run(scope, receive, send, default, False)

    async def _run(self, scope, receive, send, project_id, custom):
        if custom and scope["path"].startswith("/api/channels/") and not scope["path"].startswith(("/api/channels/telegram/", "/api/channels/email/")):
            return await JSONResponse({"detail": "Connect this project's own message channel before polling or receiving shared-account messages."}, status_code=409)(scope, receive, send)
        if custom and scope["path"].startswith("/media/mock/"):
            return await JSONResponse({"detail": "Media not found"}, status_code=404)(scope, receive, send)
        if custom and scope["path"] == "/api/demo/reset" and scope["method"] == "POST":
            from app import activity
            from app.core import pipeline
            with pipeline._lock:
                project = storage.seed_current()
                activity.clear()
            return await JSONResponse(project)(scope, receive, send)
        if custom and scope["path"] == "/api/demo/next" and scope["method"] == "POST":
            return await JSONResponse(None)(scope, receive, send)
        start, chunks = None, []
        async def scoped_send(message):
            nonlocal start
            if message["type"] == "http.response.start":
                start = message
                if "application/json" not in Headers(raw=message["headers"]).get("content-type", ""):
                    await send(message)
                    start = None
            elif message["type"] == "http.response.body" and start is not None:
                chunks.append(message.get("body", b""))
                if not message.get("more_body"):
                    body = json.dumps(_scoped_urls(json.loads(b"".join(chunks)), project_id), ensure_ascii=False).encode()
                    MutableHeaders(scope=start)["content-length"] = str(len(body))
                    await send(start)
                    await send({"type": "http.response.body", "body": body})
            else:
                await send(message)
        await self.app(scope, receive, scoped_send)


def install(app: FastAPI):
    if getattr(app.state, "workspace_installed", False):
        return
    before = len(app.router.routes)
    app.include_router(router)
    # The existing app ends with a SPA catchall. Additive routes must precede it.
    added = app.router.routes[before:]
    del app.router.routes[before:]
    app.router.routes[0:0] = added
    app.add_middleware(WorkspaceMiddleware)
    app.state.workspace_installed = True
