"""Read-only deployment check for SciPilot's Supabase project."""

from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.supabase_service import get_supabase_client  # noqa: E402


REQUIRED_TABLES = [
    "profiles",
    "agents",
    "conversations",
    "messages",
    "papers",
    "paper_reports",
    "research_artifacts",
    "activities",
    "catalog_resources",
    "knowledge_nodes",
    "knowledge_edges",
    "kb_collections",
    "kb_documents",
    "kb_chunks",
    "kb_ingestion_jobs",
    "kb_retrievals",
    "kb_citations",
]


def main() -> int:
    client = get_supabase_client()
    failed: list[str] = []
    print("SciPilot Supabase read-only deployment check")
    for table in REQUIRED_TABLES:
        try:
            result = client.table(table).select("id", count="exact").limit(1).execute()
            count = result.count if result.count is not None else "available"
            print(f"[OK] table {table}: {count}")
        except Exception:
            failed.append(table)
            print(f"[MISSING] table {table}")

    try:
        buckets = {
            getattr(bucket, "name", None)
            or (bucket.get("name") if isinstance(bucket, dict) else None)
            for bucket in client.storage.list_buckets()
        }
    except Exception:
        buckets = set()
    for bucket in ("papers", "knowledge-base"):
        if bucket in buckets:
            print(f"[OK] private storage bucket visible: {bucket}")
        else:
            failed.append(f"storage:{bucket}")
            print(f"[MISSING] storage bucket: {bucket}")

    if failed:
        print("\nDeployment is incomplete:", ", ".join(failed))
        return 1
    print("\nAll required database objects are reachable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
