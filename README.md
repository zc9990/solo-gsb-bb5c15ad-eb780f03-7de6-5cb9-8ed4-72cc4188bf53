# 离心机转子配平规划器（Centrifuge Rotor Balance Planner）

录入离心机转子的**槽位角度、试管质量与禁用槽位**，在质量与角度约束下搜索近似最优的
**对称布局**，计算**合力矩（一阶不平衡量 U₁）与二阶不平衡量 U₂**，对**锁定试管**执行
增量重排，逐步解释每一对配对依据，并支持**方案回放**与**导出 JSON**。

技术栈：Python 3.12 · FastAPI · SQLite · 原生 HTML/CSS/JS（无前端构建）· Docker Compose。

---

## 一键启动

```bash
docker compose up --build
```

启动后打开浏览器：

- 应用页面： **http://localhost:8000**
- 接口文档（Swagger）： **http://localhost:8000/docs**
- 健康检查： **http://localhost:8000/api/health**

停止：`Ctrl+C`；后台运行：`docker compose up --build -d`；查看日志：`docker compose logs -f`。

### 端口

默认映射 **宿主机 8000 → 容器 8000**。若宿主机 8000 被占用，任选一种方式修改：

```bash
# 方式一：环境变量（推荐）
HOST_PORT=9000 docker compose up --build      # → http://localhost:9000

# 方式二：直接编辑 docker-compose.yml 中 "${HOST_PORT:-8000}:8000" 左侧端口
```

### 配置项

| 配置 | 位置 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `HOST_PORT` | compose 环境变量 | `8000` | 宿主机暴露端口 |
| `BALANCER_DB` | 容器环境变量 | `/data/balancer.db` | SQLite 数据库路径 |
| `UVICORN_LOG_LEVEL` | 容器环境变量 | `info` | uvicorn 日志级别 |
| 数据持久化 | compose 命名卷 `balancer-data` → `/data` | — | 删除容器后方案仍保留 |

不想用 Docker 时的本地开发方式：

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
BALANCER_DB=./data/balancer.db uvicorn app.main:app --reload --port 8000
```

---

## 使用说明

1. **转子配置**：设置槽位数、转子半径、转速（可选，用于换算离心合力）。
   角度默认均布（`360/n`，0° 在正上方、顺时针递增），也可切换为自定义角度。
2. **禁用槽位**：直接在转子图上**点击空槽**切换禁用（禁用槽画叉），或点击下方标签恢复。
3. **试管清单**：填写编号、质量（g）。勾选“锁定”后填写槽位号，该试管在优化中**位置固定**，
   其余试管围绕它增量重排。
4. **优化参数**：一阶/二阶权重 `w1/w2`（默认 1 / 0.15）、退火迭代次数（留空自动）、随机种子。
5. 点击 **▶ 计算配平方案**；满意后 **💾 保存方案** 入库，或 **⬇ 导出 JSON**。
6. **方案回放**：在时间轴上单步/自动播放“锁定 → 贪心构造 → 退火 → 爬山 → 最终”全过程，
   转子图与 U₁/U₂ 合力箭头随每一步变化。
7. **配对依据**：结果区列出每一对（或无配对单管）的夹角、对径误差、质量差、残余合力及
   二阶贡献，并说明锁定试管如何由对侧适配。
8. 页面打开时已载入一个示例（12 槽、禁用 11 号槽、含 1 支锁定管、5000 rpm）。

---

## 物理模型

约定 0° 在正上方、顺时针为正，单位半径下：

- **一阶不平衡量**：`U₁ = r · |Σ mᵢ·e^{jθᵢ}|`（g·mm），旋转时产生与转速平方成正比的
  离心合力 `F = ω²·U₁`（U₁ 由 g·mm 换算为 kg·m）与合力矩 `F·r`；这是主导安全指标。
- **二阶不平衡量**：`U₂ = r · |Σ mᵢ·e^{j·2θᵢ}|`（g·mm），反映 2 倍频交变载荷。
  完美对径两管 U₁=0 但 U₂ 最大；等距三点配平 U₁=U₂=0。
- **归一化残差**：`e₁ = |U₁|/(M·r)`，据此评级：
  A 优秀 (<1%) · B 良好 (<3%) · C 可用 (<8%) · D 较差 (<15%) · E 不可接受。

## 搜索算法（近似最优）

1. **贪心构造**：试管按质量降序成对处理，每一对枚举所有剩余空槽对与两种朝向，
   选使当前合力目标最小者；奇数支的单管枚举空槽取最优。锁定管先放置且不参与移动。
2. **模拟退火**：仅对未锁定试管执行 swap / move（含随机候选槽的引导移动），
   最小化 `J = w₁·|U₁| + w₂·|U₂|`，固定种子可复现。
3. **邻域爬山**：在退火最优解上做完整 move + swap 邻域扫描收尾。
4. 每一步均写入 `steps`，驱动前端回放与解释。

---

## HTTP API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/balance` | 计算配平（不落库），返回完整结果 |
| `POST` | `/api/plans` | 计算并保存方案，返回 `id` 与结果 |
| `GET` | `/api/plans` | 历史方案列表 |
| `GET` | `/api/plans/{id}` | 方案详情（含请求、结果、逐步回放数据） |
| `DELETE` | `/api/plans/{id}` | 删除方案 |
| `GET` | `/api/plans/{id}/export` | 以附件方式下载方案 JSON |
| `GET` | `/api/health` | 健康检查 |

`POST /api/balance` 请求体示例：

```json
{
  "n_slots": 12,
  "disabled": [11],
  "radius_mm": 100,
  "rpm": 5000,
  "w1": 1.0,
  "w2": 0.15,
  "iterations": null,
  "seed": 42,
  "tubes": [
    {"id": "L1", "mass": 12.0, "locked": true,  "locked_slot": 0},
    {"id": "X",  "mass": 11.5, "locked": false},
    {"id": "Y",  "mass": 8.0,  "locked": false}
  ]
}
```

`angles` 省略时按 `360/n` 均布；自定义时必须提供恰好 `n_slots` 个角度。
校验失败（试管多于可用槽、锁冲突、锁定在禁用槽、质量非正等）返回 HTTP 422 与中文原因。

---

## 目录结构

```
.
├── app/
│   ├── main.py          # FastAPI 路由 / 请求模型 / 静态托管
│   ├── balancer.py      # 配平核心算法（几何物理、贪心、退火、爬山、配对解释）
│   ├── database.py      # SQLite 持久化（plans / rotors 表）
│   └── static/
│       ├── index.html   # 单页界面
│       ├── styles.css
│       └── app.js       # 转子 SVG、指标、回放、历史、导出
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

数据均为计算演示用途；实际离心作业请同时遵守转子厂商的配重与转速规范。
