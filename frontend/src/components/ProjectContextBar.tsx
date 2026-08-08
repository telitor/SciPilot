import { useEffect, useMemo, useState } from 'react';
import { FolderKanban, Loader2, Settings2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { projectAPI } from '@/services/api';
import { useAuthStore } from '@/store/authStore';
import { useProjectStore } from '@/store/projectStore';
import type { ResearchProject } from '@/types';

interface ProjectContextBarProps {
  className?: string;
}

export default function ProjectContextBar({ className = '' }: ProjectContextBarProps) {
  const navigate = useNavigate();
  const userId = useAuthStore((state) => state.user?.id || 'anonymous');
  const selectedProjectId = useProjectStore(
    (state) => state.selectedProjectByUser[userId] || null,
  );
  const setSelectedProject = useProjectStore((state) => state.setSelectedProject);
  const [projects, setProjects] = useState<ResearchProject[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    projectAPI.getProjects()
      .then((response) => {
        if (!active) return;
        const items = Array.isArray(response.data.items) ? response.data.items : [];
        setProjects(items);
        if (selectedProjectId && !items.some((project) => project.id === selectedProjectId)) {
          setSelectedProject(userId, null);
        }
      })
      .catch(() => {
        if (active) setProjects([]);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selectedProjectId, setSelectedProject, userId]);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) || null,
    [projects, selectedProjectId],
  );

  return (
    <div className={`flex flex-col gap-3 border-y border-sci-border py-3 sm:flex-row sm:items-center ${className}`}>
      <div className="flex min-w-0 items-center gap-2">
        <FolderKanban size={17} className="text-sci-accent" />
        <div className="min-w-0">
          <p className="text-xs text-sci-muted">当前科研项目</p>
          <p className="truncate text-sm font-medium">
            {selectedProject?.name || '未选择，新增内容将保持未归属'}
          </p>
        </div>
      </div>

      <div className="flex flex-1 items-center gap-2 sm:justify-end">
        <div className="relative min-w-0 flex-1 sm:max-w-xs">
          <select
            value={selectedProjectId || ''}
            onChange={(event) => setSelectedProject(userId, event.target.value || null)}
            disabled={loading}
            className="sci-input w-full appearance-none pr-9 text-sm"
            aria-label="选择当前科研项目"
          >
            <option value="">未选择项目</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
          {loading && (
            <Loader2 size={15} className="absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-sci-muted" />
          )}
        </div>
        <button
          type="button"
          onClick={() => navigate('/projects')}
          className="sci-btn-secondary shrink-0"
          title="管理科研项目"
        >
          <Settings2 size={16} />
          <span className="hidden sm:inline">管理</span>
        </button>
      </div>
    </div>
  );
}
