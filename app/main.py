"""FastAPI 入口 (main.py)

路由：
  GET  /                 前端页面
  GET  /static/*         静态资源
  POST /api/balance      执行配平规划（不落库）
  POST /api/plans        配平并保存方案
  GET  /api/plans        历史方案列表
  GET  /api/plans/{id}   方案详情（用于回放 / 导出）
  DELETE /api/plans/{id} 删除方案
  GET  /api/plans/{id}/export   导出 JSON（attachment）
  GET  /api/health       健康检查
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import database
from .balancer import plan_balance

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="离心机转子配平规划器", version="1.0.0")


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class TubeIn(BaseModel):
    id: str = Field(..., min_length=1, description="试管编号")
    mass: float = Field(..., gt=0, description="试管质量 (g)")
    locked: bool = False
    locked_slot: Optional[int] = Field(None, ge=0, description="锁定槽位编号")


class BalanceRequest(BaseModel):
    n_slots: int = Field(..., ge=2, le=120)
    angles: Optional[list[float]] = Field(
        None, description="每槽角度(°)；缺省为 360/n 均布，0° 在顶部顺时针"
    )
    disabled: list[int] = Field(default_factory=list)
    tubes: list[TubeIn] = Field(default_factory=list)
    w1: float = Field(1.0, ge=0)
    w2: float = Field(0.15, ge=0)
    iterations: Optional[int] = Field(None, ge=0, le=500_000)
    rpm: Optional[float] = Field(None, ge=0)
    radius_mm: float = Field(100.0, gt=0, le=10000)
    seed: int = 42
    name: Optional[str] = Field(None, max_length=100)


def _run(req: BalanceRequest) -> tuple[dict, dict]:
    angles = req.angles
    if angles is None:
        angles = [360.0 * i / req.n_slots for i in range(req.n_slots)]
    if len(angles) != req.n_slots:
        raise HTTPException(422, "槽位角度数量与槽位数不一致")
    if len(set(req.disabled)) != len(req.disabled):
        raise HTTPException(422, "禁用槽位列表存在重复编号")

    tube_dicts = [t.model_dump() for t in req.tubes]
    # 先做数量约束，再检查编号唯一性
    if len(tube_dicts) > len([i for i in range(req.n_slots)
                              if i not in set(req.disabled)]):
        raise HTTPException(
            422,
            f"试管数量({len(tube_dicts)}) 超过可用槽位数量"
            f"({req.n_slots - len(set(req.disabled))})"
        )
    ids = [t["id"] for t in tube_dicts]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "试管编号存在重复")

    try:
        result = plan_balance(
            n_slots=req.n_slots,
            angles=angles,
            disabled=req.disabled,
            tubes=tube_dicts,
            w1=req.w1,
            w2=req.w2,
            iterations=req.iterations,
            rpm=req.rpm,
            radius_mm=req.radius_mm,
            seed=req.seed,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from e

    request_snapshot = req.model_dump()
    request_snapshot["angles"] = angles
    return request_snapshot, result


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok", "db": database.DB_PATH}


@app.post("/api/balance")
def api_balance(req: BalanceRequest):
    _, result = _run(req)
    return result


@app.post("/api/plans", status_code=201)
def api_create_plan(req: BalanceRequest):
    request_snapshot, result = _run(req)
    name = req.name or f"方案 {result['rotor']['n_slots']}槽/{len(req.tubes)}管"
    plan_id = database.save_plan(name, request_snapshot, result)
    return {"id": plan_id, "name": name, "result": result}


@app.get("/api/plans")
def api_list_plans():
    return {"plans": database.list_plans()}


@app.get("/api/plans/{plan_id}")
def api_get_plan(plan_id: int):
    plan = database.get_plan(plan_id)
    if plan is None:
        raise HTTPException(404, "方案不存在")
    return plan


@app.delete("/api/plans/{plan_id}")
def api_delete_plan(plan_id: int):
    if not database.delete_plan(plan_id):
        raise HTTPException(404, "方案不存在")
    return {"deleted": plan_id}


@app.get("/api/plans/{plan_id}/export")
def api_export_plan(plan_id: int):
    plan = database.get_plan(plan_id)
    if plan is None:
        raise HTTPException(404, "方案不存在")
    fname = f"balance_plan_{plan_id}.json"
    return JSONResponse(
        content=plan,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        media_type="application/json; charset=utf-8",
    )


# ---------------------------------------------------------------------------
# 前端静态资源
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


database.init_db()
