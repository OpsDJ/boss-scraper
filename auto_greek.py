import time
import pandas as pd
from DrissionPage import Chromium
import os

browser = Chromium()
tab = browser.latest_tab

# ==========================================
# 配置
# ==========================================
CITY_CODE = "101280700"
KEYWORD = "大数据"
MAX_PAGES = 0
MAX_RETRIES = 3            # 单次请求最大重试次数
BASE_DELAY = 5             # 正常请求间隔（秒）
RATE_LIMIT_COOLDOWN = 90   # 触发限流后冷却时间（秒）

search_url = f"https://www.zhipin.com/web/geek/jobs?city={CITY_CODE}&query={KEYWORD}"
job_list_api = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json"
friend_add_api = "https://www.zhipin.com/wapi/zpgeek/friend/add.json"
greeted_file = "greeted.txt"

# ==========================================
# 安全取值
# ==========================================
def safe_get(d, key, default=""):
    return d.get(key, default) if d.get(key) not in [None, "null"] else default

# ==========================================
# 登录检测
# ==========================================
def wait_for_login():
    tab.listen.start(targets=job_list_api)
    tab.get(search_url)
    try:
        res = tab.listen.wait(timeout=10)
        data = res.response.body
        if data and "zpData" in data and "jobList" in data["zpData"]:
            print("检测到已登录，直接开始采集\n")
            return data
    except Exception:
        pass

    print("=" * 50)
    print("⚠ 未登录或登录已过期，请在弹出的浏览器中登录")
    print("  登录成功后程序将自动检测并继续...")
    print("=" * 50)
    while True:
        try:
            res = tab.listen.wait()
            data = res.response.body
            if data and "zpData" in data and "jobList" in data["zpData"]:
                print("检测到登录成功，开始采集\n")
                return data
        except Exception:
            continue

# ==========================================
# 阶段一：采集岗位列表（含 encryptJobId）
# ==========================================
print("=" * 50)
print("阶段一：采集岗位列表...")
print("=" * 50)

first_page_data = wait_for_login()

all_jobs = {}
page = 0

def collect_jobs(data):
    global all_jobs
    new_count = 0
    for job in data["zpData"]["jobList"]:
        sid = safe_get(job, "securityId")
        if sid and sid not in all_jobs:
            all_jobs[sid] = {
                "securityId": sid,
                "encryptJobId": safe_get(job, "encryptJobId"),
                "jobName": safe_get(job, "jobName"),
                "brandName": safe_get(job, "brandName"),
            }
            new_count += 1
    return new_count

new_count = collect_jobs(first_page_data)
page += 1
print(f"第 {page} 页：新增 {new_count} 条，累计 {len(all_jobs)} 条")

while page < MAX_PAGES:
    try:
        tab.scroll.to_bottom()
        res = tab.listen.wait(timeout=15)
        data = res.response.body

        if not data or "zpData" not in data or "jobList" not in data["zpData"]:
            continue

        new_count = collect_jobs(data)
        page += 1
        print(f"第 {page} 页：新增 {new_count} 条，累计 {len(all_jobs)} 条")

        if new_count == 0:
            print("没有新数据，翻页结束")
            break
    except Exception as e:
        print(f"错误：{e}")
        break

tab.listen.stop()
print(f"阶段一完成，共 {len(all_jobs)} 个岗位\n")

# ==========================================
# 加载已沟通记录（格式：岗位名称|公司名称|状态）
# ==========================================
greeted = set()
if os.path.exists(greeted_file):
    with open(greeted_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                parts = line.split("|")
                if len(parts) >= 3 and parts[2] == "成功":
                    greeted.add((parts[0], parts[1]))
    print(f"已加载 {len(greeted)} 条成功沟通记录\n")

# ==========================================
# 从搜索页提取 lid
# ==========================================
tab.get(search_url)
time.sleep(3)
lid = tab.run_js("""
    try {
        var store = window.__INITIAL_STATE__ || window.__NUXT__ || {};
        if (store.lid) return store.lid;
    } catch(e) {}
    return 'auto_' + Date.now().toString(36) + '.search.1';
""")
print(f"lid = {lid}\n")

# ==========================================
# 工具：判断是否被限流
# ==========================================
def is_rate_limited(result):
    """检测 API 返回是否触发限流"""
    if not result:
        return False
    code = result.get("code", 0)
    msg = result.get("message", "")
    # Boss直聘限流通常返回 code=31 或提示"操作太频繁"
    if code == 31 or "频繁" in msg or "稍后" in msg:
        return True
    return False

# ==========================================
# 工具：带重试的沟通请求
# ==========================================
def send_greet(sid, encrypt_job_id, lid):
    """
    发送一次沟通请求，返回 (result, error_msg)。
    result 为 API 响应的 dict，error_msg 为错误信息（成功时为空）。
    """
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

def greet_with_retry(sid, encrypt_job_id, lid):
    """带重试和限流处理的沟通请求，返回最终状态字符串"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result, err = send_greet(sid, encrypt_job_id, lid)

            if result and result.get("code") == 0:
                return "成功", result

            # 请求发出去了但返回非 0
            if is_rate_limited(result):
                print(f"     ⚠ 触发限流，冷却 {RATE_LIMIT_COOLDOWN}s...")
                time.sleep(RATE_LIMIT_COOLDOWN)
            else:
                print(f"     ⚠ 返回异常 code={result.get('code')}，重试 {attempt}/{MAX_RETRIES}")
                time.sleep(BASE_DELAY * attempt)

        except Exception as e:
            print(f"     ⚠ 请求异常，重试 {attempt}/{MAX_RETRIES}：{e}")
            time.sleep(BASE_DELAY * attempt)

    return "失败", None

# ==========================================
# 阶段二：批量发送沟通请求
# ==========================================
print("=" * 50)
print("阶段二：发送沟通请求...")
print("=" * 50)

job_items = list(all_jobs.values())

for i, job in enumerate(job_items):
    sid = job["securityId"]
    encrypt_job_id = job["encryptJobId"]
    name_key = (job["jobName"], job["brandName"])

    if name_key in greeted:
        print(f"[{i + 1}/{len(job_items)}] {job['jobName']} @ {job['brandName']} — 已沟通过，跳过")
        continue

    if not encrypt_job_id:
        print(f"[{i + 1}/{len(job_items)}] {sid} — 无 encryptJobId，跳过")
        continue

    print(f"[{i + 1}/{len(job_items)}] {job['jobName']} @ {job['brandName']}", end="")
    status, _ = greet_with_retry(sid, encrypt_job_id, lid)

    if status == "成功":
        print(" — 打招呼成功")
        greeted.add(name_key)
    else:
        print(" — 最终失败")

    with open(greeted_file, "a", encoding="utf-8") as f:
        f.write(f"{job['jobName']}|{job['brandName']}|{status}\n")

    time.sleep(BASE_DELAY)

print(f"\n完成，成功沟通 {len(greeted)} 个岗位")
