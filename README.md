# pi-data-triage

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://python.org)
[![Pi Agent](https://img.shields.io/badge/pi_agent-0.82.1-green.svg)](https://pi.dev)
[![Streamlit](https://img.shields.io/badge/streamlit-1.60-red.svg)](https://streamlit.io)
[![License MIT](https://img.shields.io/badge/license-MIT-lightgrey.svg)](LICENSE)

数据分析 triage agent——基于 Pi Agent Runtime，上传 CSV 后 Agent 自主调用工具完成数据画像、统计分析和可视化。

## 和典型 LLM 应用的区别

常见的做法是把 CSV 内容拼进 prompt 调 API。这里 Agent 收到数据后，自己判断该调用哪个 Skill（Python 工具脚本），拿到工具返回值后再决定下一步。LLM 负责推理，工具负责计算——各干各的。

实际跑一遍 co2-emissions-per-capita.csv.gz 的数据流

```
数据画像  →  Agent 判断需要统计建模  →  调用 PCA + KMeans
         →  Agent 判断结果需要可视化  →  调用 plotly 出图
         →  Agent 整合输出报告
```

每一步决策是 Agent 自己做的，没有预置流程。

## 架构

```
Streamlit (Python UI)
    ↓
Python 业务层 (会话管理, 数据预处理)
    ↓ picable · JSONL over stdin/stdout
Pi Agent Runtime (TypeScript · 工具编排 · 上下文管理)
    ↓ bash 执行 Skill 脚本
Agent Skills (Python 工具脚本 · data-triage / stat-deep-dive / viz-craft)
    ↓
LLM (DeepSeek v4-Flash · 可切换)
```

Pi 是 TypeScript 写的 agent runtime。JS 生态的 agent 框架迭代快——Skills 标准、RPC 模式、渐进披露都是那边先出来的。数据分析工具链（pandas scikit-learn plotly）在 Python 这边成熟。所以没强行全用 Python，而是通过 Pi 的 RPC 模式（JSONL over stdin stdout）做跨语言编排：Python 侧用 picable 驱动 Pi 子进程，Agent 再通过 bash 执行 Python Skill 脚本��

## 快速开始

前置条件

- Python 3.11+
- Node.js 22+
- LLM API Key（DeepSeek / OpenAI / Anthropic 都行）
- Pi Agent Runtime 已安装

```bash
npm install -g @earendil-works/pi-coding-agent
```

安装

```bash
git clone https://github.com/Carefreemoon1025/pi-data-triage.git
cd pi-data-triage
python -m venv .venv
.venv\Scripts\activate
pip install picable streamlit pandas plotly
python setup_patches.py
```

配置 LLM

```bash
echo '{"deepseek":{"type":"api_key","key":"sk-你的key"}}' > ~/.pi/agent/auth.json
```

如果用的不是 DeepSeek，改 `runtime_config.py` 里的 `DEFAULT_PROVIDER` 和 `DEFAULT_MODEL`。

启动

```bash
streamlit run app.py
```

打开 http://localhost:8501，上传 CSV，点 Analyze with Pi。

## 使用

1. 上传 CSV 或 .csv.gz 文件
2. 界面会展示本地 pandas 数据画像（行数、列数、缺失值、可疑列）
3. 点 Analyze with Pi，Agent 开始调用工具分析
4. 结果流式返回，包含数据概述、质量问题、清理建议
5. 可以追问，比如"哪三列应该先清洗"
6. 支持导出 Markdown 和 HTML 会话记录

sample_data 目录里有一个 co2-emissions-per-capita.csv.gz 可以试。

## Agent Skills

Skills 是 Agent 的工具箱。每个 Skill 遵循 Agent Skills 标准

```
skill-name/
├── SKILL.md          frontmatter (name + description) + 使用说明
└── scripts/helper.py Python 工具脚本
```

Agent 启动时只加载 Skill 描述（渐进披露），任务匹配时用 read 工具加载完整指令，然后通过 bash 执行 Python 脚本。

计划中的 Skills（开发中）

- data-triage EDA 和 pandas 数据画像
- stat-deep-dive PCA、聚类、时间序列分解
- viz-craft 根据数据类型自动选择 plotly 图表

## 工程技术

三个踩过的坑

**Windows 上 Pi 子进程找不到。** picable 的默认 executable 只写了 "pi"，依赖系统 PATH。Windows 上 npm 全局路径不在子进程 PATH 里。用 `shutil.which()` 动态解析 pi.cmd 实际路径，`dataclasses.replace` 强制注入 PiClientOptions——不管 Streamlit 模块缓存怎么处理，每次构建 options 都重新找。

**picable 0.1.0 不认识 Pi 0.82.1 的 agent_settled 事件。** picable 把事件类型写死在 if-else 链里，不认识的直接抛异常。补了 AgentSettledEvent 数据类，注册进 AgentEvent union 类型，塞进解析链。补丁在 patches/events.py。

**跨 Provider 配置链路。** Pi 的认证是 auth.json → runtime_config → PiClientOptions → 子进程 argv 四层往下传。切 Provider 时漏一层就报错，逐层排查对齐的。

## 项目结构

```
pi-data-triage/
├── app.py               Streamlit 主界面
├── pi_session.py        Pi RPC 会话封装
├── profiler.py          本地 pandas 数据画像
├── prompts.py           prompt 构造
├── runtime_config.py    Provider / Model 配置
├── skills/              Agent Skills（开发中）
├── patches/             picable 兼容性补丁
├── setup_patches.py     一键应用补丁
└── sample_data/         示例 CSV
```

## 技术栈

| 层 | 技术 |
|----|------|
| Agent Runtime | Pi 0.82.1 (TypeScript, RPC 模式) |
| Python ↔ Agent 通信 | picable 0.1.0, JSONL over stdin/stdout |
| LLM | DeepSeek v4-Flash（可切换） |
| UI | Streamlit 1.60 |
| 数据分析 | pandas 3.0.5, plotly 6.9.0 |

## License

MIT
