# SciPilot 星火知识库后端接入说明

## 1. 当前接入结果

SciPilot 已新增星火 ChatDoc 后端适配器。所有鉴权信息只保存在
`backend/.env`，前端仍然只访问 SciPilot FastAPI，不接触 AppID、
APISecret 或知识库 ID。

新增接口（均需要 SciPilot 登录令牌）：

- `GET /api/v1/knowledge/xunfei/status`：检查配置是否完整，不返回密钥。
- `POST /api/v1/knowledge/xunfei/answer`：直接验证星火知识库问答。
- 现有 `/api/v1/chat` 与 `/api/v1/agents/{agent_id}/ask` 可通过
  `XFYUN_KB_MODE` 接入星火知识库。

## 2. 需要从队友或讯飞控制台获得的信息

| 配置 | 是否必需 | 获取位置/说明 |
| --- | --- | --- |
| `XFYUN_KB_APP_ID` | 是 | 该知识库所属讯飞应用的 AppID |
| `XFYUN_KB_API_SECRET` | 是 | ChatDoc 接口鉴权使用的 APISecret；不是 APIKey |
| `XFYUN_KB_REPO_ID` | 是 | 已构建知识库的 repoId |
| `XFYUN_KB_BASE_URL` | 通常无需更改 | 官方地址 `https://chatdoc.xfyun.cn` |

当前仓库文档记录的 repoId 是
`193588d54888467f8d18001408bc22aa`。repoId 本身不能代替 AppID 或
APISecret。若队友截图或聊天记录里发过 APISecret，应先在讯飞控制台轮换，
再把新值写入本机环境文件。

## 3. 本机配置

只编辑本机的 `backend/.env`，不要把真实值写入 `.env.example`：

```dotenv
XFYUN_KB_MODE=prefer
XFYUN_KB_APP_ID=你的知识库所属应用AppID
XFYUN_KB_API_SECRET=轮换后的ChatDoc APISecret
XFYUN_KB_REPO_ID=193588d54888467f8d18001408bc22aa
XFYUN_KB_BASE_URL=https://chatdoc.xfyun.cn
XFYUN_KB_CONNECT_TIMEOUT=10
XFYUN_KB_READ_TIMEOUT=600
XFYUN_KB_TOP_N=6
XFYUN_KB_RETRIEVAL_FILTER_POLICY=REGULAR
XFYUN_KB_TEMPERATURE=0.2
```

模式说明：

- `off`：仅使用现有 Supabase RAG，默认值。
- `fallback`：Supabase 没检索到引用时，再调用星火知识库。
- `prefer`：未指定 Supabase collection 时优先调用星火知识库。

## 4. 验证步骤

1. 安装后端依赖并启动 FastAPI。
2. 在 `/docs` 使用 `/api/v1/auth/login` 获取 token。
3. 点击 Swagger 右上角 `Authorize`，填入 `Bearer <token>`。
4. 调用 `GET /api/v1/knowledge/xunfei/status`，确认
   `configured=true`。
5. 调用 `POST /api/v1/knowledge/xunfei/answer`：

```json
{
  "message": "敏捷软件开发中如何管理质量需求？",
  "top_n": 6,
  "thinking_output": false
}
```

6. 成功响应应包含 `answer`、`sid`、`citations` 和
   `provider: xunfei-chatdoc`。
7. 将 `XFYUN_KB_MODE` 设为 `prefer` 并重启后端，再从现有 Agent 页面
   发送问题；消息元数据中的 `retrieval_mode` 应为 `xunfei-chatdoc`。

## 5. 知识库内容仍需完成的工作

远端交付说明记录：此前仅小批上传 3 篇，上传请求成功但后续处理状态均为
`failed`。必须先使用仓库 `KnowledgeBase` 下的批量脚本完成 3 篇小批验证，
确认文件全部进入 `vectored`，并且问答收到结束帧和引用帧，再上传剩余论文。

因此，“后端代码已接通”和“知识库内容已可用”是两件事。只有文档状态为
`vectored` 时，ChatDoc 才能检索并回答。

## 6. 安全边界

- 不要把 `XFYUN_KB_API_SECRET` 放进前端、README、截图或 Git。
- 不要把 APISecret 当成普通 APIKey；本接口使用 AppID + APISecret 签名。
- 后端日志不打印鉴权请求头。
- `.xfyun-upload-state.json` 只用于本地断点续传，已加入 `.gitignore`。
