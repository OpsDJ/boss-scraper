import time
import json
import pandas as pd
from DrissionPage import Chromium
import os
import requests

browser = Chromium()
tab = browser.latest_tab

# ==========================================
# 加载配置
# ==========================================
with open("../config.json", "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

INPUT_CSV = "../output/boss_jobs.csv"

DS = CONFIG["deepseek"]
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", DS["api_key"])
DEEPSEEK_BASE_URL = DS["base_url"]
DEEPSEEK_MODEL = DS["model"]

MY_PROFILE = CONFIG["profile"]

GREET = CONFIG["auto_greet"]
BASE_DELAY = GREET["base_delay"]
MAX_RETRIES = GREET["max_retries"]
RATE_LIMIT_COOLDOWN = GREET["rate_limit_cooldown"]

SEARCH = CONFIG["search"]
KEYWORD = SEARCH["keyword"]

job_detail_api = "https://www.zhipin.com/wapi/zpgeek/job/detail.json"
friend_add_api = "https://www.zhipin.com/wapi/zpgeek/friend/add.json"
search_base = "https://www.zhipin.com/web/geek/jobs"
greeted_file = "../output/greeted.txt"
eval_file = "../output/eval_results.json"
approved_csv = "../output/approved_jobs.csv"

# ==========================================
# 工具函数
# ==========================================
def is_rate_limited(result):
    if not result:
        return False
    code = result.get("code", 0)
    msg = result.get("message", "")
    return code == 31 or "频繁" in msg or "稍后" in msg

def is_need_login(result):
    if not result:
        return False
    code = result.get("code", 0)
    msg = result.get("message", "")
    return code == 3 or "登录" in msg or "未登录" in msg

def wait_for_login():
    """等待用户登录"""
    url = f"{search_base}?city=101280100&query={KEYWORD}"  # 用广州作为默认登录页
    tab.get(url)
    time.sleep(3)

    # 弹窗提示
    print("=" * 50)
    print("⚠ 请在弹出的浏览器中登录 Boss直聘")
    print("  登录成功后程序将自动检测并继续...")
    print("=" * 50)

    while True:
        try:
            # 尝试访问搜索页看是否能正常加载
            tab.get(url)
            time.sleep(3)
            # 检查页面是否需要登录（有登录按钮说明未登录）
            need_login = tab.run_js("""
                return document.querySelector('.login-btn') !== null ||
                       document.querySelector('[class*="login"]') !== null;
            """)
            if not need_login:
                print("  检测到登录成功\n")
                return
        except Exception:
            pass
        time.sleep(5)

# ==========================================
# 阶段零：加载数据
# ==========================================
print("=" * 60)
print("加载数据...")
print("=" * 60)

if not os.path.exists(INPUT_CSV):
    print(f"❌ 未找到 {INPUT_CSV}，请先运行 collector/claw.py 采集数据")
    exit(1)

df = pd.read_csv(INPUT_CSV)
print(f"已加载 {len(df)} 条岗位")

# 检查必要列
required_cols = ["securityId", "jobName", "brandName"]
missing = [c for c in required_cols if c not in df.columns]
if missing:
    print(f"❌ CSV 缺少必要列：{missing}")
    exit(1)

# 检查 encryptJobId
if "encryptJobId" not in df.columns:
    df["encryptJobId"] = ""
else:
    df["encryptJobId"] = df["encryptJobId"].astype(str).replace("nan", "")
need_encrypt = (df["encryptJobId"] == "").sum()

# 检查 postDescription
if "postDescription" not in df.columns:
    df["postDescription"] = ""
else:
    df["postDescription"] = df["postDescription"].astype(str).replace("nan", "")
need_desc = (df["postDescription"] == "").sum()

# 检查 activeTimeDesc
if "activeTimeDesc" not in df.columns:
    df["activeTimeDesc"] = ""
else:
    df["activeTimeDesc"] = df["activeTimeDesc"].astype(str).replace("nan", "")

print(f"缺少 encryptJobId：{need_encrypt} 条")
print(f"缺少 postDescription：{need_desc} 条")

# ==========================================
# 阶段一：补全缺失数据（encryptJobId + postDescription）
# ==========================================
if need_encrypt > 0 or need_desc > 0:
    print(f"\n{'=' * 60}")
    print("阶段一：补全缺失数据...")
    print("=" * 60)

    # 确保已登录
    wait_for_login()

    for i, (idx, row) in enumerate(df.iterrows()):
        sid = row["securityId"]
        need_fetch = False

        if str(row.get("encryptJobId", "")) == "":
            need_fetch = True
        if str(row.get("postDescription", "")) == "":
            need_fetch = True

        if not need_fetch:
            continue

        # 每 5 次刷新主页
        if i % 5 == 0:
            tab.get("https://www.zhipin.com/")

        ok = False
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                tab.listen.start(targets=job_detail_api)
                tab.get(f"{job_detail_api}?securityId={sid}")
                res = tab.listen.wait(timeout=15)
                data = res.response.body

                if is_rate_limited(data):
                    print(f"  ⚠ 限流，冷却 {RATE_LIMIT_COOLDOWN}s...")
                    time.sleep(RATE_LIMIT_COOLDOWN)
                    continue

                if is_need_login(data):
                    wait_for_login()
                    continue

                if not data or "zpData" not in data:
                    raise Exception("响应异常")

                job_info = data.get("zpData", {}).get("jobInfo", {})
                boss_info = data.get("zpData", {}).get("bossInfo", {})
                encrypt_id = job_info.get("encryptJobId", "")
                desc = job_info.get("postDescription", "")
                active_time = boss_info.get("activeTimeDesc", "")

                if encrypt_id:
                    df.at[idx, "encryptJobId"] = encrypt_id
                if desc:
                    df.at[idx, "postDescription"] = desc
                if active_time:
                    df.at[idx, "activeTimeDesc"] = active_time
                ok = True
                break

            except Exception as e:
                time.sleep(BASE_DELAY * attempt)

        if ok:
            print(f"[{i + 1}/{len(df)}] {row['jobName']} @ {row['brandName']} — 补全完成")
        else:
            print(f"[{i + 1}/{len(df)}] {sid} — 补全失败")

        time.sleep(BASE_DELAY)

    # 保存补全后的数据
    df.to_csv(INPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"数据已回写 → {INPUT_CSV}\n")

# ==========================================
# 阶段二：LLM 评估岗位匹配度
# ==========================================
print("=" * 60)
print("阶段二：LLM 评估岗位匹配度...")
print("=" * 60)

evaluations = {}
eval_errors = 0
if os.path.exists(eval_file):
    with open(eval_file, "r", encoding="utf-8") as f:
        raw_evals = json.load(f)
    for sid, ev in raw_evals.items():
        reason = ev.get("reason", "")
        score = ev.get("score", 0)
        # 网络异常的结果视为未评估，允许重试
        if score == 0 and ("异常" in reason or "API错误" in reason or "Error" in reason):
            eval_errors += 1
            continue
        evaluations[sid] = ev
    print(f"已加载 {len(evaluations)} 条有效评估" + (f"（{eval_errors} 条异常将重试）" if eval_errors else ""))


def evaluate_job(row):
    """调用 DeepSeek 评估单个岗位"""
    desc = str(row.get("postDescription", ""))
    job_info = f"""
岗位名称：{row.get('jobName', '')}
薪资范围：{row.get('salaryDesc', '')}
技能要求：{row.get('skills', '')}
经验要求：{row.get('jobExperience', '')}
学历要求：{row.get('jobDegree', '')}
城市：{row.get('cityName', '')}
区域：{row.get('areaDistrict', '')}
公司：{row.get('brandName', '')}
行业：{row.get('brandIndustry', '')}
公司规模：{row.get('brandScaleName', '')}
职位描述：
{desc[:1500]}
"""

    prompt = f"""你是一个职业匹配评估助手。请根据以下信息，判断这个岗位是否适合我投递。

{MY_PROFILE}

## 待评估岗位
{job_info}

## 评估要求
请严格按以下 JSON 格式输出（不要输出其他内容）：
{{"decision": "yes或no", "score": 1-5的整数, "reason": "一句话理由，不超过50字"}}

评分标准：
- 5分：非常匹配，技能和经验都很对口，互联网行业，有技术含量
- 4分：较匹配，大部分技能吻合，有技术含量，可能经验或行业稍有偏差
- 3分：一般，部分匹配但存在明显差距
- 2分：不太匹配，技能或行业方向差异大
- 1分：完全不匹配（纯业务岗、销售岗、与数据分析无关）

关键判断规则：
- 如果岗位是纯销售/客服/地推/行政 → decision=no, score=1
- 如果岗位需要 Python/SQL/数据分析/数据开发等技术 → 高分倾向
- 如果公司是互联网/科技行业 → 加分
- 如果薪资明确低于6K → decision=no
- 如果薪资范围下限超过12K或上限超过18K（薪资过高，资历不够）→ decision=no
- 薪资在6K-10K区间 → 加分
- 如果是实习岗且无转正 → decision=no"""

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是一个严格的职业匹配评估助手。只输出 JSON，不要输出其他内容。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 200,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30,
            )
            if resp.status_code != 200:
                if attempt < MAX_RETRIES:
                    time.sleep(2 * attempt)
                    continue
                return "no", 0, f"API错误:{resp.status_code}"

            content = resp.json()["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                if content.endswith("```"):
                    content = content[:-3]

            result = json.loads(content)
            return result.get("decision", "no"), int(result.get("score", 0)), result.get("reason", "")

        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            if attempt < MAX_RETRIES:
                time.sleep(2 * attempt)
                continue
            return "no", 0, f"异常:{e}"


approved = []
rejected = []

for i, (idx, row) in enumerate(df.iterrows()):
    sid = str(row["securityId"])

    if sid in evaluations:
        prev = evaluations[sid]
        tag = "✅" if prev["decision"] == "yes" else "❌"
        print(f"[{i + 1}/{len(df)}] {row['jobName']} @ {row['brandName']} — {tag} 已评估({prev['decision']})")
        if prev["decision"] == "yes":
            approved.append(row)
        else:
            rejected.append(row)
        continue

    desc = str(row.get("postDescription", ""))
    if not desc or desc == "nan":
        evaluations[sid] = {"decision": "no", "score": 0, "reason": "无职位描述"}
        rejected.append(row)
        print(f"[{i + 1}/{len(df)}] {row['jobName']} @ {row['brandName']} — 无描述，跳过")
        continue

    # 活跃度预筛选：只有白名单内的才进入 LLM 评估，省 token
    active = str(row.get("activeTimeDesc", ""))
    valid_active = {"刚刚活跃", "今日活跃", "本周活跃", "2周内活跃", "3日内活跃", "本月活跃"}
    if active not in valid_active:
        evaluations[sid] = {"decision": "no", "score": 1, "reason": f"BOSS活跃度不达标（{active or '未知'}）"}
        rejected.append(row)
        print(f"[{i + 1}/{len(df)}] {row['jobName']} @ {row['brandName']} — ❌ {active or '未知'}，跳过")
        continue

    decision, score, reason = evaluate_job(row)
    evaluations[sid] = {"decision": decision, "score": score, "reason": reason}

    if decision == "yes":
        approved.append(row)
        print(f"[{i + 1}/{len(df)}] {row['jobName']} @ {row['brandName']} — ✅ 通过({score}分) {reason}")
    else:
        rejected.append(row)
        print(f"[{i + 1}/{len(df)}] {row['jobName']} @ {row['brandName']} — ❌ 不投({score}分) {reason}")

    tmp = eval_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(evaluations, f, ensure_ascii=False, indent=2)
    os.replace(tmp, eval_file)  # 原子操作，防止中断损坏文件

    time.sleep(0.5)

print(f"\n评估完成：通过 {len(approved)} / 拒绝 {len(rejected)} / 总计 {len(df)}")

# 保存通过列表
if approved:
    pd.DataFrame(approved).to_csv(approved_csv, index=False, encoding="utf-8-sig")
    print(f"通过列表已保存 → {approved_csv}\n")
else:
    print("没有通过的岗位，跳过打招呼阶段")
    exit(0)

# ==========================================
# 阶段三：打招呼
# ==========================================
print("=" * 60)
print(f"阶段三：发送沟通请求（{len(approved)} 个通过岗位）")
print("=" * 60)

# 加载已沟通记录
greeted = set()
if os.path.exists(greeted_file):
    with open(greeted_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                parts = line.split("|")
                if len(parts) >= 3 and parts[2] == "成功":
                    greeted.add((parts[0], parts[1]))

# 提取 lid
tab.get(f"{search_base}?city=101280100&query={KEYWORD}")
time.sleep(3)
lid = tab.run_js("""
    try {
        var store = window.__INITIAL_STATE__ || window.__NUXT__ || {};
        if (store.lid) return store.lid;
    } catch(e) {}
    return 'auto_' + Date.now().toString(36) + '.search.1';
""")
print(f"lid = {lid}\n")


def send_greet(sid, encrypt_job_id):
    ts = int(time.time() * 1000)
    post_url = f"{friend_add_api}?securityId={sid}&jobId={encrypt_job_id}&lid={lid}&_={ts}"
    tab.listen.start(targets=friend_add_api)
    tab.run_js(f"""
        var xhr = new XMLHttpRequest();
        xhr.open("POST", "{post_url}");
        xhr.setRequestHeader("Content-Type", "application/x-www-form-urlencoded");
        xhr.send("sessionId=");
    """)
    res = tab.listen.wait(timeout=15)
    return res.response.body, ""


def greet_with_retry(sid, encrypt_job_id):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result, _ = send_greet(sid, encrypt_job_id)
            if result and result.get("code") == 0:
                return "成功", result
            if is_rate_limited(result):
                print(f"     ⚠ 触发限流，冷却 {RATE_LIMIT_COOLDOWN}s...")
                time.sleep(RATE_LIMIT_COOLDOWN)
            else:
                print(f"     ⚠ code={result.get('code')}，重试 {attempt}/{MAX_RETRIES}")
                time.sleep(BASE_DELAY * attempt)
        except Exception as e:
            print(f"     ⚠ 异常，重试 {attempt}/{MAX_RETRIES}：{e}")
            time.sleep(BASE_DELAY * attempt)
    return "失败", None


for i, row in enumerate(approved):
    sid = row["securityId"]
    encrypt_job_id = str(row.get("encryptJobId", ""))
    name_key = (str(row["jobName"]), str(row["brandName"]))
    score = evaluations.get(sid, {}).get("score", "?")

    if name_key in greeted:
        print(f"[{i + 1}/{len(approved)}] {row['jobName']} @ {row['brandName']} ({score}分) — 已沟通过")
        continue

    if not encrypt_job_id:
        print(f"[{i + 1}/{len(approved)}] {sid} — 无 encryptJobId")
        continue

    print(f"[{i + 1}/{len(approved)}] {row['jobName']} @ {row['brandName']} ({score}分)", end="")
    status, _ = greet_with_retry(sid, encrypt_job_id)

    if status == "成功":
        print(" — 打招呼成功")
        greeted.add(name_key)
    else:
        print(" — 最终失败")

    with open(greeted_file, "a", encoding="utf-8") as f:
        f.write(f"{row['jobName']}|{row['brandName']}|{status}\n")

    time.sleep(BASE_DELAY)

print(f"\n全部完成：评估通过 {len(approved)} → 成功沟通 {len(greeted)} 个岗位")
print(f"评估详情 → {eval_file}")
print(f"通过列表 → {approved_csv}")
