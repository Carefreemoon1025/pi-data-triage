# pi-data-triage · 3 个 Agent Skill 实施 Spec

> 2026-09-28。目标：把 README 承诺的 `data-triage` / `stat-deep-dive` / `viz-craft` 真正实现，
> 使「实现 3 个 Agent Skill」这句话在简历上成立。
> 本文件是实施前的待批 spec。除标注「推测」外，全部结论来自实测。

---

## 0. 实测基线（证据）

### 0.1 Pi runtime（关键 —— 决定 skill 放哪）
- `pi` **已安装**：`/home/myue/.nvm/versions/node/v24.21.0/bin/pi`，版本 **0.87.1**
- 非交互可用：`pi -p "<prompt>"`，实测 exit 0、秒级返回（**不触发 opc 那种长挂**，因为走 Pi 自己的 provider）
- `~/.pi/agent/settings.json`：`defaultProvider=opencode-go`、`defaultModel=deepseek-v4.1-flash`
- `~/.pi/agent/auth.json` 有 `opencode-go` 凭据
- 相关 flag：`--print/-p`、**`--skill <path>`（可重复）**、`--no-skills/-ns`、`--provider`、`--model`

**skill 发现路径实测结果**（建探针 SKILL.md 后跑真实 `pi -p` 列表）：

| 放置方式 | 是否被发现 |
|---|---|
| `~/.pi/agent/skills/` | ✅ 是 |
| `settings.json` 的 `skills: [<path>]` | ✅ 是 |
| `<cwd>/.pi/skills/` | ❌ 否 |
| git 仓库内 `.agents/skills/` | ❌ 否 |
| `pi --skill <path>`（据 flag 存在推断） | 推测 ✅，未单独实测 |

> 来源：`dist/core/skills.js` 读出的路径表给了 4 条，**其中 2 条运行时证伪** —— 这是本次最有价值的纠正。

### 0.2 环境
- `.venv`（uv 建）：**Python 3.12.14**，pandas 3.0.6、numpy 2.5.3、scikit-learn 1.9.1、statsmodels 0.15.0、plotly 7.1.0、picable 0.1.0
- **全部 cp312 manylinux wheel，零源码编译**；总 386 MB；冷装 14 秒
- ⚠️ `.venv` 里**没有 pip**（`No module named pip`）→ 验收期间不能临时装包
- ⚠️ **streamlit 未装** → 验收链路必须绕开 Streamlit

### 0.3 现有代码（1623 行）
- `profiler.build_dataset_profile(df) -> DatasetProfile` 是**唯一 public 函数**；`models.py` 全 frozen dataclass，无 `asdict`
- `loader.load_csv(uploaded_file, *, options)`；按 gz 魔数解压；fingerprint = **解压后**字节的 sha256
- ⚠️ **`load_csv` 不接受路径字符串**（`loader.py:121` 抛 `Unsupported upload type`）
- 真样本 `sample_data/co2-emissions-per-capita.csv.gz`：**26,509 行 × 4 列**，列名含 Unicode `₂`，`Code` 空值 12.46%
  - 实测跑通：`rows=26509 columns=4 dup=0`，`suspicious_columns` 恰好 1 列（CO₂，`extreme numeric range relative to the median`）
  - ⚠️ 26,509 > `CsvLoadOptions.max_rows` 默认 **5000** → 不显式放开就会截断
- `prompts.py` 全文**无 `tool`/`skill`/`bash` 任一字样**（grep 命中 0）
- README 的 `## Agent Skills` 在 **91–107** 行；`README.md:132` 自认 `skills/` 尚未入库（实测确实不存在）
- tool 事件**已在 `patches/events.py:168-170` 注册**（`tool_execution_start/update/end`），但 `pi_session.py:115-143` **不消费**，静默丢弃

### 0.4 仓库状态（与本次无关，但影响提交）
- `git status` 显示 14 个文件 `M`：**CRLF/LF 差异**（增删各 1830 行），非内容改动
- 文件 mtime = **2026-09-07**（克隆当天），无 `.gitattributes`、未设 `core.autocrlf`
- → 提交 `skills/` 时必须避免把这 14 个文件一起扫进去

---

## 1. 待裁决的四个决策点

### D1 · skill 放哪（决定 README 是否保持诚实）
| 方案 | 做法 | 优点 | 代价 |
|---|---|---|---|
| **D1-a（推荐）** | 文件放仓库内 `skills/`，跑 Pi 时带 `--skill skills/` | 仓库自包含、README 布局承诺原样成立、零全局配置污染 | 每次启动要带 flag |
| D1-b | 文件放 `skills/`，`settings.json` 写 `skills: ["<repo>/skills"]` | 一次配置永久生效 | 改用户全局配置；新克隆要补一行 |
| D1-c | 文件放 `~/.pi/agent/skills/` | 零配置 | **skill 不在仓库里** → README 与简历都站不住，否 |

### D2 · 要不要补「工具事件通路」
- (a) 补：4 文件约 40–55 行（新增独立回调 `on_tool_event`，不动 `on_update` 签名）。**前置条件已解除** —— 真实 Pi 会话跑得通，可抓事件顺序验收。额外收益：**「工具调用可视化」这句简历话同时变真**（防复发清单第 4 条）
- (b) 不补：0 行，skill 照跑，但简历只能写「实现了 3 个 Skill」，不能写可视化
- ➡️ **推荐 (a)**：先决条件（真实会话）已具备，且它一次性消掉两句假话

### D3 · skill 脚本怎么读输入文件
- (i) 脚本各自 `open(path,'rb').read()` 再交给 `load_csv` —— **0 改动**，3 处各 3 行重复
- (ii) 在 `loader.py` 加 ~4 行支持 `str`/`Path` —— 动公共 API，`upload.name` 会变 `None`
- ➡️ **推荐 (i)**

### D4 · 简历同步范围与时机
落地后必须同时改（见 §4），且**必须处理 3 个会把真话改回假话的修正脚本**。

---

## 2. 三个 Skill 的契约（统一约定）

**CLI**：`python3 skills/<name>/scripts/<x>.py --input <path.csv[.gz]> [--output <path.json>]`
**stdout**：**只输出一个 JSON 对象**（人读文本走 stderr）
**错误信封**：`{"ok": false, "error": {"code": "<machine_code>", "message": "<人读>", "hint": "<下一步>"}}`
**exit code**：`0` 成功 · `2` 用法错 · `3` 数据加载失败 · `4` 列/参数不匹配 · `5` 依赖缺失 · `1` 其他
**字段名**：一律复用 `DatasetProfile`/`ColumnProfile` 既有拼写，不新增同义字段
**三条硬约束**：不 import `app.py`、不 import `streamlit`、不 import `pi_session`（后者会把 picable 拖进依赖链）

| skill | argv 要点 | 输出要点 | 复用 | 新写 |
|---|---|---|---|---|
| `data-triage` | `--input`、`--separator/--encoding/--no-header/--max-rows` | `dataset{name,size_bytes,fingerprint}` + `load{loaded_rows,truncated,notices}` + `profile{...8 字段}` | `loader.load_csv` + `profiler.build_dataset_profile` | CLI 胶水 60–80 行 + dataclass→dict |
| `stat-deep-dive` | `--method {pca,kmeans,decompose}`、`--columns`、`--n-components/--n-clusters/--period` | `input{rows,columns_used,dropped}` + `result{...}` + `profile_excerpt{numeric_summary}` | 裸 `sklearn` / `statsmodels` | 计算主体 + CLI 120–150 行 |
| `viz-craft` | `--intent auto\|trend\|distribution\|correlation\|composition`、`--x/--y` | `chart{kind,x,y,reason,encoding}` + `figure{plotly JSON}` + `warnings` | `plotly.express` + profiler 的 dtype 判据 | 选型 40 行 + figure 60 行 |

**SKILL.md 硬规则**（踩了会被拒载）：
- `---` 必须在文件**最开头**
- `name`：≤64 字符、仅 `a-z0-9-`、目录名须与之一致
- `description`：1–1024 字符、**缺失或全空白 → 该 skill 直接不加载**；须同时说「做什么」+「何时用」

---

## 3. 验收（3 条断言，全部可脚本化）

```bash
cd /home/myue/DSH/resume/个人简历/pi-data-triage
.venv/bin/python skills/data-triage/scripts/profile.py  --input sample_data/co2-emissions-per-capita.csv.gz --max-rows 0
.venv/bin/python skills/stat-deep-dive/scripts/stat.py   --input sample_data/co2-emissions-per-capita.csv.gz --method pca --columns "Year,CO₂ emissions per capita"
.venv/bin/python skills/viz-craft/scripts/viz.py         --input sample_data/co2-emissions-per-capita.csv.gz --x Year --y "CO₂ emissions per capita" --intent trend
```

1. exit 0 且 stdout 可 `json.loads`，`obj["ok"] is True`
2. `profile.rows == 26509 and profile.columns == 4 and load.truncated is False`
3. 错误路径：`--input /nonexistent.csv` → exit 2 + `{"ok":false,...}`

**第 4 条（仅 D1 生效后）**：`pi -p "列出可用 skill"` 能列出 3 个 skill 名。

---

## 4. 简历同步范围（子代理 E 实测：**15 个落点，4 类**）

比 09-19 记录多 2 类。**只改一处会让假话复活**。

1. **母本**：`AI-work-master-resume/master-resume.md:44,46,48,87`；`职业规划/00:85,156-157,255,268`、`01:46-47`、`03:158`、`04:83`、`05:212-230`
2. **生成脚本**：`Z_Cache-resume/build/generate_resumes.js:70,123`；`求职相关/output/render_*.py` 4 个；`.resume_work/build_fullstack_resume.py:115,121`
3. **产物**：13 份 docx（2026-09-09 同批，实测解包含「工具调用链路」「实时呈现」「封装为标准化 Skill」）+ 约 18 份 PDF（仅凭时间戳判陈旧，本机无 pdftotext）
4. **面试文件（最危险，背的答案是假的）**：`Z_Cache-resume/项目事实清单.md:14-15`「只有设计，没有实现」、`面试学习清单.md:18,19,104`、`面试学习台.html:153,157,521`、`简历修改手册.md:175`；`resume/现有项目事实核查-2026-09-17.md:35-39`、`现有项目一周升级计划-2026-09-17.md`

**三个反向风险（会把真话改回假话，必须同期处理）**：
`resume/scripts/fix_resume_claims.py`、`fix_skill_claims_round2.py`、`fix_skill_claims_round4.py` —— 规则是「禁写实现」。

**沙箱外、必须用户手工做的两件事**：
- `D:\Z_Cache\resume\build\`（宿主机权威副本）实测**仍是 09-09 旧版含 5 处假话**，md5 与工作区副本不同；`D:\AI work\...\master-resume.md:46` 仍是「设计**并实现了**三个自定义 Agent Skills」
- GitHub 公开仓库 `Carefreemoon1025/pi-data-triage` 的 README 仍写「规划中，尚未入库」→ **skill 落地后必须 push**

---

## 5. 风险

1. **`picable` 是 Alpha 单人项目**（唯一版本 0.1.0 / 2026-05-06 / 0 stars / 最后提交 2026-05-13）。建议 pin `picable==0.1.0`。README 说它「不认识 Pi 0.82.1 的 agent_settled」是**归因错误** —— 该事件 0.80.4 就有了
2. **tool 事件与 `agent_end` 的到达顺序未知**：`pi_session.py:131-138` 处理完 `agent_end` 即 `break`，若 Pi 在之后才发 tool 事件就会丢。补通路时必须先抓一次真实会话的 JSONL 确认
3. `profiler.py` 用了 pandas 3.0 特性（`dropna=`、`format="mixed"`）→ **不能降 pandas 版本**
4. `statsmodels` 0.15.0 已迁 meson-python 构建：命中 wheel 无事，回退源码编译需要完整 C 工具链

---

## 6. 工时

| 项 | 估时 |
|---|---|
| 3 个 skill（脚本 + SKILL.md） | 3–5 h |
| D2 若选 (a)：通路 + UI 渲染 | 4–8 h |
| 验收脚本化 | 0.5 h |
| 简历/README 四类同步 | 2–3 h（含宿主机回写等待） |
