# PiDataTriage — 基于开源 Pi Agent Runtime 的数据分析智能体

[![Python](https://img.shields.io/badge/Python-3.13-blue)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.60-red)](https://streamlit.io)
[![Pi Agent](https://img.shields.io/badge/Pi_Agent-0.82.1-green)](https://pi.dev)
[![DeepSeek](https://img.shields.io/badge/LLM-DeepSeek_v4‑Flash-purple)](https://deepseek.com)

> 让 AI Agent 自动完成数据分析——上传 CSV，Agent 自主完成数据画像、质量检测、统计建模与可视化，全程无需手动写代码。

## ✨ 一句话定位

基于开源 **Pi Agent Runtime** 构建的数据分析 triage 工具，通过 **跨语言 RPC 编排** + **自定义 Agent Skill**，将 LLM 从「聊天式分析」升级为「工具调用式专业分析」。

## 🎯 为什么这个项目值得关注

市面上大多数 LLM 应用只是简单的 API 调用链：用户提问 → 拼接 prompt → 调 LLM → 返回文本。这不是真正的 Agent。

**这个项目的不同之处**：

```
传统 LLM 应用：      用户 → API → LLM → 文本输出
PiDataTriage：       用户 → Agent Runtime → 工具调用 → LLM 推理 → 行动
                              ↕
                    自定义 Skill (python 工具)
```

Agent 会**自主决定**何时调用哪个工具、用什么参数、如何解读工具返回的结果——就像一个有判断力的数据分析师，而不仅是一个翻译 prompt 的传声筒。

## 🏗️ 架构

```
┌────────────────────────────────────────┐
│  Streamlit UI (Python)                 │
│  上传 CSV · 流式展示 · 过程可视化        │
└──────────────┬─────────────────────────┘
               │
┌──────────────▼─────────────────────────┐
│  Python 业务层                         │
│  - 会话管理 / 数据预处理 / 报告生成      │
└──────────────┬─────────────────────────┘
               │ picable (Pi RPC wrapper)
               │ JSONL over stdin/stdout
┌──────────────▼─────────────────────────┐
│  Pi Agent Runtime (TypeScript)         │
│  - Agent 编排 · 工具调度 · 上下文管理    │
└──────────────┬─────────────────────────┘
               │ 调用 Skill helper 脚本
┌──────────────▼─────────────────────────┐
│  自定义 Agent Skills (含 Python 脚本)   │
│  data-triage    → EDA & 数据画像       │
│  stat-deep-dive → PCA/聚类/时序分解    │
│  viz-craft      → 智能可视化(plotly)   │
└────────────────────────────────────────┘
```

## 🚀 Agent 能力展示

### 1. 自主工具调用（核心亮点）

Agent 不是被动接受指令，而是**自主分析任务需求，选择合适的工具**：

- 上传 CSV → Agent 发现数据 → 自动调用 `data-triage` Skill → 生成数据画像
- 发现高维数据 → Agent 判断需要降维 → 调用 `stat-deep-dive` Skill → PCA 分析
- 发现时间列 → Agent 识别时序模式 → 调用时间序列分解
- 分析完成 → Agent 选择合适图表 → 调用 `viz-craft` Skill → 生成 plotly 图表

### 2. 跨语言 Agent 编排

Pi Agent Runtime 是 TypeScript 项目，通过其 **RPC 模式**（JSONL over stdin/stdout）实现 Python↔TypeScript 双向通信：

```python
# Python 业务层通过 picable 驱动 TypeScript Agent
from picable import PiClient, PiClientOptions

client = PiClient(provider="deepseek", model="deepseek-v4-flash")
events = client.subscribe_events(maxsize=500)
client.prompt("请分析这个数据集的数据质量问题")

# Agent 自主决定调用哪些工具，Python 侧接收流式结果
for event in events:
    process(event)  # 实时展示 Agent 的思考与行动过程
```

### 3. Agent Skills 标准实现

每个 Skill 遵循 [Agent Skills 标准](https://agentskills.io/specification)，包含：

```
data-triage/
├── SKILL.md          # Agent 何时触发 + 做什么
└── scripts/helper.py # Python 工具脚本
```

Agent 启动时只加载 Skill 描述（渐进披露），任务匹配时用 `read` 工具加载完整指令，然后通过 `bash` 工具执行 Python 脚本。这正是「让 LLM 用工具而非猜答案」的标准范式。

## 🔧 工程挑战与解决

| 挑战 | 解决 |
|------|------|
| **跨语言 RPC 集成**：Pi 是 TS 项目，Python 如何驱动？ | 调研 Pi 的 RPC 模式（JSONL stdin/stdout），选用 picable 作为 Python wrapper，实现零 HTTP 开销的进程间通信 |
| **Windows 兼容性**：npm 全局安装的 `pi` 子进程无法被 Python subprocess 找到 | 定位到 `PiClientOptions.executable` 依赖 PATH 变量，通过 `dataclasses.replace` 注入 Windows 绝对路径 |
| **版本兼容性**：picable 0.1.0 不认识 Pi 0.82.1 新增的 `agent_settled` 事件类型 | 逆向 picable 的 AgentEvent 类型体系，新增 `AgentSettledEvent` 数据类并注册到事件解析链 |
| **多 Provider 适配**：从 OpenAI → DeepSeek 切换时 auth.json / runtime_config / PiClientOptions 三层配置需全链路对齐 | 逐层排查认证链路，统一为 DeepSeek provider + deepseek-v4-flash 模型 |

## 📦 快速开始

### 前置条件

- Python 3.11+ & Node.js 22+
- 一个 LLM API Key（支持 OpenAI / Anthropic / DeepSeek 等）
- Pi Agent Runtime 已安装：`npm install -g @earendil-works/pi-coding-agent`

### 安装

```bash
git clone <this-repo>
cd pi-data-triage
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install picable streamlit pandas plotly

# 应用 picable 兼容性补丁
python setup_patches.py
```

### 配置 LLM

编辑 `~/.pi/agent/auth.json`：

```json
{"deepseek":{"type":"api_key","key":"sk-你的key"}}
```

或设环境变量：`DEEPSEEK_API_KEY=sk-你的key`

### 运行

```bash
streamlit run app.py
# 打开 http://localhost:8501，上传 CSV，点击 Analyze with Pi
```

## 📁 项目结构

```
pi-data-triage/
├── app.py              # Streamlit 主界面
├── pi_session.py       # Pi Agent RPC 会话封装
├── profiler.py          # 本地 pandas 数据画像
├── prompts.py           # Agent prompt 构造
├── runtime_config.py    # Provider/Model 配置
├── skills/              # 自定义 Agent Skills（核心差异化）
│   ├── data-triage/
│   │   ├── SKILL.md
│   │   └── scripts/helper.py
│   ├── stat-deep-dive/
│   └── viz-craft/
├── patches/             # picable 兼容性补丁
├── sample_data/         # 示例数据集
└── .gitignore
```

## 🛠️ 技术栈

- **Agent Runtime**: Pi 0.82.1 (TypeScript, RPC 模式)
- **Python RPC**: picable 0.1.0
- **LLM**: DeepSeek v4-Flash (可切换 OpenAI/Anthropic)
- **UI**: Streamlit 1.60.0
- **数据分析**: pandas 3.0.5, plotly 6.9.0
- **Agent 协议**: JSONL over stdin/stdout, Agent Skills Standard

## 📝 License

MIT
