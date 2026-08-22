# Supabase 迁移与只读数据库审计

## 已修复的历史问题

Supabase Preview 在 `c4d3d60` 上报告“远端存在本地目录没有的迁移版本”。仓库此前删除了已经进入历史的 `008_knowledge_base.sql`；当前代码已从删除前的 Git 版本原样恢复该文件。新环境会依次执行 008 和后续用于移除旧知识库的 009，远端迁移历史也不再失去 008 的本地对应项。

已应用的 migration 是不可变审计记录：不要删除、重命名或修改它。任何结构调整都应增加一个更高版本的新 migration。仓库质量门现在也会检查三位版本连续性、所有 `public` 表的 RLS 启用记录，以及 `SECURITY DEFINER` 函数是否固定 `search_path`。

## 远端只读审计

安装并认证 Supabase CLI、在仓库中链接正确项目后运行：

```powershell
python backend/scripts/supabase_remote_audit.py
```

脚本只执行迁移历史对比、远端 schema lint、索引使用率、未使用索引和顺序扫描检查，不会调用 `db push`、`db reset` 或 `migration repair`。官方 CLI 说明见 [migration list](https://supabase.com/docs/reference/cli/supabase-orgs-list#supabase-migration-list)、[db lint](https://supabase.com/docs/reference/cli/supabase-orgs-list#supabase-db-lint) 和 [数据库检查工具](https://supabase.com/docs/guides/database/inspect)。

如果仍有历史差异：

1. 先保存 `supabase migration list --linked` 的完整输出并核对目标项目；
2. 远端已有而本地缺失时，优先从 Git 历史恢复原文件；
3. 只有在数据库实际结构和迁移内容均已人工核对后，才按官方给出的精确版本考虑 `migration repair`；
4. 不要对链接的生产项目运行 reset，也不要为了让检查变绿而伪造 applied/reverted 状态。

远端 Preview 是否转绿需要在这些源码变更推送后由 Supabase GitHub 集成重新验证；本地环境没有项目认证信息时不能替代这一步。
