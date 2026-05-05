# 更新日志

## v1.1 — 2026-05-05 模块化重构

### 项目结构重组

- 拆分为 `collector/`（数据采集）和 `auto_greet/`（打招呼）两个独立模块
- 新增 `config.json` 统一管理所有配置（API Key、搜索筛选、个人条件等）
- `data/` 目录存放城市代码等参考数据，`output/` 存放运行时产物

### collector/claw.py

- **交互式城市选择**：启动时输入城市名（支持逗号分隔、模糊匹配），或输入「全部」采集所有 373 城
- **URL 筛选参数**：搜索时附加 `experience`、`industry` 等过滤条件，在请求层面减少无关结果
- **进度状态追踪**：`city_progress.txt` 格式升级为 `城市代码|状态`，状态分「完成」「部分」「失败」三种
  - 完成：全部页码正常采集完毕
  - 部分：遗漏了页码（中断/异常），重跑时重新采集
  - 失败：第一页就没拿到数据，重跑时重新采集
- 兼容旧版纯城市代码的进度文件
- 新增采集字段：`encryptJobId`（打招呼必需）、`activeTimeDesc`（BOSS 活跃度）
- 修复 `MAX_PAGES=0` 时 `new_count` 未定义的 bug

### auto_greet/auto_greek.py

- 改为从 `claw.py` 输出的 CSV 读取数据，不再重复采集
- 阶段一自动补全缺失的 `encryptJobId`、`postDescription`、`activeTimeDesc`
- LLM 评估规则增强：
  - 新增薪资上限过滤（下限超 12K 或上限超 18K → 不投）
  - 新增 BOSS 活跃度判断（半年前活跃等 → 不投）
  - 优化薪资偏好（6K-10K 最佳）
- 评估详情保存到 `eval_results.json`，通过列表保存到 `approved_jobs.csv`
- 修复 `approved` list 迭代 `.iterrows()` 报错
- 修复 pandas dtype 兼容性（float64 → str）

### 配置文件

新增 `config.json`，包含以下段：

| 段 | 用途 |
|------|------|
| `deepseek` | API Key、Base URL、模型名 |
| `search` | 关键词、URL 筛选参数 |
| `collect` | 翻页数、延迟、重试次数 |
| `auto_greet` | 打招呼参数、目标城市 |
| `profile` | 个人背景 + 岗位偏好（LLM 评估用） |

`claw.py` 读 `search` + `collect`，`auto_greek.py` 读 `deepseek` + `profile` + `auto_greet`。

### 其他

- `config.json`、`output/` 加入 `.gitignore`，防止 API Key 和运行数据提交
- README 重写，增加快速开始指南和配置说明
- 新增 `CHANGELOG.md`
