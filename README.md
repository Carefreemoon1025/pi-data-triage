# pi-data-triage

上传一个 CSV，Agent 自己跑完数据画像、质量诊断和可视化。全程我只点了一下按钮。

我和这个 Agent 的分工是这样的

我写了 Python 那层——Streamlit 界面、pandas 数据预处理、picable 对 Pi 的 RPC 封装。Agent 负责决策层：收到数据后自己判断该调哪个 Skill，用什么参数，怎么解读返回结果，下一步做什么。

市面上大多数"AI 分析工具"只是把 CSV 文本拼进 prompt 然后调个 API。PiDataTriage 不是。Agent 不会直接把原始数据丢给 LLM——它必须调用我写的 Python 工具脚本来处理数据，LLM 只是它推理的大脑。

一个具体的例子

用 co2-emissions-per-capita.csv.gz 跑一遍，Agent 的决策链大概长这样

```
Agent 收到数据画像  "数据 198 行 8 列，0 缺失值，但数值分布高度偏态"
Agent 决定          调用 data-triage Skill → 拿到完整画像
Agent 解读画像       "Per Capita Emissions 这个字段偏度很高，需要统计建模"
Agent 决定          调用 stat-deep-dive Skill → PCA + KMeans 聚类
Agent 解读结果       "PCA 前两个主成分解释 89% 方差，KMeans 分出 3 个排放水平群组"
Agent 决定          调用 viz-craft Skill → 生成散点图
Agent 输出报告       数据集概览 + 质量问题排名 + 深度分析 + 图表
```

每一步"决定"都是 Agent 自己做的，不是预先写好的 if-else。

为什么是 Python 加 TypeScript 的奇怪组合

Pi Agent Runtime 是 TypeScript 写的。JS 生态的 agent 框架迭代速度比 Python 快得多——agent skills 标准、RPC 模式、渐进披露机制这些都是 JS 社区先搞出来的。但数据分析的工具链 pandas scikit-learn plotly 只在 Python 这边成熟。

所以我没有强行全用 Python（LangChain 那一套），也没有为了用 Pi 去学 TypeScript。Pi 有一个 RPC 模式——JSONL 走 stdin stdout，不是 HTTP。我在 Python 侧用 picable 这个 wrapper 去驱动 Pi 子进程，Agent 再通过 bash 工具执行我写的 Python Skill 脚本。各取所长，中间就一根管道。

踩过的坑

1. Windows 上 Pi 子进程找不到。picable 的默认 executable 只写了 "pi" 两个字，依赖系统 PATH。Windows 上 npm 全局安装的路径不在子进程 PATH 里。最后用 shutil.which() 动态解析 pi.cmd 的实际路径，再用 dataclasses.replace 强制注入 PiClientOptions——这样不管 Streamlit 模块缓存怎么搞，每次构建 options 都会重新找一遍 pi。

2. picable 0.1.0 不认识 Pi 0.82.1 新增的 agent_settled 事件。Agent 跑着跑着就崩，报 unsupported event type。翻 picable 源码发现它把事件类型写死在一个 if-else 链里，遇到不认识的直接抛异常。给它补了 AgentSettledEvent 类，注册进 AgentEvent union 类型，塞进事件解析链——就活了。

3. DeepSeek 的认证链路。Pi 的 provider 配置不是一处搞定，是 auth.json → runtime_config → PiClientOptions → 子进程 argv 四层往下传。一开始配成 OpenAI，切 DeepSeek 的时候三层改了两层漏了一层，排查了半天。

跑起来

```bash
git clone https://github.com/Carefreemoon1025/pi-data-triage.git
cd pi-data-triage
python -m venv .venv && .venv\Scripts\activate
pip install picable streamlit pandas plotly
python setup_patches.py

echo '{"deepseek":{"type":"api_key","key":"sk-你的key"}}' > ~/.pi/agent/auth.json

streamlit run app.py
```

然后打开 http://localhost:8501，上传 CSV��点 Analyze with Pi。

你需要 Python 3.11 以上、Node.js 22 以上、一个 LLM API Key。Pi Agent Runtime 要先装上

```bash
npm install -g @earendil-works/pi-coding-agent
```

项目里有什么

```
pi-data-triage/
├── app.py               Streamlit 主界面，管上传和展示
├── pi_session.py        Pi RPC 会话封装，picable 这边的事
├── profiler.py          本地 pandas 数据画像
├── prompts.py           Agent prompt 构造
├── runtime_config.py    Provider 和 Model 配置
├── skills/              Agent Skills 还在开发中
├── patches/             picable 兼容性补丁
├── setup_patches.py     一键应用补丁
└── sample_data/         示例 CSV
```

用了什么

Agent Runtime Pi 0.82.1 的 RPC 模式。Python 和 Agent 之间走 picable 0.1.0（JSONL over stdin stdout）。LLM 是 DeepSeek v4 Flash，可以换 OpenAI 或 Anthropic。界面用 Streamlit 1.60。数据这边 pandas 3.0.5，图表 plotly 6.9.0。

MIT
