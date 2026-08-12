import { lazy, Suspense } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuthStore } from '@/store/authStore';
import AppLayout from '@/app/layout';
import Home from '@/pages/Home';
import Login from '@/pages/Login';
import Register from '@/pages/Register';
import ForgotPassword from '@/pages/ForgotPassword';
import ResetPassword from '@/pages/ResetPassword';
import NotificationContainer from '@/components/NotificationContainer';
import AuthBootstrap from '@/components/AuthBootstrap';

const Dashboard = lazy(() => import('@/pages/Dashboard'));
const PaperRead = lazy(() => import('@/pages/PaperRead'));
const PaperLibrary = lazy(() => import('@/pages/PaperLibrary'));
const ResearchDecompose = lazy(() => import('@/pages/ResearchDecompose'));
const ExperimentRoadmap = lazy(() => import('@/pages/ExperimentRoadmap'));
const CodeReproduce = lazy(() => import('@/pages/CodeReproduce'));
const ResultAnalyze = lazy(() => import('@/pages/ResultAnalyze'));
const KnowledgeBase = lazy(() => import('@/pages/KnowledgeBase'));
const KnowledgeGraph = lazy(() => import('@/pages/KnowledgeGraph'));
const Profile = lazy(() => import('@/pages/Profile'));
const Projects = lazy(() => import('@/pages/Projects'));

function WorkspaceLoading() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center text-sm text-sci-muted" role="status">
      正在打开科研工作台…
    </div>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return isAuthenticated ? <>{children}</> : <Navigate to="/login" replace />;
}

function App() {
  return (
    <AuthBootstrap>
      <Suspense fallback={<WorkspaceLoading />}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route element={<AppLayout />}>
            <Route path="/dashboard" element={<RequireAuth><Dashboard /></RequireAuth>} />
            <Route path="/projects" element={<RequireAuth><Projects /></RequireAuth>} />
            <Route path="/paper/read" element={<RequireAuth><PaperRead /></RequireAuth>} />
            <Route path="/paper/library" element={<RequireAuth><PaperLibrary /></RequireAuth>} />
            <Route path="/research/decompose" element={<RequireAuth><ResearchDecompose /></RequireAuth>} />
            <Route path="/experiment/roadmap" element={<RequireAuth><ExperimentRoadmap /></RequireAuth>} />
            <Route path="/code/reproduce" element={<RequireAuth><CodeReproduce /></RequireAuth>} />
            <Route path="/result/analyze" element={<RequireAuth><ResultAnalyze /></RequireAuth>} />
            <Route path="/knowledge" element={<RequireAuth><KnowledgeBase /></RequireAuth>} />
            <Route path="/kg/explore" element={<RequireAuth><KnowledgeGraph /></RequireAuth>} />
            <Route path="/profile" element={<RequireAuth><Profile /></RequireAuth>} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
      <NotificationContainer />
    </AuthBootstrap>
  );
}

export default App;
