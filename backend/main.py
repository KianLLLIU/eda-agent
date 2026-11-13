# -*- coding: utf-8 -*-
"""
EDA Agent 后端服务（FastAPI）v2.0

单进程同时提供 REST API 与前端静态页面 / 桌面窗口内容：
    python run.py                 # 浏览器版
    python desktop_launcher.py    # 桌面窗口版
    http://127.0.0.1:8000

v2.0 新增能力：
  - /api/chat   统一对话入口（意图路由 + 上下文 + 动态助手回复 + 结果一次返回）
  - /api/analyze 实时 NLU 预览；/api/capabilities 助手能力档案
  - /api/templates + /api/template 离线模板库
  - /api/history* 多轮会话持久化；/api/settings 运行时配置
  - /api/render /api/export /api/file /api/open-folder /api/design-from-json
  - 所有 v1 接口保持兼容
"""

from __future__ import annotations

import glob
import os
import platform
import subprocess
import time
import uuid
import zipfile

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, kicad_detect
from .agent import (
    generate_design_json,
    apply_revision,
    extract_keywords,
    build_project_files,
    package_project,
    list_templates,
    list_template_categories,
    load_template_by_name,
    nlu,
    assistant,
)
from .agent.validator import DesignError, validate_design
from .kicad_gen.render_svg import build_svg
from .kicad_gen.bom import bom_markdown, netlist_markdown
from .reports import work_report, operation_guide, hardware_requirements

app = FastAPI(
    title="EDA Agent",
    version=config.APP_VERSION,
    description="自然语言驱动的 KiCad 电路设计智能体",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = config.FRONTEND_DIR
STORE = assistant.STORE


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


class AnalyzeRequest(BaseModel):
    text: str = Field(..., description="待分析文本")
    has_design: bool = Field(False, description="当前是否已有设计")


class ChatRequest(BaseModel):
    message: str = Field(..., description="用户消息")
    session_id: str | None = Field(None, description="会话 ID，空则用当前会话")
    difficulty: str = Field("intermediate")
    style: str = Field("classic")
    project_name: str | None = Field(None)
    use_llm: bool | None = Field(None)
    force_new: bool = Field(False, description="强制新建会话")


class TemplateRequest(BaseModel):
    template_id: str = Field(..., description="模板 ID")
    style: str = Field("classic")
    difficulty: str = Field("intermediate")


class RenderRequest(BaseModel):
    design: dict
    style: str = Field("classic")


class ExportRequest(BaseModel):
    design: dict
    kind: str = Field("design", description="bom/netlist/report/guide/hardware/design/all")
    requirement: str = Field("", description="原始需求，用于报告标题")
    mode: str = Field("template")


class DesignFromJsonRequest(BaseModel):
    design: dict
    style: str = Field("classic")
    project_name: str | None = Field(None)
    difficulty: str = Field("intermediate")


class HistoryActivateRequest(BaseModel):
    session_id: str


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
def _read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def _slugify(s):
    import re
    # KiCad 工程文件名建议使用 ASCII，避免跨平台兼容问题
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", str(s)).strip("_")
    return s[:40] or "circuit"


def _status_dict():
    from .agent.llm import LLMClient
    client = LLMClient()
    s = config.llm_settings()
    if client.api_key:
        model, base = client.model, client.base_url
    elif client.free_enabled:
        model, base = s["free_model"], s["free_base_url"]
    else:
        model, base = None, None
    kicad = kicad_detect.detect()
    return {
        "llm_available": client.available,
        "llm_mode": client.mode,
        "llm_model": model,
        "llm_base_url": base,
        # 兼容 v1 字段：探测到的 exe 路径或友好提示
        "kicad_cli": kicad["path"] or "未探测（本机可能未安装 KiCad，不影响生成原理图文件）",
        # v2.0.1：结构化探测结果，供状态栏与设置面板展示
        "kicad": {
            "found": kicad["found"],
            "path": kicad["path"],
            "version": kicad["version"],
            "source": kicad["source"],
            "checked_count": kicad["checked_count"],
            "hint": kicad["hint"],
        },
        "version": config.APP_VERSION,
        "frozen": config.IS_FROZEN,
        "platform": platform.system(),
        "output_dir": config.OUTPUT_DIR,
        "data_dir": config.USER_DATA_DIR,
    }


def _safe_path(path: str):
    """路径安全校验：只允许访问输出目录内的文件"""
    out = os.path.abspath(config.OUTPUT_DIR)
    full = os.path.abspath(path)
    if not full.startswith(out) or not os.path.isfile(full):
        raise HTTPException(status_code=404, detail="文件不存在或不允许访问")
    return full


def assemble_result(design: dict, requirement: str, mode: str,
                    difficulty: str = "intermediate", style: str = "classic",
                    project_name: str | None = None, session: str | None = None) -> dict:
    """设计 JSON → 完整结果包（工程文件 + SVG + 报告 + zip）"""
    project_name = project_name or _slugify(design.get("title", "circuit"))
    session = session or uuid.uuid4().hex[:8]
    out_dir = os.path.join(config.OUTPUT_DIR, session, project_name)
    files = build_project_files(design, out_dir, project_name)

    report_md = work_report(design, requirement, mode)
    guide_md = operation_guide(design, project_name)
    hw_md = hardware_requirements(design)
    for fname, content in (("工作汇报.md", report_md), ("操作指南.md", guide_md),
                           ("硬件需求.md", hw_md)):
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as f:
            f.write(content)

    zip_path = package_project(out_dir, project_name)

    return {
        "design": design,
        "mode": mode,
        "session": session,
        "project_name": project_name,
        "style": style,
        "svg": build_svg(design, style),
        "bom_md": _read(files["bom_md"]),
        "netlist_md": _read(files["netlist_md"]),
        "report_md": report_md,
        "guide_md": guide_md,
        "hardware_md": hw_md,
        "download_zip": zip_path,
        "files": {k: os.path.basename(v) for k, v in files.items()},
        "output_dir": out_dir,
    }


def _find_kicad():
    """兼容旧调用：委托给多策略探测器，返回可执行文件路径或 None。

    v2.0.1 起不再只查 C:\\Program Files\\KiCad，详见 backend/kicad_detect.py。
    """
    return kicad_detect.detect()["path"]


def _open_in_os(path: str):
    """在系统文件管理器中打开目录（桌面端可用）"""
    if platform.system() == "Windows":
        os.startfile(path)  # noqa: S606
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


# ---------------------------------------------------------------------------
# 一、v1 兼容接口
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok", "time": time.time(), "version": config.APP_VERSION}


@app.get("/api/status")
def status():
    return _status_dict()


@app.post("/api/generate")
def generate(req: GenerateRequest):
    """步骤一：自然语言 → 设计 JSON（BOM + 网表）"""
    try:
        design, mode = generate_design_json(req.requirement, use_llm=req.use_llm)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"生成失败: {e}") from e
    return {"design": design, "mode": mode, "analysis": nlu.analyze(req.requirement)}


@app.post("/api/build")
def build(req: BuildRequest):
    """步骤二：设计 JSON → KiCad 工程文件 + BOM + 报告"""
    try:
        design = validate_design(req.design)
    except DesignError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    result = assemble_result(design, design.get("title", ""), "manual",
                             project_name=req.project_name)
    return {
        "session": result["session"],
        "project_name": result["project_name"],
        "files": list(result["files"].values()),
        "download_zip": result["download_zip"],
        "bom_md": result["bom_md"],
        "netlist_md": result["netlist_md"],
        "report_md": result["report_md"],
        "guide_md": result["guide_md"],
        "hardware_md": result["hardware_md"],
    }


@app.post("/api/design")
def design_once(req: GenerateRequest):
    """一步到位：自然语言 → 完整工程 + 全部报告 + 实时构图 SVG"""
    design, mode = generate_design_json(req.requirement, use_llm=req.use_llm, difficulty=req.difficulty)
    result = assemble_result(design, req.requirement, mode, req.difficulty, req.style)
    result["keywords"] = extract_keywords(req.requirement)
    result["analysis"] = nlu.analyze(req.requirement)
    return result


@app.post("/api/revision")
def revision(req: RevisionRequest):
    """对话式实时修改（LLM 优先，离线规则兜底）"""
    try:
        new_design, mode, changes = apply_revision(req.design, req.instruction)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"修改失败: {e}") from e
    result = assemble_result(new_design, req.instruction, mode)
    result["changes"] = changes
    return result


@app.get("/api/download")
def download(path: str):
    """下载生成的 zip（path 为绝对路径，仅限输出目录内）"""
    return FileResponse(_safe_path(path), filename=os.path.basename(path))


@app.post("/api/open-kicad")
def open_kicad(req: OpenKicadRequest):
    """解压工程 zip，并用本机 KiCad 打开 .kicad_pro"""
    full = _safe_path(req.zip_path)
    info = kicad_detect.detect()
    kicad = info["path"]
    if not kicad:
        raise HTTPException(
            status_code=400,
            detail="未检测到本机 KiCad（已检查 %d 处）。%s" % (info["checked_count"], info["hint"]),
        )

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
# 二、v2 新增：NLU / 助手能力 / 统一对话
# ---------------------------------------------------------------------------
@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    """实时 NLU 预览：前端输入框边打字边调用（建议 250ms 防抖）"""
    return nlu.analyze(req.text, has_design=req.has_design)


@app.get("/api/capabilities")
def capabilities():
    """助手能力档案 + 快捷指令 + 模板 + 动态欢迎语（前端启动时拉取）"""
    s = _status_dict()
    payload = assistant.capabilities_payload(s)
    payload["greeting"] = assistant.greeting(s)
    payload["templates"] = list_templates()
    payload["template_categories"] = list_template_categories()
    return payload


@app.post("/api/chat")
def chat(req: ChatRequest):
    """统一对话入口：意图识别 → 路由 → 生成/修改/解释/帮助 → 助手回复 + 结果

    前端只需调这一个接口，大幅简化交互逻辑，并天然拥有上下文记忆。
    """
    # 1. 会话
    conv = STORE.get(req.session_id) if req.session_id else None
    if conv is None:
        conv = STORE.current()
    if req.force_new:
        conv = STORE.create()

    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空")

    has_design = bool(conv.design)
    analysis = nlu.analyze(message, has_design=has_design)
    intent = analysis["intent"]["name"]
    status_info = _status_dict()

    # 明确要「换一个电路」时自动开新会话
    if intent == "generate" and has_design and any(
            k in message for k in ("新做", "另外做", "重新做", "换一个电路", "再做一个", "从头做")):
        conv = STORE.create()
        has_design = False
        analysis = nlu.analyze(message, has_design=False)

    ctx = {
        "has_design": has_design,
        "design": conv.design,
        "status": status_info,
        "style": req.style,
        "context_summary": conv.context_summary(),
    }
    reply_pack = assistant.build_reply(analysis, ctx)

    conv.add_turn("user", message, {"intent": intent, "confidence": analysis["confidence"]})
    conv.remember_keywords(analysis["keywords"])
    conv.last_intent = intent

    result = None
    changes = []

    # 2. 意图路由
    if intent in ("help", "status", "explain", "export", "render", "template", "reset"):
        if intent == "reset":
            conv = STORE.create()
            conv.add_turn("user", message, {"intent": intent})
            conv.remember_keywords(analysis["keywords"])
        elif intent == "explain" and has_design:
            reply_pack["reply"] = assistant.explain_design(conv.design)
        # 其余意图只回消息，由前端执行 action

    elif intent == "revise" and has_design:
        new_design, mode, changes = apply_revision(
            conv.design, message, analysis=analysis, context=conv.context_summary())
        result = assemble_result(new_design, message, mode, req.difficulty, req.style,
                                 project_name=req.project_name)
        result["keywords"] = nlu.keyword_terms(analysis)

    elif intent == "revise" and not has_design:
        # 用户想改但还没设计 → 转为生成
        analysis = nlu.analyze(message, has_design=False)
        reply_pack = assistant.build_reply(analysis, {**ctx, "has_design": False})
        design, mode = generate_design_json(
            message, use_llm=req.use_llm, difficulty=req.difficulty,
            analysis=analysis, context=conv.context_summary())
        result = assemble_result(design, message, mode, req.difficulty, req.style,
                                 project_name=req.project_name)
        result["keywords"] = nlu.keyword_terms(analysis)

    else:  # generate / unknown
        if intent == "unknown" or (analysis["intent"].get("fallback") and not has_design):
            pass  # 仍然尝试生成，避免卡住用户
        design, mode = generate_design_json(
            message, use_llm=req.use_llm, difficulty=req.difficulty,
            analysis=analysis, context=conv.context_summary())
        result = assemble_result(design, message, mode, req.difficulty, req.style,
                                 project_name=req.project_name)
        result["keywords"] = nlu.keyword_terms(analysis)

    # 3. 生成后的总结性回复（附加在意图回复之后）
    if result is not None:
        reply_pack["reply"] += "\n\n---\n\n" + assistant.success_reply(analysis, result, intent == "revise")
        if changes:
            reply_pack["reply"] += "\n\n**本次改动**：\n" + "\n".join("· " + c for c in changes)
        conv.design = result["design"]
        conv.project_name = result["project_name"]
        conv.zip_path = result["download_zip"]
        result["changes"] = changes

    conv.add_turn("assistant", reply_pack["reply"], {"intent": intent})
    STORE.commit()

    return {
        "reply": reply_pack["reply"],
        "suggestions": reply_pack["suggestions"],
        "actions": reply_pack["actions"],
        "intent": intent,
        "intent_label": analysis["intent"]["label"],
        "analysis": analysis,
        "result": result,
        "changes": changes,
        "session": conv.brief(),
        "session_id": conv.id,
        "has_design": bool(conv.design),
    }


# ---------------------------------------------------------------------------
# 三、v2 新增：模板 / 会话 / 设置 / 导出 / 工具
# ---------------------------------------------------------------------------
@app.get("/api/templates")
def templates():
    return {"templates": list_templates()}


@app.post("/api/template")
def apply_template(req: TemplateRequest):
    """直接套用离线模板，返回完整结果包"""
    try:
        design = load_template_by_name(req.template_id)
    except DesignError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    conv = STORE.current()
    result = assemble_result(design, "套用模板：" + req.template_id, "template",
                             req.difficulty, req.style,
                             project_name=_slugify(design.get("title", "circuit")))
    result["keywords"] = []
    conv.design = design
    conv.project_name = result["project_name"]
    conv.zip_path = result["download_zip"]
    conv.add_turn("user", "套用模板：" + req.template_id, {"intent": "template"})
    conv.add_turn("assistant", "已套用模板「%s」。" % design.get("title", req.template_id))
    STORE.commit()
    return {"result": result, "session": conv.brief()}


@app.get("/api/history")
def history():
    return {"sessions": STORE.list(), "current_id": STORE._current_id}


@app.post("/api/session/new")
def session_new():
    """新建会话（前端「新建」按钮），返回空会话与动态欢迎语"""
    conv = STORE.create()
    return {
        "session": conv.brief(),
        "session_id": conv.id,
        "greeting": assistant.greeting(_status_dict()),
    }


@app.post("/api/history/activate")
def history_activate(req: HistoryActivateRequest):
    conv = STORE.activate(req.session_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    result = None
    if conv.design:
        # 重新组装完整结果包，让前端恢复后所有标签页与下载都能直接用
        result = assemble_result(conv.design, conv.title, "restored")
    return {"session": conv.to_dict(), "result": result}


@app.delete("/api/history/{session_id}")
def history_delete(session_id: str):
    if not STORE.delete(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


@app.delete("/api/history")
def history_clear():
    STORE.clear_all()
    STORE.create()
    return {"ok": True}


@app.get("/api/settings")
def get_settings():
    return config.public_settings()


@app.post("/api/settings")
def set_settings(data: dict):
    return config.apply_settings(data)


@app.post("/api/render")
def render(req: RenderRequest):
    """只重绘 SVG（切换板色 / 编辑 JSON 后刷新，无需重新生成工程文件）"""
    try:
        design = validate_design(req.design)
    except DesignError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"svg": build_svg(design, req.style), "style": req.style}


@app.post("/api/design-from-json")
def design_from_json(req: DesignFromJsonRequest):
    """编辑后的设计 JSON → 重新生成工程与预览（前端 JSON 编辑器「应用修改」）"""
    try:
        design = validate_design(req.design)
    except DesignError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    result = assemble_result(design, design.get("title", ""), "manual-json",
                             req.difficulty, req.style, project_name=req.project_name)
    conv = STORE.current()
    conv.design = design
    conv.project_name = result["project_name"]
    conv.zip_path = result["download_zip"]
    STORE.commit()
    return {"result": result, "session": conv.brief()}


@app.post("/api/export")
def export(req: ExportRequest):
    """导出单份文本（前端用 Blob 直接下载，无需落盘）"""
    design = req.design
    mapping = {
        "bom": ("BOM.md", bom_markdown(design)),
        "netlist": ("NETLIST.md", netlist_markdown(design)),
        "report": ("工作汇报.md", work_report(design, req.requirement, req.mode)),
        "guide": ("操作指南.md", operation_guide(design, _slugify(design.get("title", "circuit")))),
        "hardware": ("硬件需求.md", hardware_requirements(design)),
        "design": ("design.json", __import__("json").dumps(design, ensure_ascii=False, indent=2)),
    }
    if req.kind == "all":
        text = "\n\n".join("# " + name + "\n\n" + content for name, content in mapping.values())
        return {"filename": "EDA-Agent-完整报告.md", "content": text, "mime": "text/markdown"}
    if req.kind not in mapping:
        raise HTTPException(status_code=400, detail="不支持的导出类型: " + req.kind)
    filename, content = mapping[req.kind]
    mime = "application/json" if req.kind == "design" else "text/markdown"
    return {"filename": filename, "content": content, "mime": mime}


@app.get("/api/file")
def get_file(path: str):
    """下载输出目录中的单个生成文件（BOM.md / design.json 等）"""
    return FileResponse(_safe_path(path), filename=os.path.basename(path))


@app.post("/api/open-folder")
def open_folder(data: dict | None = None):
    """在系统文件管理器打开目录（桌面端）"""
    target = (data or {}).get("path") or config.OUTPUT_DIR
    out = os.path.abspath(config.OUTPUT_DIR)
    full = os.path.abspath(target)
    if not (full == out or full.startswith(out)):
        full = out
    os.makedirs(full, exist_ok=True)
    try:
        _open_in_os(full)
        return {"ok": True, "path": full}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"打开目录失败: {e}") from e


# ---------------------------------------------------------------------------
# 四、v2.0.1 新增：KiCad 安装探测与手动配置
# ---------------------------------------------------------------------------
@app.get("/api/kicad")
def kicad_info():
    """KiCad 探测详情：路径 / 版本 / 来源 / 检查过的位置 / 建议"""
    return kicad_detect.detect()


@app.post("/api/kicad/detect")
def kicad_redetect():
    """强制重新探测（绕过 30 秒缓存）"""
    return kicad_detect.detect(force=True)


@app.post("/api/kicad/config")
def kicad_set_path(data: dict):
    """手动指定 kicad.exe 路径或安装目录；传空字符串表示恢复自动探测。

    路径会持久化到 ~/.eda-agent/settings.json，重启后依然生效。
    """
    raw = str((data or {}).get("path", "")).strip()
    normalized = kicad_detect.normalize_manual(raw) if raw else ""
    if normalized and not os.path.isfile(normalized):
        raise HTTPException(status_code=400, detail="路径不存在或不是文件：%s" % normalized)
    config.RUNTIME["kicad_path"] = normalized
    config.apply_settings({"kicad_path": normalized})
    kicad_detect.invalidate()
    return kicad_detect.detect(force=True)


@app.get("/api/app-info")
def app_info():
    """桌面窗口 / 关于面板使用"""
    return {
        "name": config.APP_NAME,
        "version": config.APP_VERSION,
        "frozen": config.IS_FROZEN,
        "desktop": bool(os.environ.get("EDA_AGENT_DESKTOP")),
        "platform": platform.system(),
        "python": platform.python_version(),
        "data_dir": config.USER_DATA_DIR,
        "output_dir": config.OUTPUT_DIR,
    }


# ---------------------------------------------------------------------------
# 前端静态资源（挂在最后，避免覆盖 /api 路由）
# ---------------------------------------------------------------------------
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")
