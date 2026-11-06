# -*- coding: utf-8 -*-
"""
EDA Agent 后端服务（FastAPI）

单进程同时提供 REST API 与前端静态页面，一条命令即可启动：
    python run.py            # 或 uvicorn backend.main:app
    http://127.0.0.1:8000
"""

from __future__ import annotations

import os
import glob
import subprocess
import time
import uuid
import zipfile

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .agent import generate_design_json, apply_revision, extract_keywords, build_project_files, package_project
from .agent.validator import DesignError
from .kicad_gen.render_svg import build_svg
from .reports import work_report, operation_guide, hardware_requirements

app = FastAPI(title="EDA Agent", version="1.0.0", description="自然语言驱动的 KiCad 电路设计智能体")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = config.FRONTEND_DIR


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------
class GenerateRequest(BaseModel):
    requirement: str = Field(..., description="自然语言电路需求")
    use_llm: bool | None = Field(None, description="是否强制使用 LLM；None 表示自动")
    difficulty: str = Field("intermediate", description="难度：beginner/intermediate/advanced")
    style: str = Field("classic", description="电路板风格：classic/minimal/retro")


class RevisionRequest(BaseModel):
    design: dict = Field(..., description="当前电路设计 JSON")
    instruction: str = Field(..., description="修改指令（如：把电容换成 100nF）")


class OpenKicadRequest(BaseModel):
    zip_path: str = Field(..., description="生成的工程 zip 路径")


class BuildRequest(BaseModel):
    design: dict = Field(..., description="电路设计 JSON")
    project_name: str = Field("circuit", description="工程名")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok", "time": time.time()}


@app.get("/api/status")
def status():
    from .agent.llm import LLMClient
    client = LLMClient()
    if client.api_key:
        model, base = client.model, client.base_url
    elif config.FREE_LLM_ENABLED:
        model, base = config.FREE_LLM_MODEL, config.FREE_LLM_BASE_URL
    else:
        model, base = None, None
    return {
        "llm_available": client.available,
        "llm_mode": client.mode,
        "llm_model": model,
        "llm_base_url": base,
        "kicad_cli": config.KICAD_CLI or "未探测（本机可能未安装 KiCad，不影响生成原理图文件）",
    }


@app.post("/api/generate")
def generate(req: GenerateRequest):
    """步骤一：自然语言 → 设计 JSON（BOM + 网表）"""
    try:
        design, mode = generate_design_json(req.requirement, use_llm=req.use_llm)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"生成失败: {e}") from e
    return {"design": design, "mode": mode}


@app.post("/api/build")
def build(req: BuildRequest):
    """步骤二：设计 JSON → KiCad 工程文件 + BOM + 报告"""
    from .agent.validator import validate_design
    try:
        design = validate_design(req.design)
    except DesignError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    session = uuid.uuid4().hex[:8]
    out_dir = os.path.join(config.OUTPUT_DIR, session, req.project_name)
    try:
        files = build_project_files(design, out_dir, req.project_name)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"生成工程文件失败: {e}") from e

    # 生成三份报告
    requirement = design.get("title", "")
    report_md = work_report(design, requirement, "手动上传 JSON")
    guide_md = operation_guide(design, req.project_name)
    hw_md = hardware_requirements(design)

    with open(os.path.join(out_dir, "工作汇报.md"), "w", encoding="utf-8") as f:
        f.write(report_md)
    with open(os.path.join(out_dir, "操作指南.md"), "w", encoding="utf-8") as f:
        f.write(guide_md)
    with open(os.path.join(out_dir, "硬件需求.md"), "w", encoding="utf-8") as f:
        f.write(hw_md)

    zip_path = package_project(out_dir, req.project_name)

    # 读取 BOM / 网表内容返回给前端
    with open(files["bom_md"], "r", encoding="utf-8") as f:
        bom_md = f.read()
    with open(files["netlist_md"], "r", encoding="utf-8") as f:
        netlist_md = f.read()

    return {
        "session": session,
        "project_name": req.project_name,
        "files": list(files.values()),
        "download_zip": zip_path,
        "bom_md": bom_md,
        "netlist_md": netlist_md,
        "report_md": report_md,
        "guide_md": guide_md,
        "hardware_md": hw_md,
    }


@app.post("/api/design")
def design_once(req: GenerateRequest):
    """一步到位：自然语言 → 完整工程 + 全部报告 + 实时构图 SVG"""
    design, mode = generate_design_json(req.requirement, use_llm=req.use_llm, difficulty=req.difficulty)

    project_name = _slugify(design.get("title", "circuit"))
    session = uuid.uuid4().hex[:8]
    out_dir = os.path.join(config.OUTPUT_DIR, session, project_name)
    files = build_project_files(design, out_dir, project_name)

    report_md = work_report(design, req.requirement, mode)
    guide_md = operation_guide(design, project_name)
    hw_md = hardware_requirements(design)

    with open(os.path.join(out_dir, "工作汇报.md"), "w", encoding="utf-8") as f:
        f.write(report_md)
    with open(os.path.join(out_dir, "操作指南.md"), "w", encoding="utf-8") as f:
        f.write(guide_md)
    with open(os.path.join(out_dir, "硬件需求.md"), "w", encoding="utf-8") as f:
        f.write(hw_md)

    zip_path = package_project(out_dir, project_name)

    # 实时构图 SVG + 关键词
    svg = build_svg(design, req.style)
    keywords = extract_keywords(req.requirement)

    return {
        "design": design,
        "mode": mode,
        "session": session,
        "project_name": project_name,
        "style": req.style,
        "svg": svg,
        "keywords": keywords,
        "bom_md": files and _read(files["bom_md"]),
        "netlist_md": _read(files["netlist_md"]),
        "report_md": report_md,
        "guide_md": guide_md,
        "hardware_md": hw_md,
        "download_zip": zip_path,
    }


@app.post("/api/revision")
def revision(req: RevisionRequest):
    """对话式实时修改：把修改指令应用到已有设计，返回新设计 + 新 SVG"""
    try:
        new_design, mode = apply_revision(req.design, req.instruction)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"修改失败: {e}") from e

    project_name = _slugify(new_design.get("title", "circuit"))
    session = uuid.uuid4().hex[:8]
    out_dir = os.path.join(config.OUTPUT_DIR, session, project_name)
    files = build_project_files(new_design, out_dir, project_name)

    report_md = work_report(new_design, req.instruction, mode)
    guide_md = operation_guide(new_design, project_name)
    hw_md = hardware_requirements(new_design)
    with open(os.path.join(out_dir, "工作汇报.md"), "w", encoding="utf-8") as f:
        f.write(report_md)
    with open(os.path.join(out_dir, "操作指南.md"), "w", encoding="utf-8") as f:
        f.write(guide_md)
    with open(os.path.join(out_dir, "硬件需求.md"), "w", encoding="utf-8") as f:
        f.write(hw_md)

    zip_path = package_project(out_dir, project_name)

    return {
        "design": new_design,
        "mode": mode,
        "project_name": project_name,
        "svg": build_svg(new_design, "classic"),
        "bom_md": _read(files["bom_md"]),
        "netlist_md": _read(files["netlist_md"]),
        "report_md": report_md,
        "guide_md": guide_md,
        "hardware_md": hw_md,
        "download_zip": zip_path,
    }


def _read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def _slugify(s):
    import re
    # KiCad 工程文件名建议使用 ASCII，避免跨平台兼容问题
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_")
    return s[:40] or "circuit"


@app.get("/api/download")
def download(path: str):
    """下载生成的 zip（path 为绝对路径，仅限输出目录内）"""
    out = os.path.abspath(config.OUTPUT_DIR)
    full = os.path.abspath(path)
    if not full.startswith(out) or not os.path.isfile(full):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(full, filename=os.path.basename(full))


def _find_kicad():
    """探测本机 KiCad 可执行文件路径"""
    candidates = []
    base = r"C:\Program Files\KiCad"
    if os.path.isdir(base):
        for ver in os.listdir(base):
            for exe in ("kicad.exe", "eeschema.exe"):
                p = os.path.join(base, ver, "bin", exe)
                if os.path.isfile(p):
                    candidates.append(p)
    # 也查 PATH
    for exe in ("kicad", "eeschema"):
        found = shutil_which(exe)
        if found:
            candidates.append(found)
    return candidates[0] if candidates else None


def shutil_which(name):
    import shutil
    return shutil.which(name)


@app.post("/api/open-kicad")
def open_kicad(req: OpenKicadRequest):
    """解压工程 zip，并用本机 KiCad 打开 .kicad_pro"""
    out = os.path.abspath(config.OUTPUT_DIR)
    full = os.path.abspath(req.zip_path)
    if not full.startswith(out) or not os.path.isfile(full):
        raise HTTPException(status_code=404, detail="工程文件不存在")

    kicad = _find_kicad()
    if not kicad:
        raise HTTPException(status_code=400, detail="未检测到本机 KiCad，请下载工程包后手动打开")

    extract_dir = os.path.splitext(full)[0] + "_opened"
    os.makedirs(extract_dir, exist_ok=True)
    try:
        with zipfile.ZipFile(full) as z:
            z.extractall(extract_dir)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"解压失败: {e}") from e

    pro_files = glob.glob(os.path.join(extract_dir, "**", "*.kicad_pro"), recursive=True)
    if not pro_files:
        raise HTTPException(status_code=404, detail="工程包中未找到 .kicad_pro 文件")

    try:
        subprocess.Popen([kicad, pro_files[0]])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"启动 KiCad 失败: {e}") from e

    return {"ok": True, "kicad": kicad, "project": pro_files[0]}


# ---------------------------------------------------------------------------
# 前端静态资源（挂在最后，避免覆盖 /api 路由）
# ---------------------------------------------------------------------------
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")
