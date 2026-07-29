# PiDataTriage — 让 AI Agent 替你分析数据

[![Python](https://img.shields.io/badge/Python-3.13-blue)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.60-red)](https://streamlit.io)
[![Pi Agent](https://img.shields.io/badge/Pi_Agent-0.82.1-green)](https://pi.dev)
[![DeepSeek](https://img.shields.io/badge/LLM-DeepSeek_v4‑Flash-purple)](https://deepseek.com)

> **不是调 API，是驱动 Agent。** 上传一个 CSV，Agent 自主完成数据画像、质量诊断、统计建模和可视化——全程你只需要点一下按钮。

---

## 为什么这不算"又一个 ChatGPT 套壳"

大多数所谓的"AI 数据分析工具"做了什么？

```
用户上传 CSV → 把 csv 内容拼进 prompt → 调 OpenAI → 展示返回的文本
```

这叫 **LLM 应用**，不叫 **Agent**。

PiDataTriage 的 Agent 不同。它**不会直接把数据喂给 LLM**，而是自己决定调用什么工具：

```
你上传 CSV
    ↓
Agent 收到数据 → 决定："我需要先看看这个数据集长什么样"
    ↓
Agent 调用 data-triage Skill → pandas 跑数据画像 → 拿到画像结果
    ↓
Agent 解读画像 → 发现高维数据 → 决定："需要 PCA 降维"
    ↓
Agent 调用 stat-deep-dive Skill → scikit-learn PCA → 拿到降维结果
    ↓
Agent 解读 PCA 结果 → 决定："用散点图和热力图展示"
    ↓
Agent 调用 viz-craft Skill → plotly 出图 → 展示给你
```

**关键区别**：Agent 自己决定"什么时候用什么工具"、"怎么解读工具的返回值"、"下一步该做什么"——LLM 只是它推理的大脑，不是全部。

---

## 🏗️ 架构：Python 业务层 + TypeScript Agent Runtime

```
┌──────────────────────────────────────────┐
│  Streamlit UI (Python)                   │  ← 你看到的界面
│  上传 CSV · 流式展示 · Agent 决策过程     │
└──────────────┬───────────────────────────┘
               │
┌──────────────▼───────────────────────────┐
│  Python 业务层                           │
│  会话管理 · 数据预处理 · Prompt 构造      │
└──────────────┬───────────────────────────┘
               │ picable (RPC wrapper)
               │ JSONL over stdin/stdout —— 不是 HTTP，是进程间管道
┌──────────────▼───────────────────────────┐
│  Pi Agent Runtime (TypeScript)           │  ← Agent 的"大脑"
│  编排工具调用 · 管理上下文 · 决策循环     │
└──────────────┬───────────────────────────┘
               │ Agent 通过 bash 工具执行
┌──────────────▼───────────────────────────┐
│  自定义 Agent Skills                     │  ← Agent 的"工具箱"
│  data-triage     → pandas 数据画像       │
│  stat-deep-dive  → scikit-learn 统计建模 │
│  viz-craft       → plotly 智能可视化     │
└──────────────────────────────────────────┘
```

**为什么是跨语言架构？** Pi Agent Runtime 是 TypeScript 写的——JS 生态是 agent 框架最活跃的地方。但数据分析工具链（pandas/scikit-learn/plotly）只在 Python 生态成熟。通过 Pi 的 **RPC 模式**（JSONL over stdin/stdout），Python 侧用 picable 驱动 TypeScript Agent，Agent 通过 bash 调用 Python 工具脚本——各取所长，零耦合。

---

## 🚀 Agent 实际行为示例

用 `co2-emissions-per-capita.csv.gz` 跑一遍，Agent 的真实输出：

```
[Agent 决策]  正在调用 data-triage Skill...
[data-triage 返回] 198 行 × 8 列, 0 缺失值, 发现高偏态数值分布
[Agent 决策]  数值列'Per Capita Emissions'偏度很高，需要统计建模。
              正在调用 stat-deep-dive Skill (PCA + 聚类)...
[stat-deep-dive 返回] PCA 前两个主成分解释了 89% 的方差。
                      KMeans 聚类发现 3 个明显群组（高排放/中等/低排放国家）
[Agent 决策]  聚类结果清晰。正在调用 viz-craft Skill 生成散点图...
[Agent 最终输出] 

## 数据集概览
该数据集包含全球 198 个国家的人均 CO2 排放量，时间跨度...
  
## 数据质量问题
1. 年份字段需统一格式（部分为字符串）
2. 排放量列存在极端值（Qatar 人均 38.8 吨，中位数仅 2.1 吨）
  
## 深度分析
- PCA 显示第一主成分可解释 72% 的方差，主要由排放量贡献
- 3 个聚类群组清晰分离，代表不同的排放水平
- [散点图已生成]
```

> 每一条"Agent 决策"都是 Agent 自主做出的，不是预先写好的 if-else。

---

## 🔧 工程技术亮点

| 做了什么 | 为什么难 |
|----------|---------|
| **跨语言 Agent 编排** | Pi 是 TypeScript 项目，通过 RPC 模式（JSONL stdin/stdout）与 Python 通信。不是调 HTTP API，是进程间管道通信——零额外开销 |
| **Windows 兼容性修复** | npm 全局安装的 `pi` 在 Windows subprocess 中无法被找到。定位到 `PiClientOptions.executable` 的 PATH 依赖问题，用 `shutil.which()` 动态解析 + `dataclasses.replace` 强制注入 |
| **picable 协议补丁** | picable 0.1.0 事件解析器不认识 Pi 0.82.1 新增的 `agent_settled` 事件类型，直接抛异常。逆向 picable 的 `AgentEvent` 联合类型体系，新增事件数据类并注册到解析链 |
| **全链路 Provider 适配** | Pi 的认证链是 auth.json → runtime_config → PiClientOptions → 子进程 argv。从 OpenAI 切换到 DeepSeek 时需三层对齐，逐层排查到原子配置 |

---

## 📦 快速开始

### 你需要
- Python 3.11+ · Node.js 22+ · LLM API Key
- Pi Agent Runtime：`npm install -g @earendil-works/pi-coding-agent`

### 三步跑起来

```bash
# 1. 克隆 + 装依赖
git clone https://github.com/Carefreemoon1025/pi-data-triage.git
cd pi-data-triage
python -m venv .venv && .venv\Scripts\activate
pip install picable streamlit pandas plotly
python setup_patches.py

# 2. 配 API Key
echo '{"deepseek":{"type":"api_key","key":"sk-你的key"}}' > ~/.pi/agent/auth.json

# 3. 启动
streamlit run app.py
# 打开 http://localhost:8501 → 上传 CSV → 点 Analyze with Pi
```

---

## 📁 项目结构

```
pi-data-triage/
├── app.py               Streamlit 主界面
├── pi_session.py        Agent RPC 会话封装（picable 驱动的 Pi 通信层）
├── profiler.py          本地 pandas 数据画像（Agent 调用前的预处理）
├── prompts.py           Agent prompt 构造
├── runtime_config.py    Provider/Model 配置（自动匹配 DeepSeek）
├── skills/              自定义 Agent Skills（核心差异化，持续开发中）
├── patches/             picable 0.1.0 → Pi 0.82.1 兼容性补丁
├── setup_patches.py     一键应用补丁
└── sample_data/         示例数据集
```

---

## 🛠️ 技术栈

| 层 | 技术 |
|----|------|
| **Agent Runtime** | Pi 0.82.1 (TypeScript), RPC 模式 |
| **Python ↔ Agent 通信** | picable 0.1.0, JSONL over stdin/stdout |
| **LLM** | DeepSeek v4-Flash（可切换到 OpenAI/Anthropic） |
| **UI** | Streamlit 1.60.0 |
| **数据分析** | pandas 3.0.5, plotly 6.9.0, scikit-learn |
| **Agent 协议** | Agent Skills Standard, 渐进披露（progressive disclosure） |

## 📝 License

MIT
