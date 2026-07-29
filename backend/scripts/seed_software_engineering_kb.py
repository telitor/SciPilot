"""Seed SciPilot with a public, copyright-safe software-engineering knowledge base.

This script intentionally stores only factual bibliography, official links, and
original Chinese summaries/checklists written for SciPilot.  It does not fetch,
copy, upload, or redistribute paper/standard/syllabus full text.

Run from the repository root after migrations 006-008:

    python backend/scripts/seed_software_engineering_kb.py

The service-role key is read from ``backend/.env`` by the existing Supabase
client factory.  Set ``SCIPILOT_SEED_USER_ID`` when more than one profile exists.
The script is idempotent: unchanged seed entries are reused; changed entries
replace only the system-managed document bearing the same stable ``seed_key``.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Any
from uuid import UUID

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from services.knowledge_base_service import (  # noqa: E402
    chunk_knowledge_text,
    create_embedding,
    estimate_tokens,
    sha256_bytes,
)
from services.supabase_service import get_supabase_client  # noqa: E402


COLLECTION_NAME = "软件工程公开知识入门"
SEED_VERSION = "2026-07-29.1"
CONTENT_POLICY = (
    "只保存书目信息、SciPilot 原创中文摘要和官方链接；不抓取、不缓存、"
    "不重新发布受版权保护的论文、标准、课程大纲或数据集全文。"
)

PAPER_SCOPE = (
    "本条正文为 SciPilot 原创概括；仅保存事实性书目信息与 arXiv 官方摘要页链接。"
    "论文正文、图表和附录权利归作者或出版方，本脚本不复制或分发其全文。"
)
STANDARD_SCOPE = (
    "本条正文为 SciPilot 原创学习卡片；只链接发布机构的官方页面。"
    "标准、指南或课程大纲原文权利归发布机构，本脚本不复制或分发其全文。"
)
REPOSITORY_SCOPE = (
    "本条正文为 SciPilot 原创使用说明；只链接项目官方仓库。仓库代码依其 LICENSE 使用，"
    "数据集及上游项目可能有独立许可，下载或再分发前必须逐项核验。"
)
NOTE_SCOPE = (
    "本条为 SciPilot 根据所列官方资料独立撰写的方法清单，可在本项目内检索和引用；"
    "外部资料权利与许可不因本条摘要而改变，且未复制其全文。"
)


@dataclass(frozen=True)
class SeedEntry:
    seed_key: str
    title: str
    source_type: str
    source_url: str
    license_scope: str
    topics: tuple[str, ...]
    agent_categories: tuple[str, ...]
    content: str
    official_sources: tuple[str, ...] = ()


def clean(text: str) -> str:
    return dedent(text).strip()


SEEDS: tuple[SeedEntry, ...] = (
    SeedEntry(
        seed_key="paper-attention-is-all-you-need",
        title="Attention Is All You Need：Transformer 论文精读卡",
        source_type="paper",
        source_url="https://arxiv.org/abs/1706.03762",
        license_scope=PAPER_SCOPE,
        topics=("Transformer", "self-attention", "sequence-modeling", "reproduction"),
        agent_categories=("paper-reading", "code-reproduction"),
        content=clean(
            """
            【书目信息】
            Vaswani 等，Attention Is All You Need，2017，arXiv:1706.03762。官方入口见来源链接。

            【原创概括】
            这项工作的工程价值，不只是提出“注意力”，而是把序列建模的主要信息交互改写为可并行的
            注意力计算，并用位置表示保留顺序信息。阅读时应分别追踪编码器、解码器、残差连接、归一化、
            多头机制和掩码的职责，避免把 Transformer 简化成单一公式。

            【精读问题】
            先说明论文要替代的计算瓶颈，再区分架构贡献与训练技巧；检查实验任务、比较基线、质量指标、
            训练成本和消融证据是否共同支持结论。论文中的机器翻译结论不能未经验证直接外推到代码理解。

            【复现提示】
            固定论文版本、数据切分、分词器、最大长度、随机种子、硬件和精度模式；记录学习率计划、批量
            大小与梯度累积后的有效批量。先做最小样本过拟合和张量形状测试，再扩大训练。若结果不同，
            优先排查掩码方向、位置编码、padding、评测脚本和解码策略。
            """
        ),
    ),
    SeedEntry(
        seed_key="paper-bert",
        title="BERT：双向预训练与下游适配精读卡",
        source_type="paper",
        source_url="https://arxiv.org/abs/1810.04805",
        license_scope=PAPER_SCOPE,
        topics=("BERT", "pretraining", "fine-tuning", "evaluation"),
        agent_categories=("paper-reading", "code-reproduction", "result-interpretation"),
        content=clean(
            """
            【书目信息】
            Devlin、Chang、Lee、Toutanova，BERT: Pre-training of Deep Bidirectional Transformers
            for Language Understanding，2018，arXiv:1810.04805。

            【原创概括】
            BERT 使用 Transformer 编码器学习上下文相关表示，再以较小的任务头适配分类、序列标注或
            问答。精读重点是区分预训练目标、输入表示、下游微调和评测协议：模型结构只是结果的一部分，
            语料、词表、任务切分和训练预算同样决定可比性。

            【软件工程迁移边界】
            问题单、需求文本和代码注释可视为自然语言，但源代码还包含作用域、类型和数据依赖。将 BERT
            迁移到代码任务时，应建立纯文本基线，并明确它没有天然编码程序结构。比较模型时保持训练数据、
            参数规模、搜索预算和测试集一致，避免把额外数据收益误判为架构收益。

            【复现与结果解释】
            保存模型与分词器版本、最大长度、截断规则、类别映射和每次随机种子。报告均值与离散程度，
            对类别不均衡任务同时给出适当的宏平均指标和错误样本分析，不只展示一次最佳运行。
            """
        ),
    ),
    SeedEntry(
        seed_key="paper-codebert-graphcodebert",
        title="CodeBERT 与 GraphCodeBERT：代码表示学习路线",
        source_type="paper",
        source_url="https://arxiv.org/abs/2002.08155",
        license_scope=PAPER_SCOPE,
        topics=("CodeBERT", "GraphCodeBERT", "code-representation", "data-flow"),
        agent_categories=("paper-reading", "code-reproduction", "result-interpretation"),
        official_sources=(
            "https://arxiv.org/abs/2009.08366",
            "https://github.com/microsoft/CodeBERT",
        ),
        content=clean(
            """
            【书目信息】
            CodeBERT：Feng 等，2020，arXiv:2002.08155。GraphCodeBERT：Guo 等，2020，
            arXiv:2009.08366。官方实现入口为 microsoft/CodeBERT。

            【原创比较】
            CodeBERT 面向自然语言与程序语言的联合表示，强调从成对和非成对数据中学习可迁移特征；
            GraphCodeBERT 在序列表示之外引入代码数据流关系，使变量之间“值从何处来”的联系参与预训练。
            两者的差别应落实到输入构造、预训练任务和下游评测，而不是只比较模型名称。

            【任务选择】
            代码搜索主要检验自然语言与代码表示的对齐；克隆检测关注功能相近代码；代码翻译与修复还要求
            生成结果可编译、可测试。不同任务的指标不能互换，生成任务仅有文本相似度也不足以证明语义正确。

            【复现清单】
            固定仓库提交、依赖版本、数据脚本和预训练检查点；核对解析器能否覆盖目标语言，并统计数据流
            提取失败率。先复现官方小规模命令，再改变一个变量。报告参数量、推理成本、失败样本以及是否
            使用额外训练数据，防止不公平比较。
            """
        ),
    ),
    SeedEntry(
        seed_key="paper-swe-bench",
        title="SWE-bench：真实仓库问题解决评测指南",
        source_type="paper",
        source_url="https://arxiv.org/abs/2310.06770",
        license_scope=PAPER_SCOPE,
        topics=("SWE-bench", "benchmark", "issue-resolution", "program-repair"),
        agent_categories=(
            "paper-reading",
            "problem-decomposition",
            "code-reproduction",
            "result-interpretation",
        ),
        official_sources=("https://github.com/SWE-bench/SWE-bench",),
        content=clean(
            """
            【书目信息】
            Jimenez 等，SWE-bench: Can Language Models Resolve Real-World GitHub Issues?，
            arXiv:2310.06770；项目与评测工具见 SWE-bench 官方 GitHub 仓库。

            【原创概括】
            该基准把真实问题描述、特定仓库版本和回归测试组合成任务，要求系统理解上下文并产生可验证的
            修改。它衡量的是从问题定位到补丁验证的整条链路，不等同于单函数生成能力。

            【问题拆解模板】
            将任务拆为：复现失败、定位相关模块、建立行为假设、设计最小修改、运行目标测试、运行回归测试、
            审查副作用。每一步都要保存证据；未通过测试的补丁不能因为解释合理而判为成功。

            【评测注意】
            锁定数据版本、仓库提交、容器镜像、测试补丁和超时策略；区分生成失败、应用补丁失败、环境失败
            与测试失败。检查训练数据或历史提交泄漏，不把不同子集、不同过滤条件的得分直接横比。使用数据
            和镜像前分别核验其许可与资源要求。
            """
        ),
    ),
    SeedEntry(
        seed_key="catalog-swebok-requirements",
        title="SWEBOK 导向的软件需求与问题拆解方法",
        source_type="catalog",
        source_url="https://www.computer.org/education/bodies-of-knowledge/software-engineering",
        license_scope=STANDARD_SCOPE,
        topics=("SWEBOK", "requirements", "traceability", "project-planning"),
        agent_categories=("problem-decomposition", "project-planning"),
        content=clean(
            """
            【来源定位】
            IEEE Computer Society 发布的 SWEBOK 用知识领域组织软件工程共识。本条不是指南摘录，而是
            为 SciPilot 独立编写的需求拆解操作卡；版本信息应以官方页面为准。

            【六层拆解】
            一、业务目标：为什么做、如何判断有价值。二、利益相关者：谁使用、谁维护、谁承担风险。
            三、场景与边界：正常流程、异常流程及明确不做的事项。四、需求：区分功能需求与性能、安全、
            可用性等质量要求。五、约束：预算、周期、平台、法规和数据来源。六、验收：为每项需求给出
            可观察的输入、操作、预期结果和失败判据。

            【追踪关系】
            建立“目标—需求—设计—接口—数据表—测试—发布证据”的双向追踪。需求变化时沿关系评估影响，
            不只修改页面描述。高风险或高不确定项优先做原型和验证，低价值功能放入后续范围。

            【智能体输出要求】
            问题拆解助手应列出事实、假设、待确认问题和依赖；项目规划助手应给出 MVP、里程碑、负责人、
            风险缓解与验收证据。含糊的“支持、优化、智能化”必须转化为可测试条件。
            """
        ),
    ),
    SeedEntry(
        seed_key="catalog-nist-ssdf",
        title="NIST SSDF：安全软件开发落地卡",
        source_type="catalog",
        source_url="https://csrc.nist.gov/pubs/sp/800/218/final",
        license_scope=STANDARD_SCOPE,
        topics=("NIST", "SSDF", "secure-development", "supply-chain"),
        agent_categories=("problem-decomposition", "project-planning", "code-reproduction"),
        content=clean(
            """
            【来源定位】
            NIST SP 800-218（SSDF 1.1）提供可嵌入不同生命周期的高层安全实践。本条用原创语言把它转为
            项目检查单；规范含义、版本和补充材料以 NIST 官方页面为准。

            【落地框架】
            准备组织：明确安全角色、培训、工具和开发环境；保护软件：控制源码、构建材料和发布制品的
            访问与完整性；生产安全软件：把威胁分析、代码审查、依赖检查和安全测试放进开发流程；响应
            漏洞：建立接收、分级、修复、披露和复盘机制。

            【项目规划字段】
            每项实践至少记录负责人、适用资产、触发时点、自动化检查、证据位置、失败处理和例外审批。
            依赖应锁定版本并保存来源与许可证；机密只进入受控变量，不能进入仓库、日志或前端包。

            【验收示例】
            合并请求通过单元测试、静态检查和依赖扫描；发布物可追溯到提交与构建流程；高危发现阻止发布；
            漏洞修复包含回归测试和根因行动。安全控制必须产生可审计证据，不能只写成口号。
            """
        ),
    ),
    SeedEntry(
        seed_key="catalog-github-actions-cicd",
        title="GitHub Actions：CI/CD 流水线设计与验收",
        source_type="catalog",
        source_url="https://docs.github.com/en/actions/get-started/quickstart",
        license_scope=STANDARD_SCOPE,
        topics=("CI", "CD", "GitHub-Actions", "automation"),
        agent_categories=("project-planning", "code-reproduction", "result-interpretation"),
        content=clean(
            """
            【来源定位】
            GitHub Actions 官方文档介绍以工作流自动执行构建、测试和部署。本条是平台无关的原创规划卡，
            YAML 语法、权限和计费限制应以当前官方文档为准。

            【流水线分层】
            快速反馈层执行格式化、静态检查和单元测试；集成层连接数据库或外部服务并保存测试报告；构建层
            生成带版本与校验值的制品；发布层仅消费已验证制品，并通过环境审批、最小权限密钥和回滚步骤
            保护生产环境。避免在部署阶段重新构建不同内容。

            【可复现性】
            固定运行时和依赖版本，缓存只用于加速而不是替代依赖声明；矩阵任务明确操作系统与版本组合；
            失败日志、覆盖率和制品设置保留期。第三方 Action 应固定到可信版本或提交，并审查其权限。

            【验收】
            拉取请求能阻止失败检查；主分支构建可追溯到提交；部署使用受保护环境；密钥不会出现在日志；
            同一制品可在预发布和生产间晋级；失败后能恢复到上一个已知良好版本。
            """
        ),
    ),
    SeedEntry(
        seed_key="note-reproducible-software-research",
        title="软件工程可复现实验最小证据包",
        source_type="note",
        source_url="https://github.com/github/CodeSearchNet",
        license_scope=NOTE_SCOPE,
        topics=("reproducibility", "experiment-design", "provenance", "artifact"),
        agent_categories=("project-planning", "code-reproduction", "result-interpretation"),
        official_sources=(
            "https://github.com/rjust/defects4j",
            "https://github.com/SWE-bench/SWE-bench",
        ),
        content=clean(
            """
            【目标】
            可复现不是“代码能启动”，而是另一位研究者能识别同一输入、重建环境、执行同一过程，并理解
            结果差异。本条由 SciPilot 结合三个官方项目仓库的可复现实践独立整理。

            【最小证据包】
            保存代码提交和未提交补丁；运行时、系统、硬件与依赖锁文件；数据来源、版本、许可、切分脚本
            和校验值；配置、随机种子、完整命令和资源预算；原始输出、结构化指标、日志、失败记录与绘图
            脚本。每个结果表必须能指回生成它的运行编号。

            【执行顺序】
            先在小样本完成端到端冒烟测试，再复现一个已知基线，然后运行目标实验。一次只改变一个主要
            因素；重复随机运行并记录全部结果。环境差异无法消除时，明确标记其影响而不是挑选最接近论文
            的一次运行。

            【交付检查】
            新环境可按 README 一次性初始化；无私有绝对路径和硬编码密钥；数据缺失时有清晰获取说明；
            测试脚本返回可靠退出码；结果表能由保存的原始数据重新生成；第三方资源许可被逐项记录。
            """
        ),
    ),
    SeedEntry(
        seed_key="catalog-codesearchnet",
        title="CodeSearchNet：代码搜索数据与评测使用卡",
        source_type="catalog",
        source_url="https://github.com/github/CodeSearchNet",
        license_scope=REPOSITORY_SCOPE,
        topics=("CodeSearchNet", "semantic-code-search", "dataset", "data-leakage"),
        agent_categories=("paper-reading", "code-reproduction", "result-interpretation"),
        official_sources=("https://arxiv.org/abs/1909.09436",),
        content=clean(
            """
            【资源定位】
            CodeSearchNet 官方仓库提供自然语言代码搜索相关的数据、工具和基线入口，对应论文见
            arXiv:1909.09436。本知识条目不复制数据集，只保存使用方法与官方链接。

            【任务建模】
            明确查询是文档字符串、问题描述还是用户真实输入；候选代码的粒度是函数、文件还是仓库；
            检索阶段与重排阶段使用哪些特征。离线指标反映排序质量，但不能自动代表真实用户满意度。

            【数据治理】
            保留来源仓库、语言、提交和许可证信息；检查重复代码、派生仓库及跨切分近重复，避免训练测试
            泄漏。仓库代码可有不同许可，不能把工具仓库的 MIT 许可误认为所有数据都可统一再分发。

            【复现与分析】
            固定预处理、分词、负样本构造、候选池和评测脚本；分别报告各语言结果、总体聚合方法、延迟和
            索引成本。对错误结果按查询歧义、命名偏差、长上下文、语言差异和语义近似分类。
            """
        ),
    ),
    SeedEntry(
        seed_key="catalog-defects4j",
        title="Defects4J：真实缺陷实验与程序修复验证卡",
        source_type="catalog",
        source_url="https://github.com/rjust/defects4j",
        license_scope=REPOSITORY_SCOPE,
        topics=("Defects4J", "testing", "fault-localization", "program-repair"),
        agent_categories=("code-reproduction", "result-interpretation", "project-planning"),
        content=clean(
            """
            【资源定位】
            Defects4J 官方仓库提供可复现的 Java 缺陷与实验基础设施。工具仓库标注 MIT 许可，但具体项目
            和下载内容仍应分别核验。本条不复制缺陷代码或数据。

            【实验单元】
            一个缺陷实验应明确项目标识、缺陷编号、缺陷版与修复版、触发测试、相关测试、运行环境及工具
            版本。先证明缺陷版稳定失败、修复版稳定通过，再评价定位或修复方法，否则环境错误可能被误当
            成算法失败。

            【复现流程】
            使用官方命令查询元数据并检出隔离工作区；记录 Java、时区和依赖；先编译，再运行触发测试，
            最后运行完整回归。自动程序修复还要检查补丁能否应用、编译、通过目标测试并避免回归。

            【结果边界】
            “测试通过”不等于语义完全正确，可能出现对测试集过拟合。报告排除样本、超时、基础设施失败、
            弃用缺陷和多次运行差异；不要在不同 Defects4J 版本或不同缺陷子集之间直接比较单一百分比。
            """
        ),
    ),
    SeedEntry(
        seed_key="catalog-istqb-testing",
        title="ISTQB CTFL 导向的软件测试设计卡",
        source_type="catalog",
        source_url="https://www.istqb.org/help/ctfl-v40/",
        license_scope=STANDARD_SCOPE,
        topics=("ISTQB", "testing", "test-design", "risk-based-testing"),
        agent_categories=("problem-decomposition", "project-planning", "result-interpretation"),
        official_sources=(
            "https://istqb.org/wp-content/uploads/2024/11/ISTQB_CTFL_Syllabus_v4.0.1.pdf",
        ),
        content=clean(
            """
            【来源定位】
            ISTQB CTFL 官方页面与大纲给出基础测试知识框架。本条为 SciPilot 原创操作卡，不替代大纲、
            培训或认证材料；术语和当前版本以 ISTQB 官方发布为准。

            【测试设计】
            从测试依据提取可验证条件，区分正常、边界、异常和权限场景；为每项测试写明前置条件、数据、
            操作、预期结果与清理。组合使用静态检查和动态测试，并按组件、集成、系统与验收目标组织证据。

            【风险优先】
            用发生可能性、影响和可检测性帮助排序，但保留业务关键路径的最低覆盖。缺陷报告包含可复现步骤、
            环境、实际结果、预期结果和证据，不用严重度代替修复优先级。

            【结果解释】
            通过率只有在测试范围稳定时才可比较；覆盖率表示执行范围，不证明断言质量。区分产品缺陷、
            测试缺陷、环境失败和偶发失败；修复后运行针对性确认测试，并对受影响区域执行回归测试。
            """
        ),
    ),
    SeedEntry(
        seed_key="note-nist-statistical-analysis",
        title="NIST 工程统计导向的实验结果分析清单",
        source_type="note",
        source_url="https://www.itl.nist.gov/div898/handbook/",
        license_scope=NOTE_SCOPE,
        topics=("statistics", "confidence-interval", "experiment-design", "evaluation"),
        agent_categories=("paper-reading", "project-planning", "result-interpretation"),
        official_sources=(
            "https://www.itl.nist.gov/div898/handbook/prc/section1/prc14.htm",
            "https://itl.nist.gov/div898/handbook/pri/section1/pri1.htm",
        ),
        content=clean(
            """
            【来源定位】
            NIST/SEMATECH 工程统计手册提供实验设计、比较与区间估计方法。本条是面向软件实验的原创检查单，
            具体公式、假设和适用条件应回到官方手册核验。

            【实验前】
            预先确定研究问题、主要指标、对照、实验单元、重复次数和停止规则；区分随机种子重复与真正独立
            样本。记录可能的混杂因素，如硬件、负载、数据版本和缓存。样本量与变异较大时，不应只看均值。

            【分析时】
            同时报出样本量、中心趋势、离散程度和适当的不确定性区间；检查异常值和缺失值形成原因，不因
            结果不利而随意删除。多指标、多模型或反复试验会增加偶然发现风险，应披露比较数量和选择过程。
            统计显著不等于工程上重要，还需报告效应大小、成本和实际阈值。

            【结论边界】
            相关关系不能自动解释为因果；单个数据集、语言或仓库上的结果不代表所有场景。结论应列出支持
            证据、反例、适用范围和威胁，并提供原始数据到图表的可追踪链路。图表必须标注单位、聚合方式、
            误差表示和样本数。
            """
        ),
    ),
)


def _choose_seed_user_id(database: Any) -> str:
    configured = os.getenv("SCIPILOT_SEED_USER_ID", "").strip()
    if configured:
        try:
            user_id = str(UUID(configured))
        except ValueError as exc:
            raise RuntimeError("SCIPILOT_SEED_USER_ID 必须是有效 UUID") from exc
        result = (
            database.table("profiles")
            .select("id")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if not (result.data or []):
            raise RuntimeError("SCIPILOT_SEED_USER_ID 在 profiles 中不存在")
        return user_id

    result = database.table("profiles").select("id", count="exact").limit(2).execute()
    rows = result.data or []
    count = result.count if result.count is not None else len(rows)
    if count != 1 or len(rows) != 1:
        raise RuntimeError(
            "未设置 SCIPILOT_SEED_USER_ID，且 profiles 不是恰好 1 条；"
            "请在 backend/.env 中显式设置种子内容的归属用户 UUID"
        )
    return str(rows[0]["id"])


def _collection_metadata() -> dict[str, Any]:
    return {
        "system_managed": True,
        "seed_key": "scipilot-software-engineering-public-starter",
        "seed_version": SEED_VERSION,
        "content_policy": CONTENT_POLICY,
        "agent_categories": [
            "paper-reading",
            "problem-decomposition",
            "project-planning",
            "code-reproduction",
            "result-interpretation",
        ],
        "topics": [
            "software-engineering",
            "research-reading",
            "requirements",
            "project-planning",
            "reproducibility",
            "testing",
            "result-analysis",
        ],
    }


def _get_or_create_collection(database: Any, user_id: str) -> dict[str, Any]:
    result = (
        database.table("kb_collections")
        .select("*")
        .eq("user_id", user_id)
        .eq("name", COLLECTION_NAME)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    embedding_model = (
        os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        if os.getenv("EMBEDDING_API_KEY", "").strip()
        else None
    )
    payload = {
        "name": COLLECTION_NAME,
        "description": (
            "面向 SciPilot 五类子智能体的公开软件工程入门知识：官方书目信息、"
            "原创中文摘要、复现清单、项目规划、测试与结果分析。"
        ),
        "is_public": True,
        "embedding_model": embedding_model,
        "embedding_dimensions": 1536,
        "metadata": _collection_metadata(),
    }
    if rows:
        current = rows[0]
        payload["metadata"] = {
            **(current.get("metadata") or {}),
            **_collection_metadata(),
        }
        updated = (
            database.table("kb_collections")
            .update(payload)
            .eq("id", current["id"])
            .eq("user_id", user_id)
            .execute()
        )
        return (updated.data or [current])[0]

    created = (
        database.table("kb_collections")
        .insert({"user_id": user_id, **payload})
        .execute()
    )
    if not (created.data or []):
        raise RuntimeError("创建知识库集合失败：Supabase 未返回集合记录")
    return created.data[0]


def _document_metadata(entry: SeedEntry) -> dict[str, Any]:
    official_sources = list(dict.fromkeys((entry.source_url, *entry.official_sources)))
    return {
        "system_managed": True,
        "seed_key": entry.seed_key,
        "seed_version": SEED_VERSION,
        "content_origin": "scipilot-original-chinese-summary",
        "content_policy": CONTENT_POLICY,
        "source_url": entry.source_url,
        "official_sources": official_sources,
        "license_scope": entry.license_scope,
        "topics": list(entry.topics),
        "agent_categories": list(entry.agent_categories),
    }


def _delete_document(database: Any, document_id: str, user_id: str) -> None:
    database.table("kb_documents").delete().eq("id", document_id).eq(
        "user_id", user_id
    ).execute()


def _seed_document(
    database: Any,
    *,
    entry: SeedEntry,
    collection_id: str,
    user_id: str,
    existing_rows: list[dict[str, Any]],
) -> tuple[str, int, int]:
    text = entry.content.strip()
    checksum = sha256_bytes(text.encode("utf-8"))
    metadata = _document_metadata(entry)
    candidates = [
        row
        for row in existing_rows
        if row.get("checksum") == checksum
        or (row.get("metadata") or {}).get("seed_key") == entry.seed_key
    ]
    reusable = next(
        (
            row
            for row in candidates
            if row.get("checksum") == checksum
            and row.get("status") == "ready"
            and int(row.get("chunk_count") or 0) > 0
        ),
        None,
    )
    if reusable:
        merged_metadata = {**(reusable.get("metadata") or {}), **metadata}
        database.table("kb_documents").update(
            {
                "title": entry.title,
                "source_type": entry.source_type,
                "source_url": entry.source_url,
                "language": "zh-CN",
                "character_count": len(text),
                "metadata": merged_metadata,
            }
        ).eq("id", reusable["id"]).eq("user_id", user_id).execute()
        for row in candidates:
            if row["id"] != reusable["id"]:
                _delete_document(database, row["id"], user_id)
        return "reused", int(reusable.get("chunk_count") or 0), int(
            (reusable.get("metadata") or {}).get("embedded_chunks") or 0
        )

    replaced = bool(candidates)
    for row in candidates:
        _delete_document(database, row["id"], user_id)

    chunks = chunk_knowledge_text(text)
    if not chunks:
        raise RuntimeError(f"知识条目无法分块：{entry.seed_key}")

    created = (
        database.table("kb_documents")
        .insert(
            {
                "collection_id": collection_id,
                "user_id": user_id,
                "title": entry.title,
                "source_type": entry.source_type,
                "source_url": entry.source_url,
                "checksum": checksum,
                "language": "zh-CN",
                "status": "processing",
                "character_count": len(text),
                "metadata": metadata,
            }
        )
        .execute()
    )
    if not (created.data or []):
        raise RuntimeError(f"创建知识文档失败：{entry.seed_key}")
    document_id = str(created.data[0]["id"])

    embedded_chunks = 0
    embedding_failed = False
    try:
        chunk_rows: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks):
            embedding = None
            if not embedding_failed:
                try:
                    embedding = create_embedding(chunk)
                except Exception:
                    # Full-text retrieval remains functional. Avoid repeatedly
                    # calling a misconfigured provider for the remaining chunks.
                    embedding_failed = True
            if embedding is not None:
                embedded_chunks += 1
            chunk_rows.append(
                {
                    "document_id": document_id,
                    "collection_id": collection_id,
                    "user_id": user_id,
                    "chunk_index": index,
                    "title": entry.title,
                    "content": chunk,
                    "token_count": estimate_tokens(chunk),
                    "embedding": embedding,
                    "metadata": {
                        "system_managed": True,
                        "seed_key": entry.seed_key,
                        "source_url": entry.source_url,
                        "license_scope": entry.license_scope,
                        "topics": list(entry.topics),
                        "agent_categories": list(entry.agent_categories),
                    },
                }
            )
        for start in range(0, len(chunk_rows), 50):
            database.table("kb_chunks").insert(chunk_rows[start : start + 50]).execute()

        completed_metadata = {
            **metadata,
            "embedded_chunks": embedded_chunks,
            "retrieval": "hybrid" if embedded_chunks else "full-text",
        }
        database.table("kb_documents").update(
            {
                "status": "ready",
                "chunk_count": len(chunk_rows),
                "error_message": None,
                "metadata": completed_metadata,
            }
        ).eq("id", document_id).eq("user_id", user_id).execute()
    except Exception:
        # Cascading deletion also removes partial chunks, so a retry starts clean.
        _delete_document(database, document_id, user_id)
        raise

    return ("replaced" if replaced else "created"), len(chunks), embedded_chunks


def main() -> None:
    database = get_supabase_client()
    user_id = _choose_seed_user_id(database)
    collection = _get_or_create_collection(database, user_id)
    collection_id = str(collection["id"])
    existing = (
        database.table("kb_documents")
        .select("id,checksum,status,chunk_count,metadata")
        .eq("collection_id", collection_id)
        .eq("user_id", user_id)
        .execute()
    )
    existing_rows = existing.data or []

    summary = {"created": 0, "replaced": 0, "reused": 0, "chunks": 0, "embedded": 0}
    for entry in SEEDS:
        action, chunk_count, embedded_count = _seed_document(
            database,
            entry=entry,
            collection_id=collection_id,
            user_id=user_id,
            existing_rows=existing_rows,
        )
        summary[action] += 1
        summary["chunks"] += chunk_count
        summary["embedded"] += embedded_count
        print(f"[{action:8}] {entry.title} ({chunk_count} chunks)")

    print(
        "完成："
        f"{len(SEEDS)} 条原创知识；新建 {summary['created']}，替换 {summary['replaced']}，"
        f"复用 {summary['reused']}；共 {summary['chunks']} 个分块，"
        f"{summary['embedded']} 个带向量。集合为 public/system_managed。"
    )


if __name__ == "__main__":
    main()
