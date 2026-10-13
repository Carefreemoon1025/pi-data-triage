# 三个 Agent Skill 技术选型决策表

检索日期 2026-09-28。证据来源：PyPI JSON API（`https://pypi.org/pypi/<pkg>/json`，取 version / upload_time / license / requires_dist / wheel 文件名）+ GitHub REST API（stars / open_issues / pushed_at / license）。**本机无 pip/uv，全部版本与日期来自上述接口，未做安装验证。**

---

## 1. 决策表

| # | 问题 | 裁决 | 一句理由 | 关键证据 |
|---|---|---|---|---|
| 1 | data-triage 画像 | **自研（继续用 profiler.py）** | 现成 213 行的输出是结构化 dataclass（可直接进 JSON），三个候选库全以 HTML 报告为交付物，接进来要么套 HTML 要么二次解析 | profiler.py:24 `build_dataset_profile() -> DatasetProfile`（models.py 100 行 dataclass） |
| 2 | stat-deep-dive / PCA+KMeans | **裸 sklearn** | 5 个依赖、有 cp312 wheel、被采用度最高；`PCA`/`KMeans` 各约 3 行调用，Pipeline 在此规模纯属过度设计 | scikit-learn 1.9.1（2026-09-10，BSD-3-Clause，61.7k★，pushed 2026-09-24） |
| 3 | stat-deep-dive / 时序分解 | **statsmodels（`seasonal_decompose` + STL）** | 唯一「轻依赖 + 有 cp312 wheel + 同时提供 STL」的组合；statsforecast 多拉 5 个包，prophet 无 wheel | statsmodels 0.15.0（2026-08-27，BSD-3-Clause，cp312 wheel）；prophet 1.4.0 只有 sdist |
| 4 | stat-deep-dive / 自动建模 | **弃用全部（手写 60–100 行）** | auto-sklearn 已停更近 4 年、TPOT 是 LGPLv3、PyCaret 106 个依赖且 2024 年后无发版——三者任一都让「总成本」反超自研 | 见表下弃用清单 |
| 5 | viz-craft | **plotly.express 自写规则（约 80 行）** | px 已内建 dtype→mark 的自动推断（`px.scatter`/`px.line`/`px.histogram`），所谓「图表推荐」在 80 行规模没有可省的成本 | plotly 7.1.0（2026-09-15，MIT，18.8k★，pushed 2026-09-25）；纯 py wheel |
| 6 | 横向 / JSON+校验 | **保留 dataclass，不换 pydantic** | models.py 100 行已是 dataclass，`dataclasses.asdict()` + `json.dumps` 即得 JSON；换 pydantic 要改所有构造点，收益为零 | pydantic 2.13.5（2026-08-28，MIT）——健康，但无迁移理由 |
| 7 | 横向 / CLI | **标准库 `argparse`，不引 typer/click** | Skill 入口由 Agent 调用而非人类敲 CLI，argparse 零依赖足够；typer 额外拉 click+rich | typer 0.27.2（2026-08-28，MIT，4 deps） |

---

## 2. 被弃用候选（一行一因）

| 候选 | 版本 / 日期 | License | 弃用原因 |
|---|---|---|---|
| **ydata-profiling** | 4.18.4（PyPI 2026-04-22）· 上游 release 4.20.0（2026-09-11） | MIT | 21 个运行时依赖（含 numba、seaborn、wordcloud、imagehash），且**项目仓库已从 `ydataai/ydata-profiling` 迁到 `Data-Centric-AI-Community/fg-data-profiling`**，治理变动期；交付物是 HTML，结构化输出要额外解析 |
| **sweetviz** | 2.3.3（2026-04-11） | MIT | 只出 HTML 报告，无 JSON 通道；仓库 3.1k★、41 open issues，体量远小于 ydata；导入即绑定 matplotlib 出图，与「要 JSON 给 Agent 读」的目标不符 |
| **D-Tale** | 3.22.0（2026-04-01） | **LGPL-2.1** | **架构层面不匹配**：它是 Flask+Dash 的交互式 Web 应用，121 条依赖行；LGPL 对 MIT 简历项目引入许可摩擦；嵌入 Agent Skill 需拉起 Web 服务 |
| **prophet** | 1.4.0（2026-08-15） | MIT | **无任何 wheel（仅 sdist）**，且依赖 `cmdstanpy` → 运行时还需下载/编译 CmdStan 工具链；维护活跃（20.4k★）但安装成本最高 |
| **statsforecast** | 2.1.1（2026-07-16） | Apache-2.0 | 方向对（Nixtla 维护、有 cp312 wheel、pushed 2026-09-21），但在 statsmodels 之上再拉 coreforecast/fugue/utilsforecast/cloudpickle；其优势是「大规模批量预测」，本项目单序列分解用不上 |
| **umap-learn** | 0.5.12（2026-04-08） | BSD | 纯 py wheel 可装，但**需 numba 编译链**（依赖 numba），为 PCA 的替代引入重依赖；且不属于计划范围 |
| **hdbscan** | 0.8.44（2026-06-01） | BSD-3-Clause | 已提供 cp312 wheel（这点比预期好），但 KMeans 已够用；388 open issues、pushed 2026-06-12，非必要不引入 |
| **auto-sklearn** | 0.15.0（**2022-09-20**） | BSD-3 | 停更近 4 年，Python 3.12 无支持迹象，实质死项目 |
| **TPOT** | 1.1.0（2025-07-03） | **LGPL-3.0** | 许可为 LGPLv3，对 MIT 项目不友好；且 requires_python 上限 `<3.14`、依赖 deps 26 条 |
| **PyCaret** | 3.3.2（**2024-04-28**） | MIT（GitHub 显示 NOASSERTION） | 106 个依赖，最新发版停在 2024-04；安装重量与维护状态双输 |
| **altair** | 6.3.0（2026-09-15） | BSD-3-Clause | 无「自动选型」能力——它只对*已选定*的 mark 做编码映射；45 个依赖、需 `>=3.11`，换不来省事 |

---

## 3. requirements 清单建议

**通用基线（3 个 skill 共用）**

| 包 | 必须/可选 | 说明 |
|---|---|---|
| `pandas` | **必须** | profiler.py / loader.py 已依赖 |
| `scikit-learn>=1.9` | **必须**（stat-deep-dive） | PCA + KMeans，cp312 wheel |
| `statsmodels>=0.15` | **必须**（stat-deep-dive 时序） | `seasonal_decompose` / `STL`，cp312 wheel |
| `plotly>=6` | **必须**（viz-craft） | `plotly.express`，纯 py wheel |
| `numpy` | **必须** | 上述包的传递依赖 |
| `streamlit` | **必须**（现有 UI） | 已在项目中 |

**可选**

| 包 | 定位 |
|---|---|
| `ydata-profiling>=4.18` | **可选**：仅当需要「与工业界报告对照」时作为对照项，不进主路径 |
| `hdbscan>=0.8.44` | **可选**：仅在需要密度聚类替代 KMeans 时 |
| `statsforecast>=2.1` | **可选**：仅在扩展到多序列批量预测时 |

**明确不装**：prophet、cmdstanpy、PyCaret、TPOT、auto-sklearn、D-Tale、umap-learn、numba 系。

data-triage 本身**零新增依赖**（复用 profiler.py + models.py + export.py）。

---

## 4. 风险清单（最可能装不上/跑不通）

1. **statsmodels 0.15.0 的构建链**——虽提供 cp312 wheel，但 0.15.0 已从 setuptools 迁到 **meson-python**（`requires_dist` 里出现 `meson-python>=0.18.0`、`meson`、`ninja`）。只要 pip 能命中 wheel 就无事；一旦回退源码编译，需要 meson + ninja + C 编译器。**Python 3.12 + 官方 wheel 应可直接装，但需实测确认。**
2. **prophet 不可用**——只有 sdist，且 `cmdstanpy` 在首次使用时下载 CmdStan 工具链（联网 + 编译）。**若后续想用时序预测（而非仅分解），这是最大阻塞点**，需改用 statsmodels 的 SARIMAX 或 statsforecast。
3. **ydata-profiling 的依赖冲突面**——它 pin 了 `numpy<2.4`、`scipy<1.17`、`matplotlib<=3.10` 等较紧的上界，与已有环境并存时可能触发解析回退；同时其仓库正在迁移（`fg-data-profiling`），issue 追踪位置变动。**作为可选依赖时风险可控。**

**未能核实项**：本机无 pip/uv（沙箱内也不允许安装），故所有「能否在 Python 3.12 上装成功」均为**基于 wheel 文件名的推断**，未做真实安装验证；`seasonal_decompose` 与 `STL` 的具体 API 在本环境未运行验证。

---

**一句话检索结论**：三个 skill 全部走「自研 + 裸 sklearn/statsmodels/plotly.express」，不引入任何 profiling/自动建模/图表推荐库——因为候选库要么只出 HTML（ydata-profiling/sweetviz/D-Tale）、要么无 wheel（prophet）、要么 LGPL 或停更（TPOT/auto-sklearn/PyCaret），总成本均高于自写 60–100 行；且这是简历项目，自研逻辑的面试可讲性显著更高。
