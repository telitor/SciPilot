-- =============================================================================
-- Verified public research catalog and starter knowledge graph.
--
-- Only bibliographic/project metadata and links are stored here. This migration
-- does not copy papers, source code, or datasets into SciPilot.
--
-- Primary sources checked before adding this seed:
--   https://arxiv.org/abs/1706.03762
--   https://arxiv.org/abs/1810.04805
--   https://arxiv.org/abs/2009.08366
--   https://arxiv.org/abs/1909.09436
--   https://arxiv.org/abs/2002.08155
--   https://github.com/github/CodeSearchNet
--   https://github.com/microsoft/CodeBERT
--   https://github.com/rjust/defects4j
--   https://github.com/SWE-bench/SWE-bench
--   https://arxiv.org/abs/2310.06770
--
-- All writes use stable slugs and UPSERT, so this migration is idempotent.
-- =============================================================================

insert into public.catalog_resources (
  slug,
  resource_type,
  title,
  description,
  authors,
  publication_year,
  source_name,
  url,
  external_id,
  arxiv_id,
  doi,
  repository_url,
  license,
  topics,
  metadata,
  is_featured,
  is_public
)
values
  (
    'attention-is-all-you-need',
    'paper',
    'Attention Is All You Need',
    '提出完全基于注意力机制的 Transformer 架构，是现代语言模型与代码模型的重要基础。',
    array[
      'Ashish Vaswani',
      'Noam Shazeer',
      'Niki Parmar',
      'Jakob Uszkoreit',
      'Llion Jones',
      'Aidan N. Gomez',
      'Lukasz Kaiser',
      'Illia Polosukhin'
    ]::text[],
    2017,
    'arXiv',
    'https://arxiv.org/abs/1706.03762',
    'arxiv:1706.03762',
    '1706.03762',
    '10.48550/arXiv.1706.03762',
    null,
    null,
    array['transformer', 'attention', 'machine-learning', 'nlp']::text[],
    '{"primary_category":"cs.CL"}'::jsonb,
    true,
    true
  ),
  (
    'bert',
    'paper',
    'BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding',
    '提出 BERT 双向预训练语言表示，并展示预训练模型通过微调适配多种自然语言理解任务。',
    array[
      'Jacob Devlin',
      'Ming-Wei Chang',
      'Kenton Lee',
      'Kristina Toutanova'
    ]::text[],
    2018,
    'arXiv',
    'https://arxiv.org/abs/1810.04805',
    'arxiv:1810.04805',
    '1810.04805',
    '10.48550/arXiv.1810.04805',
    null,
    null,
    array['bert', 'transformer', 'pretraining', 'nlp']::text[],
    '{"primary_category":"cs.CL"}'::jsonb,
    true,
    true
  ),
  (
    'graphcodebert',
    'paper',
    'GraphCodeBERT: Pre-training Code Representations with Data Flow',
    '将代码数据流结构纳入预训练，在代码搜索、克隆检测、翻译和代码修复等任务上进行评估。',
    array[
      'Daya Guo',
      'Shuo Ren',
      'Shuai Lu',
      'Zhangyin Feng',
      'Duyu Tang',
      'Shujie Liu',
      'Long Zhou',
      'Nan Duan',
      'Alexey Svyatkovskiy',
      'Shengyu Fu',
      'Michele Tufano',
      'Shao Kun Deng',
      'Colin Clement',
      'Dawn Drain',
      'Neel Sundaresan',
      'Jian Yin',
      'Daxin Jiang',
      'Ming Zhou'
    ]::text[],
    2020,
    'arXiv',
    'https://arxiv.org/abs/2009.08366',
    'arxiv:2009.08366',
    '2009.08366',
    '10.48550/arXiv.2009.08366',
    'https://github.com/microsoft/CodeBERT/tree/master/GraphCodeBERT',
    null,
    array[
      'graphcodebert',
      'code-representation',
      'data-flow',
      'code-search',
      'clone-detection'
    ]::text[],
    '{"venue":"ICLR 2021","primary_category":"cs.SE"}'::jsonb,
    true,
    true
  ),
  (
    'codesearchnet',
    'dataset',
    'CodeSearchNet Challenge',
    '面向自然语言代码检索的公开数据、基线与评测资源；官方仓库说明主数据包含六种编程语言。',
    array[
      'Hamel Husain',
      'Ho-Hsiang Wu',
      'Tiferet Gazit',
      'Miltiadis Allamanis',
      'Marc Brockschmidt'
    ]::text[],
    2019,
    'GitHub',
    'https://github.com/github/CodeSearchNet',
    'arxiv:1909.09436',
    '1909.09436',
    '10.48550/arXiv.1909.09436',
    'https://github.com/github/CodeSearchNet',
    null,
    array[
      'dataset',
      'semantic-code-search',
      'code-representation',
      'python',
      'java',
      'javascript',
      'php',
      'ruby',
      'go'
    ]::text[],
    '{
      "paper_url":"https://arxiv.org/abs/1909.09436",
      "license_note":"Repository code is MIT licensed; dataset files retain the licenses of their source repositories."
    }'::jsonb,
    true,
    true
  ),
  (
    'microsoft-codebert',
    'repository',
    'Microsoft CodeBERT',
    '微软维护的代码预训练模型仓库，包含 CodeBERT、GraphCodeBERT 及相关复现实验代码。',
    array[
      'Zhangyin Feng',
      'Daya Guo',
      'Duyu Tang',
      'Nan Duan',
      'Xiaocheng Feng',
      'Ming Gong',
      'Linjun Shou',
      'Bing Qin',
      'Ting Liu',
      'Daxin Jiang',
      'Ming Zhou'
    ]::text[],
    2020,
    'Microsoft GitHub',
    'https://github.com/microsoft/CodeBERT',
    'github:microsoft/CodeBERT',
    '2002.08155',
    '10.48550/arXiv.2002.08155',
    'https://github.com/microsoft/CodeBERT',
    'MIT',
    array[
      'codebert',
      'graphcodebert',
      'code-representation',
      'pretraining',
      'reproduction'
    ]::text[],
    '{
      "paper_title":"CodeBERT: A Pre-Trained Model for Programming and Natural Languages",
      "paper_url":"https://arxiv.org/abs/2002.08155"
    }'::jsonb,
    true,
    true
  ),
  (
    'defects4j',
    'dataset',
    'Defects4J',
    '真实 Java 缺陷与实验基础设施，可用于软件测试、缺陷定位和自动程序修复研究。',
    array['René Just', 'Darioush Jalali', 'Michael D. Ernst']::text[],
    2014,
    'Defects4J GitHub',
    'https://github.com/rjust/defects4j',
    'github:rjust/defects4j',
    null,
    '10.1145/2610384.2628055',
    'https://github.com/rjust/defects4j',
    'MIT',
    array[
      'dataset',
      'software-defects',
      'java',
      'testing',
      'fault-localization',
      'program-repair'
    ]::text[],
    '{
      "paper_title":"Defects4J: A Database of Existing Faults to Enable Controlled Testing Studies for Java Programs",
      "venue":"ISSTA 2014",
      "documentation_url":"https://defects4j.org/"
    }'::jsonb,
    true,
    true
  ),
  (
    'swe-bench',
    'benchmark',
    'SWE-bench: Can Language Models Resolve Real-World GitHub Issues?',
    '使用真实 GitHub issue 与代码仓库评测语言模型解决软件工程问题能力的公开基准。',
    array[
      'Carlos E. Jimenez',
      'John Yang',
      'Alexander Wettig',
      'Shunyu Yao',
      'Kexin Pei',
      'Ofir Press',
      'Karthik Narasimhan'
    ]::text[],
    2024,
    'SWE-bench',
    'https://www.swebench.com/',
    'arxiv:2310.06770',
    '2310.06770',
    '10.48550/arXiv.2310.06770',
    'https://github.com/SWE-bench/SWE-bench',
    'MIT',
    array[
      'benchmark',
      'software-engineering',
      'language-model',
      'issue-resolution',
      'program-repair'
    ]::text[],
    '{
      "paper_url":"https://arxiv.org/abs/2310.06770",
      "venue":"ICLR 2024"
    }'::jsonb,
    true,
    true
  )
on conflict (slug) do update
set
  resource_type = excluded.resource_type,
  title = excluded.title,
  description = excluded.description,
  authors = excluded.authors,
  publication_year = excluded.publication_year,
  source_name = excluded.source_name,
  url = excluded.url,
  external_id = excluded.external_id,
  arxiv_id = excluded.arxiv_id,
  doi = excluded.doi,
  repository_url = excluded.repository_url,
  license = excluded.license,
  topics = excluded.topics,
  metadata = excluded.metadata,
  is_featured = excluded.is_featured,
  is_public = excluded.is_public,
  updated_at = now();


-- -----------------------------------------------------------------------------
-- Public nodes. resource_slug is resolved to the catalog row created above.
-- -----------------------------------------------------------------------------

insert into public.knowledge_nodes (
  user_id,
  resource_id,
  slug,
  label,
  category,
  description,
  metadata,
  is_public
)
select
  null::uuid,
  resource.id,
  seed.slug,
  seed.label,
  seed.category,
  seed.description,
  seed.metadata,
  true
from (
  values
    (
      'attention-is-all-you-need',
      'Attention Is All You Need',
      'paper',
      '提出 Transformer 的基础论文。',
      'attention-is-all-you-need',
      '{}'::jsonb
    ),
    (
      'bert',
      'BERT',
      'model',
      '基于 Transformer 编码器的双向预训练语言模型。',
      'bert',
      '{}'::jsonb
    ),
    (
      'graphcodebert',
      'GraphCodeBERT',
      'model',
      '融合代码数据流结构的预训练代码模型。',
      'graphcodebert',
      '{}'::jsonb
    ),
    (
      'codesearchnet',
      'CodeSearchNet',
      'dataset',
      '自然语言代码检索数据集与评测资源。',
      'codesearchnet',
      '{}'::jsonb
    ),
    (
      'codebert',
      'CodeBERT',
      'model',
      '面向自然语言和多种编程语言的预训练模型。',
      'microsoft-codebert',
      '{}'::jsonb
    ),
    (
      'defects4j',
      'Defects4J',
      'dataset',
      '真实 Java 缺陷数据与可复现实验基础设施。',
      'defects4j',
      '{}'::jsonb
    ),
    (
      'swe-bench',
      'SWE-bench',
      'benchmark',
      '真实 GitHub issue 解决能力基准。',
      'swe-bench',
      '{}'::jsonb
    ),
    (
      'transformer',
      'Transformer',
      'technique',
      '以自注意力为核心的序列建模架构。',
      null,
      '{}'::jsonb
    ),
    (
      'bidirectional-pretraining',
      'Bidirectional Pre-training',
      'technique',
      '同时利用左右上下文进行表示学习的预训练方式。',
      null,
      '{}'::jsonb
    ),
    (
      'code-representation-learning',
      'Code Representation Learning',
      'research-topic',
      '学习可供检索、分类、生成和分析任务使用的代码表示。',
      null,
      '{}'::jsonb
    ),
    (
      'data-flow',
      'Data Flow',
      'program-analysis',
      '描述程序值如何在变量与操作之间传播的结构信息。',
      null,
      '{}'::jsonb
    ),
    (
      'semantic-code-search',
      'Semantic Code Search',
      'research-topic',
      '使用自然语言语义检索相关代码。',
      null,
      '{}'::jsonb
    ),
    (
      'software-defect',
      'Software Defect',
      'research-topic',
      '软件中的真实故障及其检测、定位与修复。',
      null,
      '{}'::jsonb
    ),
    (
      'issue-resolution',
      'Issue Resolution',
      'research-topic',
      '依据问题描述理解代码库并生成可验证修复。',
      null,
      '{}'::jsonb
    ),
    (
      'software-engineering-benchmark',
      'Software Engineering Benchmark',
      'research-topic',
      '用于可重复比较软件工程方法的任务、数据与评测规范。',
      null,
      '{}'::jsonb
    )
) as seed (
  slug,
  label,
  category,
  description,
  resource_slug,
  metadata
)
left join public.catalog_resources as resource
  on resource.slug = seed.resource_slug
on conflict (slug) where user_id is null do update
set
  resource_id = excluded.resource_id,
  label = excluded.label,
  category = excluded.category,
  description = excluded.description,
  metadata = excluded.metadata,
  is_public = excluded.is_public,
  updated_at = now();


-- -----------------------------------------------------------------------------
-- Public edges. Each edge names the source used to justify the relationship.
-- -----------------------------------------------------------------------------

with edge_seed (
  source_slug,
  target_slug,
  relation,
  strength,
  evidence,
  resource_slug,
  metadata
) as (
  values
    (
      'attention-is-all-you-need',
      'transformer',
      'introduces',
      1.000::numeric,
      'The paper introduces an architecture based solely on attention mechanisms.',
      'attention-is-all-you-need',
      '{}'::jsonb
    ),
    (
      'bert',
      'transformer',
      'builds_on',
      0.950::numeric,
      'BERT uses a multi-layer bidirectional Transformer encoder.',
      'bert',
      '{}'::jsonb
    ),
    (
      'bert',
      'bidirectional-pretraining',
      'uses',
      1.000::numeric,
      'BERT pre-trains deep bidirectional representations from unlabeled text.',
      'bert',
      '{}'::jsonb
    ),
    (
      'codebert',
      'bert',
      'adapts_architecture',
      0.850::numeric,
      'CodeBERT is a Transformer-based pre-trained model for natural and programming languages.',
      'microsoft-codebert',
      '{}'::jsonb
    ),
    (
      'codebert',
      'code-representation-learning',
      'supports',
      1.000::numeric,
      'The official repository provides CodeBERT for programming-language representation tasks.',
      'microsoft-codebert',
      '{}'::jsonb
    ),
    (
      'codebert',
      'codesearchnet',
      'uses_dataset',
      0.900::numeric,
      'CodeBERT pre-training uses natural-language/programming-language pairs from CodeSearchNet.',
      'microsoft-codebert',
      '{}'::jsonb
    ),
    (
      'graphcodebert',
      'codebert',
      'extends',
      0.950::numeric,
      'GraphCodeBERT extends pre-trained code representations with structural information.',
      'graphcodebert',
      '{}'::jsonb
    ),
    (
      'graphcodebert',
      'data-flow',
      'incorporates',
      1.000::numeric,
      'GraphCodeBERT explicitly incorporates data flow during pre-training.',
      'graphcodebert',
      '{}'::jsonb
    ),
    (
      'graphcodebert',
      'code-representation-learning',
      'supports',
      1.000::numeric,
      'GraphCodeBERT evaluates learned code representations on several downstream tasks.',
      'graphcodebert',
      '{}'::jsonb
    ),
    (
      'codesearchnet',
      'semantic-code-search',
      'benchmarks',
      1.000::numeric,
      'CodeSearchNet provides data, baselines, and evaluation for semantic code search.',
      'codesearchnet',
      '{}'::jsonb
    ),
    (
      'defects4j',
      'software-defect',
      'contains_examples_of',
      1.000::numeric,
      'Defects4J curates reproducible real faults from open-source Java projects.',
      'defects4j',
      '{}'::jsonb
    ),
    (
      'defects4j',
      'software-engineering-benchmark',
      'supports',
      0.950::numeric,
      'Defects4J provides controlled and reproducible software-engineering experiments.',
      'defects4j',
      '{}'::jsonb
    ),
    (
      'swe-bench',
      'issue-resolution',
      'benchmarks',
      1.000::numeric,
      'SWE-bench evaluates patches for real-world GitHub issues.',
      'swe-bench',
      '{}'::jsonb
    ),
    (
      'swe-bench',
      'software-engineering-benchmark',
      'is_a',
      1.000::numeric,
      'SWE-bench is an evaluation benchmark for real-world software-engineering tasks.',
      'swe-bench',
      '{}'::jsonb
    )
)
insert into public.knowledge_edges (
  user_id,
  source_node_id,
  target_node_id,
  resource_id,
  relation,
  strength,
  evidence,
  metadata,
  is_public
)
select
  null::uuid,
  source_node.id,
  target_node.id,
  resource.id,
  edge_seed.relation,
  edge_seed.strength,
  edge_seed.evidence,
  edge_seed.metadata,
  true
from edge_seed
join public.knowledge_nodes as source_node
  on source_node.slug = edge_seed.source_slug
 and source_node.user_id is null
join public.knowledge_nodes as target_node
  on target_node.slug = edge_seed.target_slug
 and target_node.user_id is null
left join public.catalog_resources as resource
  on resource.slug = edge_seed.resource_slug
on conflict (source_node_id, target_node_id, relation)
where user_id is null
do update
set
  resource_id = excluded.resource_id,
  strength = excluded.strength,
  evidence = excluded.evidence,
  metadata = excluded.metadata,
  is_public = excluded.is_public,
  updated_at = now();
