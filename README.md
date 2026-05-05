# Boss直聘 数据采集与自动沟通工具

基于 DrissionPage 浏览器自动化的 Boss直聘（zhipin.com）岗位信息采集和批量打招呼工具。

## 目录结构

```
├── collector/           # 数据采集模块
│   └── claw.py          #    多城市岗位搜索 → 详情采集 → CSV
├── auto_greet/          # 自动打招呼模块
│   └── auto_greek.py    #    读取CSV → 补全数据 → LLM评估 → 精准打招呼
├── data/                # 参考数据（城市代码、API响应示例）
├── config.json          # 统一配置文件（gitignore，需自行创建）
├── output/              # 运行时产物（gitignore）
├── CHANGELOG.md         # 更新日志
└── README.md
```

## 快速开始

```bash
# 1. 安装依赖
pip install pandas drissionpage requests

# 2. 创建配置文件（复制下方示例填入你的 API Key）
cp config.example.json config.json  # 或手动创建

# 3. 采集数据
cd collector
python claw.py          # 输入城市名（如：深圳,广州）或「全部」

# 4. 评估 + 打招呼
cd ../auto_greet
python auto_greek.py    # 读取 CSV → LLM 评估 → 只投匹配的岗位
```

## config.json 配置项

```json
{
  "deepseek":    { "api_key": "sk-xxx", "model": "deepseek-chat" },
  "search":      { "keyword": "数据", "url_filters": "experience=..." },
  "collect":     { "max_pages": 20, "base_delay": 10 },
  "auto_greet":  { "target_cities": {...}, "base_delay": 10 },
  "profile":     "## 我的背景\n- 技能：..."
}
```

所有配置集中在一个文件，两个模块共享。详见 `config.json` 内注释。

## 特性

- **自动登录检测**：首次运行弹出浏览器登录，后续 cookie 持久化自动复用
- **交互式城市选择**：支持输入城市名模糊匹配，或「全部」采集所有城市
- **URL 预筛选**：搜索时直接过滤经验、学历、行业，减少无关结果
- **断点续传**：城市级 + 岗位级两级进度追踪，中断重跑自动跳过已完成
- **进度状态标记**：`city_progress.txt` 记录每个城市采集状态（完成/部分/失败）
- **限流保护**：检测 `code=31` 自动冷却 90s 重试，登录过期自动等待重新登录
- **失败重试**：每请求最多 3 次重试，递增等待
- **LLM 智能筛选**：调用 DeepSeek API 评估岗位匹配度（技能/薪资/行业/活跃度）
- **BOSS 活跃度**：捕获 `activeTimeDesc`，排除半年未活跃的 HR

## 工作流

```
claw.py                              auto_greek.py
───────                              ─────────────
选择城市 → 搜索翻页 → 详情采集        读取CSV → 补全缺失 → LLM评估
              ↓                                      ↓
       boss_jobs.csv                         只投通过的岗位
       (+ activeTimeDesc)                    ↓
                                     greeted.txt (结果)
```

## 依赖

- Python 3.7+
- pandas — 数据处理
- DrissionPage — 浏览器自动化
- requests — LLM API 调用
