

# 营销通话话术合规质检系统

从公司内部呼叫明细表读取符合条件的营销通话记录，下载录音，调用内网 ASR 获得转写文本，
按营销场景加载话术规则，调用 TokenHub LLM 逐项判断合规性，程序校验与评分后写入 PostgreSQL。

现已提供中文本地 Web 工作台：管理营销场景、话术规则与场景规则关联，手动选择通话执行评判，查看执行进度、转写原文与逐规则证据。

## 在 Windows 上启动工作台

推荐 Python 3.12。在项目根目录打开 PowerShell：

```powershell
# 首次安装：创建项目独立 .venv，优先使用清华镜像，失败自动尝试阿里云
powershell -File scripts/setup.ps1

# 启动真实业务模式（读取现有 config.yaml）
.\.venv\Scripts\python.exe -X utf8 -m app.runners.web
```

浏览器打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。也可直接双击项目根目录的 `start-web.cmd`。
无需 Node.js、npm 或前端构建命令；页面资源随 Python 服务本地提供，不依赖 CDN。
如果 PowerShell 限制执行脚本，可直接执行下文的 venv / pip 命令。

没有公司内网时，可先体验独立的离线演示：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m app.runners.web --demo --port 8001
```

打开 [http://127.0.0.1:8001](http://127.0.0.1:8001)。页面明确标识演示模式，使用虚构通话和模拟 ASR/LLM，但经过真实规则加载、证据校验、评分及入库流程。临时 SQLite 数据随服务退出清除，不读取 `config.yaml`，不访问公司服务。示例包含合规、不合规及服务失败三种情况；新增自定义演示规则会得到待复核响应，真实模式才会调用 LLM 语义判断。

更换开发机后，不要复制旧 `.venv`；在新机器重新安装依赖。若 Python 不在 PATH，可指定：

```powershell
powershell -File scripts/setup.ps1 -Python "C:\path\to\python.exe"
```

## 架构链路

```text
通话记录 → 录音 → ASR → 场景规则 → LLM逐规则判断 → 程序校验与评分 → 结构化入库

浏览器（原生 HTML/CSS/JS）
  └─ FastAPI /api
       ├─ AdminRepository → qc_scene / qc_rule / qc_scene_rule
       ├─ CallDatabaseAdapter → sor.dm_eva_feedorder_call_detail（只读）
       ├─ JobManager → ComplianceTaskService → 复用以上完整评判链路
       └─ qc_task / qc_transcript / qc_result / qc_rule_result → 进度与报告
```

## 目录结构

```text
speech_compliance/
├── app/
│   ├── config/          # settings.py / logging.py（配置与统一日志）
│   ├── domain/          # CallRecord / Scenario / Rule / Transcript / Compliance
│   ├── adapters/        # asr / tokenhub / recording / call_database
│   ├── repositories/    # rule / task / result
│   ├── services/        # compliance_service / scoring_service / evidence_service / container
│   ├── prompts/         # compliance_prompt.py
│   ├── schemas/         # llm_response.py
│   ├── web/             # API、CRUD、后台队列、离线演示与 static/ 前端
│   └── runners/         # single.py / batch.py / web.py
├── reference/           # 原三个参考文件（仅参考）
├── migrations/          # 建表 + 种子数据
├── tests/               # Test 1-12
├── config.example.yaml
├── requirements.txt
├── scripts/setup.ps1     # Windows 一键创建环境（中国镜像）
├── start-web.cmd         # Windows 双击启动
└── README.md
```

## 快速开始

### 1. 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -X utf8 -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

`-X utf8` 用于避免 Windows 默认 GBK 编码导致 requirements.txt 中的中文注释解码失败。
Linux / macOS 对应使用 `.venv/bin/python`。本次环境的精确依赖版本保存在 `requirements.lock.txt`，需要复现时将安装参数换成 `-r requirements.lock.txt`。

### 2. 配置

下文 `python` 命令应使用项目虚拟环境解释器。在 Windows 可将 `python` 替换为 `.\.venv\Scripts\python.exe -X utf8`。

```bash
# 仅首次配置时执行；已存在 config.yaml 时不要覆盖
cp config.example.yaml config.yaml
# 编辑 config.yaml，填入数据库/TokenHub/ASR 信息（敏感项用环境变量）
```

当前实现使用同一个 PostgreSQL Engine 读取源表并写入质检表，源表固定为 `sor.dm_eva_feedorder_call_detail`，质检表 schema 来自 `database.schema`。数据库用户须能读取源表，并能读写相应质检表。ASR 与 TokenHub 的地址和凭据只在服务端读取，不通过 Web API 返回；临时录音目录须可写。真实模式需要连通公司内网/VPN。

### 3. 建库 + 种子数据

```bash
python migrations/001_create_tables.py
python migrations/002_seed_scenes_rules.py
```

### 4. 运行

单条调试（打印完整链路信息）：

```bash
python -m app.runners.single --start 2026-05-06 --end 2026-05-07 --limit 1
```

批量质检：

```bash
python -m app.runners.batch \
  --start 2026-05-06 --end 2026-05-07 \
  --scene 90131206 --limit 20
```

### 5. 测试

```bash
python -m pytest tests/ -v
```

## 关键设计决策

- 场景为规则第一维度（`act_scene_id` 字符串处理，禁止 float）。
- 场景无规则 → SKIPPED / REVIEW_REQUIRED，绝不默认 100 分。
- LLM 只做逐规则语义判断；分数/状态由 `ScoringService` 纯 Python 计算。
- Evidence 防幻觉：证据片段必须规范化包含匹配于转写文本，否则自动转 REVIEW。
- 幂等：`qc_task.source_call_key` UNIQUE 约束，重复执行不会产生两份有效结果。
- 并发：`ThreadPoolExecutor` + ASR/LLM 全局 Semaphore 限流。
- 日志脱敏：不打印完整号码、Transcript、Token。

## 工作台操作说明

1. **营销场景**：新增 / 搜索 / 编辑 / 启停 / 删除 `qc_scene`。源场景 ID 必须与通话的 `act_scene_id` 一致，并始终作为字符串保存。
2. **话术规则**：管理 `qc_rule` 的编码、名称、类型、描述、标准话术、LLM 判定指令、严重程度、权重与生效区间。生效时间按 UTC+8，满足 `effective_from <= 通话时间 < effective_to`。规则内容变更时更新 revision_id / content_hash；这两项仅用于当前版本标识，不是完整版本历史。
3. **场景规则关联**：管理 `qc_scene_rule` 的场景、规则、启用状态和覆盖权重。选择器支持搜索；覆盖权重留空沿用规则值，填 0 表示零权重。删除仍有关联的场景/规则会被阻止，需先移除关联或停用配置。
4. **通话质检**：选择日期、场景 ID 和坐席 ID，查询后勾选通话并点击「开始评判」。页面日期包含首尾两天，后端转换为左闭右开区间；单次最多 32 个自然日。默认只显示已接通、有录音且达到最短时长的记录。源通话表不提供增删改。
5. **任务与结果**：每 3 秒刷新，展示下载 / ASR / LLM 阶段；明细包含转写原文、合规分数、逐规则原因、证据与证据校验情况。失败后排查原因，回到通话页重新查询并选择该通话重试。

当前关键参数表指上述三张数据库表。数据库连接、ASR/LLM 凭据、及格线、时长门槛、并发和超时仍由 `config.yaml` / 环境变量管理，修改后需重启服务。参数 CRUD 直接保存到数据库，下次规则加载时生效；已开始执行的批次请完成后再修改其规则。已完成 / 跳过 / 待复核任务沿用原有幂等规则，不会因为编辑参数自动重新评判。

### 执行与持久化边界

- 这是**本机单用户工作台**，绑定 `127.0.0.1`，只允许 localhost Host 与同源写入，无账号权限体系。共享部署需另行接入认证、权限和审计，不直接修改为公网监听。
- 批次、待执行队列及通话查询快照在内存中；已开始执行的任务阶段和报告保存在 PostgreSQL。关闭浏览器不会取消任务。服务正常退出会等待队列完成；强制结束进程会丢失尚未开始的队列，需重新查询并提交。未到终态的遗留任务可重新选择重试。
- 单个查询快照有效期 30 分钟，最多保留 100 页；单次提交最多 100 通，队列最多 200 通，最近批次最多 100 个。前端每页 30 通，翻页或重新查询会清空选择，避免误提交。
- Web 工作线程按 `task_workers` 配置，最多 20；ASR / LLM 信号量仍遵循现有配置。PostgreSQL 会话 advisory lock 防止 Web / CLI 并发重复执行同一通话，异常断开连接时释放锁。
- 重试会复用同一任务和转写记录，清理旧错误状态；总体结果与逐规则结果在同一事务内保存，避免半份报告。报告保留当时的规则名称、权重、判定和证据，不依赖后来编辑后的规则显示。
- 页面中号码脱敏，通话选择只接受服务器保存的源记录快照，不能由浏览器指定任意下载 URL。错误响应不回显上游密钥、数据库 DSN 或签名录音链接。音频由既有服务下载并在结束后清理；本版页面不提供在线播放器。

### 验证

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests -q
.\.venv\Scripts\python.exe -X utf8 -m pip check
```

测试不访问公司数据库、ASR 或 LLM，覆盖原有规则/评分测试，以及参数 CRUD、日期与权重校验、超长 ID、同源限制、分页、选择快照、重复提交、完整编排、单通失败隔离、失败重试和结果持久化。离线通过不代表真实数据库表结构和外部服务已经联调成功；真实服务需要在有相应网络访问权限的环境中验证。

### 常见问题

- **数据库未连接**：检查内网/VPN、环境变量、`config.yaml`、数据库权限和迁移 001。点击右上角状态按钮重试；若更改了配置，先重启服务。
- **查不到通话**：确认日期范围和 ID，必要时取消“仅显示符合质检资格”；低于门槛的记录可以查看但不可提交。
- **没有有效规则**：检查场景 ID、三层启用开关、关联及生效时间。此状态会跳过或要求复核，不会生成满分。
- **端口已占用**：先关闭此前启动窗口，或使用 `--port 8002`，访问相应端口。
- **首次建表**：迁移脚本不会自动创建自定义 schema，需先准备 `database.schema`；已有数据库无需重复插入种子数据。先用工作台查看配置再决定是否初始化。

## 当前未实现

公网录音上传、员工上传、自建 ASR/LLM、GPU、销售分析、话术优化、A/B 实验、多用户权限、持久化分布式任务队列、强制重评与规则版本历史。

