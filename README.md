# 价格行为分析 Codex / Claude Code Skill

这个仓库是一个 AI 编程助手 skill（同时支持 Codex 和 Claude Code），用于把用户提供的 K 线截图或 OHLC 图表数据，制作成带通道、区间、箭头、关键价位、形态标签和交易计划的价格行为标注分析图。

## 能做什么

- 基于 Al Brooks / 阿布价格行为学读取 K 线背景、市场周期、通道、交易区间、突破、失败突破和反转尝试。
- 在原始图表上叠加确定性标注，不重画 K 线，不编造价格。
- 同一张图里同时交付历史复盘层和当前交易计划层。
- 输出多头触发、空头触发、失效位置、目标区域、不交易条件和风险提醒。

## 目录结构

```text
.
├── SKILL.md                         # Skill 入口（Codex + Claude Code 共用）
├── agents/openai.yaml               # Codex 展示与默认提示配置（Claude Code 无需）
├── references/
│   ├── annotation-spec.md           # 标注 JSON 规格
│   ├── price-action-framework.md    # 价格行为分析框架
│   └── quality-gate.md              # 交付前质量检查
├── scripts/render_annotations.py    # 确定性标注渲染脚本
└── outputs/                         # 本地生成产物，不提交到仓库
```

## 连接到 Codex

把仓库目录链接到 Codex 用户 skill 目录：

```powershell
New-Item -ItemType SymbolicLink `
  -Path "$env:USERPROFILE\.codex\skills\price-action-analysis" `
  -Target "D:\Code\Price-action-analysis"
```

如果当前 Windows 环境不允许创建符号链接，可以改用目录联接：

```powershell
New-Item -ItemType Junction `
  -Path "$env:USERPROFILE\.codex\skills\price-action-analysis" `
  -Target "D:\Code\Price-action-analysis"
```

连接完成后，新开的 Codex 会在可用 skills 中看到 `price-action-analysis`。

## 连接到 Claude Code

```bash
# Linux / macOS / WSL
ln -s "$(pwd)" ~/.claude/skills/price-action-analysis
```

连接完成后，Claude Code 中通过 `/price-action-analysis` 或自然语言触发。

也可以把目录放到 Claude Code 的项目 skill 目录：

```bash
ln -s "$(pwd)" /your-project/.claude/skills/price-action-analysis
```

## 依赖安装

```bash
python3 -m pip install Pillow
```

`render_annotations.py` 仅依赖 Pillow（Python Imaging Library），其余为标准库。如果用 venv：

```bash
python3 -m venv .venv && .venv/bin/pip install Pillow
```

### 中文字体环境

标注渲染需要中文字体，不同平台安装方式：

| 平台 | 安装命令 | 备注 |
|------|---------|------|
| **Linux (Debian/Ubuntu)** | `sudo apt install fonts-wqy-zenhei` | 推荐，文泉驿正黑 |
| **Linux (Arch)** | `yay -S wqy-zenhei` | |
| **macOS** | 无需额外安装 | 系统自带 PingFang / STHeiti |
| **Windows** | 无需额外安装 | 系统自带微软雅黑 / SimHei |

## 使用方式

### Codex

在 Codex 中提供 K 线截图后调用：

```text
Use $price-action-analysis 根据这张 K 线图生成一张带通道、区间、箭头、关键价位和文字标签的价格行为分析图，并给出下一步交易计划、失效条件和不交易条件。
```

### Claude Code

```text
/price-action-analysis 根据这张 K 线图生成价格行为分析标注图
```

或直接用自然语言，Claude Code 会自动加载匹配的 skill。

渲染脚本也可以单独运行：

```bash
# Linux / macOS / WSL
python3 scripts/render_annotations.py <chart-image> <annotations.json> <output.png|output.svg>

# Windows PowerShell
python scripts/render_annotations.py <chart-image> <annotations.json> <output.png|output.svg>
```

## 交付标准

- 图上必须有历史复盘层和当前计划层。
- 历史复盘不能只写形态名称，必须说明当时证据、当时计划、失效点和后续验证。
- 当前计划必须包含触发条件、止损或失效、目标区域和不交易条件。
- 图上文字不能遮挡关键 K 线、最后一段走势或价格轴。
- 使用实时价格或最新行情时，必须说明数据来源和时间。
