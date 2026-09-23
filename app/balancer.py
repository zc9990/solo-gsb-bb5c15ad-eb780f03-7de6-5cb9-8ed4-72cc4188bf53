"""
离心机转子配平核心算法 (balancer.py)

约定（与前端一致）：
  角度 0° 在正上方，沿顺时针方向递增。直接使用用户角度计算单位向量：
      x = m * sin(a),  y = -m * cos(a)        (a 为弧度)
  一阶不平衡量 U1 = Σ m_i * r * e^{j*θ_i}，合力矩方向与之一致。
  二阶不平衡量 U2 = Σ m_i * r * e^{j*2θ_i}（2倍频谐波分量，
      完美反对称布局时 U1=0 但 U2 最大，等距三点配平时 U2=0）。

优化策略（近似最优）：
  1. 贪心构造：试管按质量降序，每一对都枚举所有剩余空槽对（含两种
     朝向），选使当前合力目标最小的槽位放置；剩余奇数单管枚举空槽取
     最优；锁定试管固定不动，其余试管围绕它们布置。
  2. 模拟退火：仅移动未锁定试管（swap / move），目标
        J = w1 * |U1| + w2 * |U2|   (默认 w1=1, w2=0.15，
    U1 为一阶合力的主导安全指标，U2 作辅助谐波约束)
  3. 确定性爬山：在最优退火解上做局部邻域扫描收尾。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# 基础几何 / 物理
# ---------------------------------------------------------------------------

def wrap_deg(a: float) -> float:
    """把角度折叠到 (-180, 180]。"""
    a = (a + 180.0) % 360.0 - 180.0
    return 180.0 if a == -180.0 else a


def separation(a: float, b: float) -> float:
    """两角度之间的最短夹角，范围 [0, 180]。"""
    return abs(wrap_deg(a - b))


def grade_for(e1_norm: float) -> str:
    """
    根据 |U1|/(M*r) 的无量纲残差（0~1）评定配平等级。
    """
    if e1_norm < 0.01:
        return "A 优秀"
    if e1_norm < 0.03:
        return "B 良好"
    if e1_norm < 0.08:
        return "C 可用"
    if e1_norm < 0.15:
        return "D 较差"
    return "E 不可接受"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

@dataclass
class Tube:
    id: str
    mass: float
    locked: bool
    locked_slot: int | None = None


def plan_balance(
    n_slots: int,
    angles: list[float],
    disabled: list[int],
    tubes: list[dict],
    w1: float = 1.0,
    w2: float = 0.15,
    iterations: int | None = None,
    rpm: float | None = None,
    radius_mm: float = 100.0,
    seed: int = 42,
):
    """
    执行完整配平规划。

    tubes: [{"id", "mass", "locked", "locked_slot"}]
    返回完整结果 dict（可直接 JSON 序列化 / 入库）。
    失败时抛 ValueError(中文消息)。
    """
    # ---------- 校验 ----------
    if n_slots < 2:
        raise ValueError("槽位数至少为 2")
    if len(angles) != n_slots:
        raise ValueError("槽位角度数量与槽位数不一致")
    disabled_set = set(disabled)
    for d in disabled:
        if not (0 <= d < n_slots):
            raise ValueError(f"禁用槽位编号越界: {d}")
    avail_slots = [i for i in range(n_slots) if i not in disabled_set]
    if len(tubes) > len(avail_slots):
        raise ValueError(
            f"试管数量({len(tubes)}) 超过可用槽位数量({len(avail_slots)})"
        )
    for t in tubes:
        if t["mass"] <= 0:
            raise ValueError(f"试管 {t['id']} 质量必须为正数")
        if t.get("locked"):
            s = t.get("locked_slot")
            if s is None:
                raise ValueError(f"锁定试管 {t['id']} 未指定槽位")
            if not (0 <= s < n_slots):
                raise ValueError(f"锁定试管 {t['id']} 的槽位编号越界")
            if s in disabled_set:
                raise ValueError(f"锁定试管 {t['id']} 位于已禁用槽位 {s}")

    lock_claim = {}
    for t in tubes:
        if t.get("locked"):
            s = t["locked_slot"]
            if s in lock_claim:
                raise ValueError(
                    f"锁定试管 {t['id']} 与 {lock_claim[s]} 占用同一槽位 {s}"
                )
            lock_claim[s] = t["id"]

    if w1 < 0 or w2 < 0 or (w1 == 0 and w2 == 0):
        raise ValueError("目标权重 w1、w2 不能同时为 0")

    tube_objs = [
        Tube(
            id=t["id"],
            mass=float(t["mass"]),
            locked=bool(t.get("locked", False)),
            locked_slot=t.get("locked_slot"),
        )
        for t in tubes
    ]
    mass_of = {t.id: t.mass for t in tube_objs}
    locked_tubes = [t for t in tube_objs if t.locked]
    free_tubes = [t for t in tube_objs if not t.locked]
    total_mass = sum(mass_of.values())

    # ---------- 预计算槽位三角表（score 热循环避免反复调用三角函数） ----------
    SIN, COS, SIN2, COS2 = [], [], [], []
    for ang in angles:
        a = math.radians(ang)
        SIN.append(math.sin(a))
        COS.append(math.cos(a))
        SIN2.append(math.sin(2.0 * a))
        COS2.append(math.cos(2.0 * a))

    # ---------- 目标函数 ----------
    def score(placement):
        vx = vy = v2x = v2y = 0.0
        for tid, si in placement.items():
            m = mass_of[tid]
            vx += m * SIN[si]
            vy -= m * COS[si]
            v2x += m * SIN2[si]
            v2y -= m * COS2[si]
        u1 = math.hypot(vx, vy)
        u2 = math.hypot(v2x, v2y)
        return w1 * u1 + w2 * u2, u1, u2, (vx, vy, v2x, v2y)

    steps = []

    def snapshot(placement, phase, action, detail):
        s, u1, u2, vec = score(placement)
        return {
            "phase": phase,
            "action": action,
            "detail": detail,
            "placement": dict(placement),
            "u1": round(u1 * radius_mm, 4),   # g·mm（单位半径=1，乘 r mm）
            "u2": round(u2 * radius_mm, 4),
            "score": round(s, 6),
            "vx": round(vec[0], 6),
            "vy": round(vec[1], 6),
            "v2x": round(vec[2], 6),
            "v2y": round(vec[3], 6),
        }

    # ---------- 初始：放置锁定试管 ----------
    placement = {t.id: t.locked_slot for t in locked_tubes}
    if locked_tubes:
        for t in locked_tubes:
            steps.append(snapshot(
                placement, "lock",
                f"放置锁定试管 {t.id}",
                f"试管 {t.id}（{t.mass:g} g）被用户锁定在 {t.locked_slot} 号槽 "
                f"({angles[t.locked_slot]:g}°)，优化全程不移动。"
            ))
    else:
        steps.append(snapshot(
            placement, "lock", "空布局基线",
            "无锁定试管，从空转子开始构造布局。"
        ))

    occupied = set(placement.values())

    # ---------- 贪心构造 ----------
    free_sorted = sorted(free_tubes, key=lambda t: -t.mass)

    # 成对放置：每一对都枚举所有剩余可用槽对（含两种朝向），
    # 选择使"当前已放置试管"目标值最小的方案，避免固定槽对顺序导致
    # 相邻对堆叠（4 管时会直接找到十字布局）。
    free_opp_slots = [i for i in avail_slots if i not in occupied]
    k = 0
    while k + 1 < len(free_sorted):
        hi, lo = free_sorted[k], free_sorted[k + 1]
        k += 2
        best = None
        for x in range(len(free_opp_slots)):
            for y in range(x + 1, len(free_opp_slots)):
                si, sj = free_opp_slots[x], free_opp_slots[y]
                for a_id, b_id, a_slot, b_slot in (
                    (hi.id, lo.id, si, sj), (lo.id, hi.id, si, sj),
                ):
                    trial = dict(placement)
                    trial[a_id] = a_slot
                    trial[b_id] = b_slot
                    sc, u1, u2, _ = score(trial)
                    if best is None or sc < best[0]:
                        best = (sc, a_id, b_id, a_slot, b_slot, u1, u2,
                                abs(separation(angles[si], angles[sj]) - 180.0))
        _, a_id, b_id, a_slot, b_slot, u1, u2, err = best
        placement[a_id] = a_slot
        placement[b_id] = b_slot
        occupied.update((a_slot, b_slot))
        free_opp_slots = [i for i in free_opp_slots
                          if i not in (a_slot, b_slot)]
        err_txt = f"对径误差 {err:.1f}°" if not math.isnan(err) else "无对径槽对"
        steps.append(snapshot(
            placement, "greedy",
            f"成对放置 {a_id} + {b_id}",
            f"质量 {mass_of[a_id]:g} g 与 {mass_of[b_id]:g} g 的两只试管组成"
            f" {mass_of[a_id] + mass_of[b_id]:g} g 重对（优先分配重管，"
            f"降低对径误差的敏感度），放入槽 {a_slot} / {b_slot}"
            f"（{angles[a_slot]:g}° / {angles[b_slot]:g}°，{err_txt}）；"
            f"比较两种朝向后取合力较小者。当前 |U1|={u1 * radius_mm:.2f}，"
            f"|U2|={u2 * radius_mm:.2f} g·mm。"
        ))

    # 单管：放入使目标增量最小的空槽
    leftover = free_sorted[k:]
    for t in leftover:
        best = None
        for si in avail_slots:
            if si in occupied:
                continue
            trial = dict(placement)
            trial[t.id] = si
            sc, u1, u2, _ = score(trial)
            if best is None or sc < best[0]:
                best = (sc, si, u1, u2)
        _, si, u1, u2 = best
        placement[t.id] = si
        occupied.add(si)
        steps.append(snapshot(
            placement, "greedy",
            f"单管放置 {t.id} → 槽 {si}",
            f"剩余试管 {t.id}（{t.mass:g} g）无配对，枚举所有空槽并选取使"
            f"目标 J 最小的位置：槽 {si}（{angles[si]:g}°），"
            f"当前 |U1|={u1 * radius_mm:.2f}，|U2|={u2 * radius_mm:.2f} g·mm。"
        ))

    init_score, init_u1, init_u2, _ = score(placement)
    steps.append(snapshot(
        placement, "greedy-done", "贪心初始布局完成",
        f"初始布局就绪：|U1|={init_u1 * radius_mm:.2f}，"
        f"|U2|={init_u2 * radius_mm:.2f} g·mm，J={init_score:.3f}。"
        "随后进入模拟退火增量优化（只移动未锁定试管）。"
    ))

    # ---------- 模拟退火（维护合力向量，增量打分） ----------
    if iterations is None:
        iterations = min(120000, max(20000, 6000 * len(free_tubes)))
    rng = random.Random(seed)
    cur = dict(placement)
    vx0, vy0, v2x0, v2y0 = 0.0, 0.0, 0.0, 0.0
    for tid, si in cur.items():
        mm = mass_of[tid]
        vx0 += mm * SIN[si]
        vy0 -= mm * COS[si]
        v2x0 += mm * SIN2[si]
        v2y0 -= mm * COS2[si]
    V = [vx0, vy0, v2x0, v2y0]

    def j_of(v):
        return w1 * math.hypot(v[0], v[1]) + w2 * math.hypot(v[2], v[3])

    cur_score = j_of(V)
    best_pl = dict(cur)
    best_V = list(V)
    best_sc = cur_score
    free_ids = [t.id for t in free_tubes]
    locked_slots = {t.locked_slot for t in locked_tubes}
    free_slot_set = [i for i in avail_slots if i not in locked_slots]

    accepted = 0
    improvements = 0
    # 温度尺度取典型试管质量（一次单管移动的 ΔJ 量级与之相当）
    avg_mass = total_mass / max(1, len(tube_objs))
    T0 = max(0.2, avg_mass * 0.15)
    Tend = 1e-4
    max_keep = 40  # 优化过程最多保留的步数

    for it in range(1, iterations + 1):
        T = T0 * ((Tend / T0) ** (it / iterations))
        if len(free_ids) >= 2 and rng.random() < 0.55:
            # swap 两个未锁定试管（增量 ΔV）
            a, b = rng.sample(range(len(free_ids)), 2)
            ida, idb = free_ids[a], free_ids[b]
            sa, sb = cur[ida], cur[idb]
            ma, mb = mass_of[ida], mass_of[idb]
            dvx = (ma - mb) * (SIN[sb] - SIN[sa])
            dvy = -(ma - mb) * (COS[sb] - COS[sa])
            dv2x = (ma - mb) * (SIN2[sb] - SIN2[sa])
            dv2y = -(ma - mb) * (COS2[sb] - COS2[sa])
            trialV = [V[0] + dvx, V[1] + dvy, V[2] + dv2x, V[3] + dv2y]
            trial_sc = j_of(trialV)
            delta = trial_sc - cur_score
            if delta < 0 or rng.random() < math.exp(-delta / T):
                cur[ida], cur[idb] = sb, sa
                V = trialV
                cur_score = trial_sc
                accepted += 1
                if trial_sc < best_sc - 1e-12:
                    best_sc, best_pl, best_V = trial_sc, dict(cur), list(V)
                    improvements += 1
                    if improvements <= max_keep:
                        steps.append(snapshot(
                            cur, "optimize",
                            f"退火交换 {ida} ↔ {idb}",
                            f"交换槽 {sa} / {sb} 中的 {ida}、{idb}，"
                            f"J 下降至 {trial_sc:.3f}（接受）。"
                        ))
        else:
            # move 一个未锁定试管到空槽（70% 概率纯随机，30% 概率在
            # 至多 6 个随机候选槽里先选最优，帮助跨越需要协同移动的势垒）
            tid = rng.choice(free_ids) if free_ids else None
            if tid is None:
                break
            occ = set(cur.values())
            empties = [i for i in free_slot_set if i not in occ]
            if not empties:
                continue
            old_slot = cur[tid]
            mm = mass_of[tid]
            guided = rng.random() < 0.3 and len(empties) > 1
            if guided:
                cand_slots = rng.sample(empties, min(6, len(empties)))
                best_cand = None
                for cs in cand_slots:
                    tv = [
                        V[0] + mm * (SIN[cs] - SIN[old_slot]),
                        V[1] - mm * (COS[cs] - COS[old_slot]),
                        V[2] + mm * (SIN2[cs] - SIN2[old_slot]),
                        V[3] - mm * (COS2[cs] - COS2[old_slot]),
                    ]
                    sc = j_of(tv)
                    if best_cand is None or sc < best_cand[0]:
                        best_cand = (sc, cs, tv)
                trial_sc, new_slot, trialV = best_cand
            else:
                new_slot = rng.choice(empties)
                trialV = [
                    V[0] + mm * (SIN[new_slot] - SIN[old_slot]),
                    V[1] - mm * (COS[new_slot] - COS[old_slot]),
                    V[2] + mm * (SIN2[new_slot] - SIN2[old_slot]),
                    V[3] - mm * (COS2[new_slot] - COS2[old_slot]),
                ]
                trial_sc = j_of(trialV)
            delta = trial_sc - cur_score
            if delta < 0 or rng.random() < math.exp(-delta / T):
                cur[tid] = new_slot
                V = trialV
                cur_score = trial_sc
                accepted += 1
                if trial_sc < best_sc - 1e-12:
                    best_sc, best_pl, best_V = trial_sc, dict(cur), list(V)
                    improvements += 1
                    if improvements <= max_keep:
                        steps.append(snapshot(
                            cur, "optimize",
                            f"退火移动 {tid}: 槽 {old_slot} → {new_slot}",
                            f"把 {tid}（{mm:g} g）移到空槽 {new_slot}"
                            f"（{angles[new_slot]:g}°），J 下降至 "
                            f"{trial_sc:.3f}（接受）。"
                        ))

    # ---------- 确定性爬山收尾（增量打分，避免整局重算） ----------
    cur = dict(best_pl)

    def totals(pl):
        vx = vy = v2x = v2y = 0.0
        for tid, si in pl.items():
            m = mass_of[tid]
            vx += m * SIN[si]
            vy -= m * COS[si]
            v2x += m * SIN2[si]
            v2y -= m * COS2[si]
        return [vx, vy, v2x, v2y]

    def score_of(v):
        u1 = math.hypot(v[0], v[1])
        u2 = math.hypot(v[2], v[3])
        return w1 * u1 + w2 * u2

    V = totals(cur)
    cur_score = score_of(V)
    hill_rounds = 0
    hill_moves = 0
    improved = True
    while improved and hill_rounds < 50:
        improved = False
        hill_rounds += 1
        # move 邻域：把 tid 从 old 槽移到空槽 si 的增量
        for tid in free_ids:
            occ = set(cur.values())
            old = cur[tid]
            m = mass_of[tid]
            best_local = (cur_score, old)
            for si in free_slot_set:
                if si in occ:
                    continue
                dvx = m * (SIN[si] - SIN[old])
                dvy = -m * (COS[si] - COS[old])
                dv2x = m * (SIN2[si] - SIN2[old])
                dv2y = -m * (COS2[si] - COS2[old])
                sc = score_of([V[0] + dvx, V[1] + dvy,
                               V[2] + dv2x, V[3] + dv2y])
                if sc + 1e-12 < best_local[0]:
                    best_local = (sc, si)
            if best_local[1] != old:
                si = best_local[1]
                V[0] += m * (SIN[si] - SIN[old])
                V[1] -= m * (COS[si] - COS[old])
                V[2] += m * (SIN2[si] - SIN2[old])
                V[3] -= m * (COS2[si] - COS2[old])
                cur[tid] = si
                cur_score = best_local[0]
                improved = True
                hill_moves += 1
                if hill_moves <= 15:
                    steps.append(snapshot(
                        cur, "hillclimb",
                        f"爬山移动 {tid}: 槽 {old} → {si}",
                        f"邻域扫描：{tid} 移至槽 {si}"
                        f"（{angles[si]:g}°），"
                        f"J 下降至 {cur_score:.3f}。"
                    ))
        # swap 邻域：交换 ida、idb 的增量
        for a in range(len(free_ids)):
            for b in range(a + 1, len(free_ids)):
                ida, idb = free_ids[a], free_ids[b]
                sa, sb = cur[ida], cur[idb]
                if sa == sb:
                    continue
                ma, mb = mass_of[ida], mass_of[idb]
                dvx = (ma - mb) * (SIN[sb] - SIN[sa])
                dvy = -(ma - mb) * (COS[sb] - COS[sa])
                dv2x = (ma - mb) * (SIN2[sb] - SIN2[sa])
                dv2y = -(ma - mb) * (COS2[sb] - COS2[sa])
                sc = score_of([V[0] + dvx, V[1] + dvy,
                               V[2] + dv2x, V[3] + dv2y])
                if sc + 1e-12 < cur_score:
                    V[0] += dvx; V[1] += dvy; V[2] += dv2x; V[3] += dv2y
                    cur[ida], cur[idb] = sb, sa
                    cur_score = sc
                    improved = True
                    hill_moves += 1
                    if hill_moves <= 15:
                        steps.append(snapshot(
                            cur, "hillclimb",
                            f"爬山交换 {ida} ↔ {idb}",
                            f"交换槽 {sa} / {sb}，J 下降至 {sc:.3f}。"
                        ))
        best_pl = dict(cur)

    final_score, final_u1, final_u2, final_vec = score(best_pl)
    placement = best_pl

    # ---------- 最终指标 ----------
    u1_gmm = final_u1 * radius_mm
    u2_gmm = final_u2 * radius_mm
    e1 = final_u1 / total_mass if total_mass else 0.0
    e2 = final_u2 / total_mass if total_mass else 0.0
    u1_angle = math.degrees(math.atan2(final_vec[0], -final_vec[1])) if final_u1 > 1e-12 else 0.0
    u2_angle = (
        0.5 * math.degrees(math.atan2(final_vec[2], -final_vec[3]))
        if final_u2 > 1e-12 else 0.0
    )

    force_n = None
    if rpm:
        omega = 2.0 * math.pi * rpm / 60.0
        # |U1| 单位 g·mm -> kg·m: ×1e-6；F = ω² * U
        force_n = omega * omega * u1_gmm * 1e-6
    moment_nmm = force_n * radius_mm if force_n is not None else None  # N·mm

    steps.append(snapshot(
        placement, "final", "最终方案",
        f"优化结束：|U1|={u1_gmm:.2f} g·mm（{grade_for(e1)}），"
        f"|U2|={u2_gmm:.2f} g·mm。"
        + (f" {rpm:g} rpm 下离心合力约 {force_n:.2f} N。" if force_n is not None else "")
    ))

    # ---------- 配对依据分析（基于最终布局） ----------
    pairings = _explain_pairs(
        placement, mass_of, angles, disabled_set,
        radius_mm, locked_tubes and {t.id for t in locked_tubes} or set(),
    )

    return {
        "rotor": {
            "n_slots": n_slots,
            "angles": [round(a, 4) for a in angles],
            "disabled": sorted(disabled_set),
            "radius_mm": radius_mm,
            "rpm": rpm,
        },
        "tubes": [
            {
                "id": t.id, "mass": t.mass, "locked": t.locked,
                "locked_slot": t.locked_slot,
            }
            for t in tube_objs
        ],
        "weights": {"w1": w1, "w2": w2},
        "total_mass": round(total_mass, 6),
        "placement": placement,
        "metrics": {
            "u1_gmm": round(u1_gmm, 4),
            "u2_gmm": round(u2_gmm, 4),
            "u1_angle_deg": round(u1_angle, 2),
            "u2_direction_deg": round(u2_angle, 2),
            "e1_norm": round(e1, 6),
            "e2_norm": round(e2, 6),
            "grade": grade_for(e1),
            "centrifugal_force_n": round(force_n, 4) if force_n is not None else None,
            "resultant_moment_nmm": round(moment_nmm, 4) if moment_nmm is not None else None,
            "init_u1_gmm": round(init_u1 * radius_mm, 4),
            "init_u2_gmm": round(init_u2 * radius_mm, 4),
            "improvement_pct": round(
                100.0 * (1.0 - final_u1 / init_u1), 2
            ) if init_u1 > 1e-12 else 0.0,
            "sa_iterations": iterations,
            "sa_accepted": accepted,
            "sa_best_improvements": improvements,
            "hill_moves": hill_moves,
        },
        "pairings": pairings,
        "steps": steps,
    }


def _explain_pairs(placement, mass_of, angles, disabled_set, radius_mm, locked_ids):
    """
    基于最终布局，贪心挑选"最近对径"的试管对并给出依据；未配上的为 solo。
    """
    # slot -> tube
    slot_tube = {si: tid for tid, si in placement.items()}
    cands = []
    tids = list(placement.keys())
    for a in range(len(tids)):
        for b in range(a + 1, len(tids)):
            ta, tb = tids[a], tids[b]
            sa, sb = placement[ta], placement[tb]
            opp = separation(angles[sa], angles[sb])
            err = abs(opp - 180.0)
            cands.append((err, ta, tb, sa, sb))
    cands.sort()
    used = set()
    result = []
    for err, ta, tb, sa, sb in cands:
        if ta in used or tb in used:
            continue
        used.add(ta)
        used.add(tb)
        ma, mb = mass_of[ta], mass_of[tb]
        # 对的合成力（g，单位半径）
        a1, a2 = math.radians(angles[sa]), math.radians(angles[sb])
        rx = ma * math.sin(a1) + mb * math.sin(a2)
        ry = -ma * math.cos(a1) - mb * math.cos(a2)
        pair_residual = math.hypot(rx, ry)
        # 两管对 U2 的贡献模
        qx = ma * math.sin(2 * a1) + mb * math.sin(2 * a2)
        qy = -ma * math.cos(2 * a1) - mb * math.cos(2 * a2)
        pair_u2 = math.hypot(qx, qy)
        diff = abs(ma - mb)
        reasons = [
            f"两槽夹角 {opp:.1f}°（与理想 180° 偏差 {err:.1f}°）",
            f"质量 {ma:g} g / {mb:g} g，质量差 {diff:g} g",
            f"该对自身残余一阶合力 {pair_residual * radius_mm:.2f} g·mm"
            + ("，质量不等是残余的主要来源" if diff > 1e-9 and err < 3 else
               "，角度偏差是残余的主要来源" if err >= 3 else ""),
            f"二阶贡献 {pair_u2 * radius_mm:.2f} g·mm"
            + ("（夹角近 180° 时二倍频分量同相叠加，需靠非对径布局抵消）"
               if err < 3 else ""),
        ]
        locked_note = []
        if ta in locked_ids:
            locked_note.append(ta)
        if tb in locked_ids:
            locked_note.append(tb)
        if locked_note:
            reasons.append("含锁定试管 " + "、".join(locked_note)
                           + "：增量重排中位置保持不变，由对侧试管适配")
        result.append({
            "type": "pair",
            "tubes": [ta, tb],
            "slots": [sa, sb],
            "angles": [round(angles[sa], 2), round(angles[sb], 2)],
            "masses": [ma, mb],
            "angular_separation_deg": round(opp, 2),
            "opposition_error_deg": round(err, 2),
            "mass_diff_g": round(diff, 6),
            "pair_residual_gmm": round(pair_residual * radius_mm, 4),
            "pair_u2_gmm": round(pair_u2 * radius_mm, 4),
            "reasons": reasons,
        })
    for tid in tids:
        if tid in used:
            continue
        si = placement[tid]
        result.append({
            "type": "solo",
            "tubes": [tid],
            "slots": [si],
            "angles": [round(angles[si], 2)],
            "masses": [mass_of[tid]],
            "reasons": [
                f"试管 {tid}（{mass_of[tid]:g} g）无对径伙伴"
                "（试管总数为奇数，或禁用槽破坏了对称槽位）",
                "其离心力无法由单只试管抵消，布局算法将其放在使整体合力"
                "增量最小的槽位，依靠其余试管的矢量和补偿",
            ] + (["该试管被锁定，位置不可调整"] if tid in locked_ids else []),
        })
    # 按槽位排序，便于阅读
    result.sort(key=lambda p: min(p["slots"]))
    return result
