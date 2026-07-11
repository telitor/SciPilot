# 项目规划 Agent 功能与后端接入说明

本文档用于说明 SciPilot 项目规划 Agent 的核心功能、输入输出规范，以及后端如何接入讯飞星辰 Agent。项目规划 Agent 不只是回答“项目应该怎么做”，而是要把用户的项目想法转换为可执行、可检查、可迭代的实施方案。

前端不应直接持有或调用讯飞平台密钥，统一通过 SciPilot 后端完成用户鉴权、会话校验、Agent 路由、模型调用、消息存储和结果返回。

## 1. 接入目标

项目规划 Agent 面向软件项目、课程设计、科研工具和竞赛作品等场景，围绕“功能落地”提供规划能力。第一版应重点支持以下功能：

| 功能 | 说明 | 主要产出 |
| --- | --- | --- |
| 项目目标澄清 | 识别项目背景、目标用户、核心问题和交付目标 | 项目定位、用户角色、目标说明 |
| 需求与范围定义 | 区分必须实现、应该实现和后续扩展功能 | MVP 范围、非目标、功能优先级 |
| 功能模块拆解 | 将项目拆成可独立开发和验收的业务模块 | 功能树、模块职责、模块依赖 |
| 用户流程设计 | 描述用户从进入系统到完成任务的完整路径 | 用户故事、关键流程、异常流程 |
| 技术架构规划 | 根据需求给出前端、后端、数据库和外部服务方案 | 技术选型、系统架构、调用链路 |
| 数据库设计 | 根据业务对象规划数据表及其关系 | 核心表、关键字段、表关系 |
| 后端接口设计 | 把前端功能映射为可实现的 API | 接口清单、请求参数、返回结果 |
| 开发计划生成 | 按依赖关系拆分阶段、任务和里程碑 | 开发顺序、任务清单、工期建议 |
| 验收标准生成 | 为每个核心功能定义可验证的完成条件 | 功能验收项、接口验收项、异常场景 |
| 风险与迭代建议 | 识别时间、技术、数据和依赖风险 | 风险清单、降级方案、后续版本 |

建议后端继续对外使用当前业务接口：

```http
POST /chat
```

后端根据数据库中 Agent 的 `category` 字段进行路由。当 `category == "project-planning"` 时，调用项目规划 Agent；其他类型保持原有处理方式。

## 2. 功能边界与交互原则

### 2.1 Agent 必须完成的工作

项目规划 Agent 的回答应满足以下要求：

1. 先确认用户要做什么，再开始给方案。
2. 优先规划功能和用户流程，技术选型服务于功能实现。
3. 明确区分 MVP、增强功能和暂不实现功能。
4. 每个模块都说明输入、处理过程、输出和验收方式。
5. 前端页面必须映射到后端接口或本地状态，不能只描述界面。
6. 后端接口必须说明调用方、主要参数、返回结果和权限要求。
7. 开发计划必须考虑依赖顺序，避免前后端各自孤立开发。
8. 信息不足时先列出关键假设，并提出不超过 5 个高价值澄清问题。

### 2.2 Agent 不应出现的回答

| 不推荐做法 | 原因 | 正确处理方式 |
| --- | --- | --- |
| 只罗列技术名词 | 无法指导开发 | 说明技术服务于哪个功能 |
| 只给页面列表 | 没有后端和数据支撑 | 同时给出接口、数据表和状态流转 |
| 一次规划全部高级功能 | 容易造成范围失控 | 先给 MVP，再给后续迭代 |
| 给出无法验收的描述 | 无法判断是否完成 | 为每项功能补充验收标准 |
| 忽略登录、权限和异常场景 | 实际联调时容易返工 | 在接口和流程中显式体现 |
| 用户信息不足时直接猜测 | 方案可能偏离需求 | 标注假设并请求补充信息 |

## 3. 推荐输入信息

前端可以继续把用户输入作为 `message` 发送，但应通过表单提示用户尽量提供以下信息：

| 输入项 | 是否必需 | 示例 |
| --- | --- | --- |
| 项目名称或主题 | 是 | 校园二手交易平台 |
| 项目背景与目标 | 是 | 为校内学生提供可信的闲置物品交易渠道 |
| 目标用户 | 是 | 在校学生、平台管理员 |
| 核心需求 | 是 | 发布商品、搜索商品、在线沟通、订单管理 |
| 项目类型 | 否 | Web 应用、微信小程序、桌面端 |
| 技术限制 | 否 | React + FastAPI + PostgreSQL |
| 团队与周期 | 否 | 3 人，6 周完成 |
| 已有基础 | 否 | 已完成登录页面和数据库初始化 |
| 外部服务 | 否 | 对象存储、地图、支付、短信服务 |
| 期望输出 | 否 | 功能清单、接口设计、开发排期 |

推荐用户输入模板：

```text
项目名称：校园二手交易平台
项目目标：帮助校内学生发布和购买闲置物品
目标用户：学生、管理员
核心需求：商品发布、分类检索、收藏、订单、举报审核
技术栈：React + FastAPI + PostgreSQL
团队与周期：3 人，6 周
当前进度：只有原型图，尚未开发
请输出：MVP 功能、前后端模块、数据库表、API 和分阶段开发计划
```

## 4. 推荐输出结构

项目规划 Agent 应优先返回结构化 Markdown，确保用户可以直接复制到项目说明、需求文档或开发任务中。

### 4.1 标准输出模板

```markdown
# 项目规划：{项目名称}

## 1. 项目定位
- 项目目标：
- 目标用户：
- 核心价值：
- 关键假设：

## 2. MVP 功能范围
| 优先级 | 功能 | 用户价值 | 是否进入首版 |
| --- | --- | --- | --- |

## 3. 用户角色与核心流程
- 用户角色：
- 主流程：
- 异常流程：

## 4. 功能模块
| 模块 | 核心功能 | 输入 | 输出 | 验收标准 |
| --- | --- | --- | --- | --- |

## 5. 系统架构
- 前端：
- 后端：
- 数据库：
- 外部服务：
- 调用链路：

## 6. 数据库设计
| 表名 | 用途 | 关键字段 | 关系 |
| --- | --- | --- | --- |

## 7. 后端 API
| 方法 | 路径 | 功能 | 鉴权 | 请求 | 响应 |
| --- | --- | --- | --- | --- | --- |

## 8. 开发计划
| 阶段 | 前端任务 | 后端任务 | 联调与验收 | 依赖 |
| --- | --- | --- | --- | --- |

## 9. 风险与降级方案
| 风险 | 影响 | 应对方式 | 降级方案 |
| --- | --- | --- | --- |

## 10. 下一步行动
- [ ] 
```

### 4.2 功能模块输出要求

每个核心模块至少应描述以下内容：

```text
模块名称
├── 用户可以执行的操作
├── 前端页面或组件
├── 后端业务处理
├── 所需 API
├── 所需数据表
├── 正常状态流转
├── 权限与异常处理
└── 可验证的验收标准
```

例如，“项目任务管理”不能只写成一个页面，应展开为：

| 层级 | 内容 |
| --- | --- |
| 用户功能 | 创建任务、修改负责人、更新状态、查看进度 |
| 前端 | 任务列表、任务表单、状态筛选、进度看板 |
| 后端 | 校验项目成员、保存任务、记录状态变化、汇总进度 |
| API | `POST /projects/{id}/tasks`、`PATCH /tasks/{id}`、`GET /projects/{id}/tasks` |
| 数据表 | `projects`、`project_members`、`tasks`、`task_logs` |
| 权限 | 仅项目成员可查看，负责人和管理员可修改 |
| 验收 | 创建后可查询；越权修改返回 `403`；状态更新后进度同步变化 |

## 5. 配置项

真实密钥只能放在后端 `.env` 中，不要写入 Git 仓库或前端代码。建议为项目规划 Agent 单独配置 `assistant_id`，其余讯飞应用配置可以与论文精读 Agent 共用。

```env
# 讯飞星辰应用凭证
XF_AGENT_APP_ID=your_app_id
XF_AGENT_API_KEY=your_api_key
XF_AGENT_API_SECRET=your_api_secret

# 不同业务 Agent 的 assistant_id
XF_PAPER_READING_ASSISTANT_ID=your_paper_reading_assistant_id
XF_PROJECT_PLANNING_ASSISTANT_ID=your_project_planning_assistant_id

# WebSocket 地址配置
XF_AGENT_WS_HOST=spark-openapi.cn-huabei-1.xf-yun.com
XF_AGENT_WS_PATH=/v1/assistants/{assistant_id}

# 项目规划对话参数
XF_PROJECT_PLANNING_DOMAIN=generalv3
XF_PROJECT_PLANNING_TEMPERATURE=0.3
XF_PROJECT_PLANNING_TOP_K=3
XF_PROJECT_PLANNING_MAX_TOKENS=4096
```

配置说明：

| 配置项 | 含义 | 是否必填 |
| --- | --- | --- |
| `XF_AGENT_APP_ID` | 讯飞开放平台应用 `app_id` | 是 |
| `XF_AGENT_API_KEY` | 讯飞平台 APIKey | 是 |
| `XF_AGENT_API_SECRET` | 用于生成 WebSocket 签名的 API Secret | 是 |
| `XF_PROJECT_PLANNING_ASSISTANT_ID` | 项目规划 Agent 的智能体 ID | 是 |
| `XF_AGENT_WS_HOST` | WebSocket 域名 | 是 |
| `XF_AGENT_WS_PATH` | WebSocket 路径模板 | 是 |
| `XF_PROJECT_PLANNING_DOMAIN` | 模型领域参数 | 是 |
| `XF_PROJECT_PLANNING_TEMPERATURE` | 回答随机性，规划任务建议设置较低 | 否 |
| `XF_PROJECT_PLANNING_TOP_K` | 候选采样数量 | 否 |
| `XF_PROJECT_PLANNING_MAX_TOKENS` | 单次回答最大 token 数 | 否 |

## 6. 讯飞请求与响应协议

### 6.1 请求地址与鉴权

接口类型为流式 WebSocket：

```text
wss://spark-openapi.cn-huabei-1.xf-yun.com/v1/assistants/{assistant_id}
```

调用时把 `{assistant_id}` 替换为 `XF_PROJECT_PLANNING_ASSISTANT_ID`。鉴权 URL 仍由后端使用 `APIKey` 和 `API Secret` 生成，签名逻辑可以复用当前 `backend/services/xunfei_agent_service.py`。

带鉴权参数后的形式为：

```text
wss://spark-openapi.cn-huabei-1.xf-yun.com/v1/assistants/{assistant_id}?authorization={authorization}&date={date}&host={host}
```

### 6.2 请求 JSON 示例

```json
{
  "header": {
    "app_id": "your_app_id",
    "uid": "user_123456"
  },
  "parameter": {
    "chat": {
      "domain": "generalv3",
      "temperature": 0.3,
      "top_k": 3,
      "max_tokens": 4096
    }
  },
  "payload": {
    "message": {
      "text": [
        {
          "role": "user",
          "content": "请把校园二手交易平台拆成 MVP 功能，并给出前端页面、后端接口、数据库表和六周开发计划。"
        }
      ]
    }
  }
}
```

### 6.3 响应处理

讯飞接口以流式分片返回结果，后端按顺序拼接 `payload.choices.text[].content`。当 `header.status == 2` 或 `payload.choices.status == 2` 时，本轮回答结束。

```json
{
  "header": {
    "code": 0,
    "message": "Success",
    "sid": "session_id",
    "status": 2
  },
  "payload": {
    "choices": {
      "status": 2,
      "seq": 0,
      "text": [
        {
          "content": "# 项目规划：校园二手交易平台\n...",
          "index": 0,
          "role": "assistant"
        }
      ]
    }
  }
}
```

后端处理规则：

| 场景 | 处理方式 |
| --- | --- |
| `header.code == 0` | 正常解析并拼接回答 |
| `header.code != 0` | 记录 `code`、`message`、`sid`，返回统一错误 |
| 返回内容为空 | 抛出 `Xunfei agent returned empty reply` |
| WebSocket 超时 | 关闭连接并提示用户稍后重试 |
| 用户输入过长 | 在后端限制长度，必要时要求用户分阶段规划 |
| 用户取消生成 | 后端主动关闭 WebSocket 连接 |

## 7. 后端集成流程

当前 `/chat` 已包含鉴权、会话校验、Agent 查询、消息存储和模型调用流程。接入项目规划 Agent 后建议保持以下完整链路：

```text
1. 校验当前用户身份
2. 校验 conversation 属于当前用户
3. 校验 payload.agent_id 与 conversation.agent_id 一致
4. 查询 Agent 的 category 和 system_prompt
5. 校验并保存用户消息
6. 当 category == "project-planning" 时调用项目规划 Agent
7. 拼接讯飞流式回答
8. 保存 assistant 消息
9. 更新 conversation 标题和 updated_at
10. 返回回答及结构化元数据给前端
```

其中第 3 步很重要。当前后端分别校验了 conversation 和 agent 是否存在，但还应防止用户在一个会话中传入另一个 Agent 的 `agent_id`。

### 7.1 推荐的服务层调整

当前文件：

```text
backend/services/xunfei_agent_service.py
```

目前服务函数和环境变量只面向论文精读。建议把底层 WebSocket 调用改造成可复用函数，再分别提供论文精读和项目规划入口：

```python
def call_xunfei_agent(
    assistant_id: str,
    user_id: str,
    user_message: str,
    temperature: float,
    top_k: int,
    max_tokens: int,
) -> str:
    """调用指定的讯飞星辰 Agent，并返回拼接后的完整文本。"""
    ...


def call_project_planning_agent(user_id: str, user_message: str) -> str:
    return call_xunfei_agent(
        assistant_id=XF_PROJECT_PLANNING_ASSISTANT_ID,
        user_id=user_id,
        user_message=user_message,
        temperature=XF_PROJECT_PLANNING_TEMPERATURE,
        top_k=XF_PROJECT_PLANNING_TOP_K,
        max_tokens=XF_PROJECT_PLANNING_MAX_TOKENS,
    )
```

`backend/services/llm_service.py` 按类型路由：

```python
from services.xunfei_agent_service import (
    call_paper_reading_agent,
    call_project_planning_agent,
)


def generate_reply(
    system_prompt: str,
    user_message: str,
    agent_category: str = "",
    user_id: str = "",
) -> str:
    if agent_category == "paper-reading":
        return call_paper_reading_agent(user_id, user_message)

    if agent_category == "project-planning":
        return call_project_planning_agent(user_id, user_message)

    return call_default_llm(system_prompt, user_message)
```

### 7.2 后端业务接口

项目规划第一版可以完全复用现有会话接口，无需单独创建一套聊天 API。

#### 获取项目规划 Agent

```http
GET /agents
```

前端从返回列表中找到：

```json
{
  "id": "project_planning_agent_id",
  "name": "项目规划助手",
  "description": "帮助用户拆解项目功能、规划技术路线、设计数据库和接口。",
  "category": "project-planning"
}
```

#### 创建项目规划会话

```http
POST /conversations
Authorization: Bearer {access_token}
Content-Type: application/json
```

```json
{
  "agent_id": "project_planning_agent_id",
  "title": "校园二手交易平台规划"
}
```

#### 发送规划请求

```http
POST /chat
Authorization: Bearer {access_token}
Content-Type: application/json
```

```json
{
  "conversation_id": "conversation_id",
  "agent_id": "project_planning_agent_id",
  "message": "请根据当前需求输出 MVP 功能、前后端模块、数据库设计、API 和开发计划。"
}
```

#### 查询历史规划

```http
GET /conversations/{conversation_id}/messages
Authorization: Bearer {access_token}
```

历史消息用于继续补充需求、调整功能优先级和迭代已有方案。

## 8. 推荐返回给前端的数据

### 8.1 当前兼容格式

第一版可以继续使用当前返回结构，前端将 Markdown 渲染为规划结果：

```json
{
  "reply": "# 项目规划：校园二手交易平台\n\n## 1. 项目定位\n..."
}
```

### 8.2 推荐扩展格式

为方便前端实现目录导航、复制模块、导出文档和任务看板，后续可以增加元数据，同时保留 `reply` 兼容现有页面：

```json
{
  "reply": "完整 Markdown 规划内容",
  "agent_category": "project-planning",
  "conversation_id": "conversation_id",
  "plan_version": 1,
  "sections": [
    "项目定位",
    "MVP 功能范围",
    "功能模块",
    "系统架构",
    "数据库设计",
    "后端 API",
    "开发计划",
    "验收标准"
  ]
}
```

如果后续需要把规划结果直接转换为任务，可新增独立接口，不建议让前端解析任意 Markdown 后直接写入数据库：

```http
POST /conversations/{conversation_id}/plans/confirm
```

后端应先校验结构化规划数据，再创建项目、里程碑和任务记录。

## 9. 前后端功能衔接

项目规划页面不应只展示一个聊天框，建议围绕完整规划流程设计：

| 前端功能 | 后端支持 | 数据来源或结果 |
| --- | --- | --- |
| 选择项目规划 Agent | `GET /agents` | `category == project-planning` |
| 新建规划 | `POST /conversations` | 返回 `conversation_id` |
| 填写项目背景 | 前端表单，最终组装为 `message` | 项目目标、用户、技术、周期 |
| 生成规划 | `POST /chat` | Markdown 规划结果 |
| 查看历史版本 | `GET /conversations/{id}/messages` | 用户需求和 Agent 回答 |
| 继续细化模块 | 再次调用 `POST /chat` | 基于会话上下文补充规划 |
| 导出规划文档 | 前端导出 Markdown/PDF，或后续后端导出接口 | 当前规划内容 |
| 确认并生成任务 | 后续 `POST /plans/confirm` | 项目、里程碑、任务记录 |

前端推荐交互流程：

```text
选择项目规划助手
  → 新建会话
  → 填写项目基本信息
  → 生成第一版 MVP 规划
  → 按模块继续追问和修改
  → 确认最终方案
  → 导出文档或生成开发任务
```

## 10. 测试用例

### 10.1 最小能力测试

```text
你可以为软件项目提供哪些规划功能？请按功能产出说明，不要只介绍自己。
```

预期：至少覆盖目标澄清、MVP、功能模块、前后端架构、数据库、API、开发计划和验收标准。

### 10.2 完整项目规划测试

```text
我要做一个校园二手交易 Web 平台，用户包括学生和管理员。
学生可以发布商品、搜索商品、收藏、下单和举报，管理员负责审核商品和处理举报。
技术栈为 React、FastAPI、PostgreSQL，团队 3 人，开发周期 6 周。
请聚焦功能，输出 MVP 范围、用户流程、前端模块、后端模块、数据库表、API、开发顺序和验收标准。
```

预期：

- 明确区分 MVP 与后续功能。
- 每个核心功能都能对应前端、后端、数据库和 API。
- 开发顺序体现“数据模型 → 后端接口 → 前端页面 → 联调验收”的依赖关系。
- 包含登录鉴权、角色权限、参数校验和异常处理。
- 给出的任务可以直接转成开发清单。

### 10.3 信息不足测试

```text
帮我规划一个学习平台。
```

预期：Agent 不直接生成庞大方案，应先说明关键假设，并询问目标用户、核心场景、平台类型、团队周期和已有技术限制。

### 10.4 后端路由测试

| 场景 | 预期结果 |
| --- | --- |
| `category == project-planning` | 调用项目规划 Agent |
| `category == paper-reading` | 仍调用论文精读 Agent |
| 其他 category | 调用默认 LLM |
| 项目规划 `assistant_id` 缺失 | 返回可定位的后端配置错误 |
| conversation 不属于当前用户 | 返回 `404` 或统一权限错误 |
| conversation.agent_id 与请求 agent_id 不一致 | 拒绝请求，不调用模型 |
| 讯飞返回非零错误码 | 记录 `sid`，前端收到统一错误提示 |

## 11. 安全与质量要求

| 要求 | 说明 |
| --- | --- |
| 密钥只放后端 | `APIKey`、`API Secret` 不得暴露给前端 |
| `.env` 不提交 | 仓库只保留 `.env.example` 和占位值 |
| 日志脱敏 | 不打印完整鉴权 URL、密钥和用户 token |
| 会话归属校验 | 查询、发送和确认规划时都要校验当前用户 |
| Agent 一致性校验 | conversation 的 Agent 必须与请求中的 `agent_id` 一致 |
| 输入长度限制 | 防止超长需求导致调用失败或成本失控 |
| 输出内容校验 | 至少检查回答非空；结构化入库前必须校验字段 |
| 错误统一封装 | 不把第三方接口堆栈和敏感信息直接返回前端 |
| 超时与重试 | 设置 WebSocket 超时；重试次数有限且避免重复保存消息 |
| 规划可追溯 | 保存用户原始需求和每轮 Agent 回答，便于继续迭代 |

## 12. 后端接入检查清单

- [ ] 已在讯飞平台创建并发布项目规划 Agent
- [ ] 已确认当前 `APPID` 有调用该 Agent 的权限
- [ ] 已获取 `XF_PROJECT_PLANNING_ASSISTANT_ID`
- [ ] 已将讯飞配置写入后端 `.env`
- [ ] 已在 `.env.example` 中补充占位配置
- [ ] 已把讯飞 WebSocket 调用抽成可复用函数
- [ ] 已实现 `call_project_planning_agent(...)`
- [ ] 已在 `llm_service.py` 中增加 `project-planning` 路由
- [ ] 已校验 conversation 与请求 `agent_id` 一致
- [ ] 已保持用户消息和 Agent 回答的数据库存储流程
- [ ] 已处理超时、空回答和 `header.code != 0`
- [ ] 已完成最小能力、完整规划和信息不足测试
- [ ] 已验证前端可以创建会话、发送规划请求和展示 Markdown
- [ ] 已确认回答聚焦功能，并明确体现后端、数据库和接口
