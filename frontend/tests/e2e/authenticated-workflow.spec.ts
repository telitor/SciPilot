import { expect, test, type Page, type Route } from '@playwright/test';

const user = {
  id: 'user-e2e',
  email: 'researcher@example.com',
  username: 'E2E Researcher',
  role: 'user',
  created_at: '2026-08-13T00:00:00Z',
};

const project = {
  id: 'project-e2e',
  user_id: user.id,
  name: '可验证科研闭环',
  objective: '验证从项目到科研产物的稳定链路',
  status: 'active',
  current_stage: 'discovery',
  created_at: '2026-08-13T00:00:00Z',
  updated_at: '2026-08-13T00:00:00Z',
};

const emptyAssets = {
  papers: [],
  conversations: [],
  artifacts: [],
  counts: { papers: 0, conversations: 0, artifacts: 0 },
};

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

async function seedAuthenticatedSession(page: Page, selectedProject = false) {
  await page.addInitScript(({ sessionUser, activeProject }) => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    window.localStorage.setItem('scipilot-auth', JSON.stringify({
      state: {
        user: sessionUser,
        token: 'controlled-e2e-token',
        isAuthenticated: true,
        rememberSession: true,
      },
      version: 0,
    }));
    window.localStorage.setItem('scipilot-project-context', JSON.stringify({
      state: {
        selectedProjectByUser: activeProject
          ? { [sessionUser.id]: activeProject }
          : {},
      },
      version: 0,
    }));
  }, { sessionUser: user, activeProject: selectedProject ? project.id : null });
}

async function mockSharedApi(page: Page) {
  await page.route('**/api/v1/users/me', (route) => json(route, user));
  await page.route('**/api/v1/projects?**', (route) => json(route, {
    items: [project],
    total: 1,
  }));
  await page.route('**/api/v1/projects', (route) => json(route, {
    items: [project],
    total: 1,
  }));
  await page.route('**/api/v1/projects/unassigned-assets', (route) => json(route, emptyAssets));
  await page.route(`**/api/v1/projects/${project.id}`, (route) => json(route, {
    ...project,
    assets: {
      papers: [],
      conversations: [],
      artifacts: [],
    },
    counts: emptyAssets.counts,
    recent_activities: [],
  }));
  await page.route('**/api/v1/agents', (route) => json(route, {
    items: [{
      id: 'agent-problem',
      name: '问题拆解助手',
      category: 'problem-decomposition',
      is_public: true,
    }],
    total: 1,
  }));
}

test('authenticated researcher selects a project and enters the paper workflow', async ({ page }) => {
  await seedAuthenticatedSession(page);
  await mockSharedApi(page);

  await page.goto('/projects');

  await expect(page.getByRole('heading', { name: '科研项目' })).toBeVisible();
  await expect(page.getByText(project.name)).toBeVisible();
  await page.getByRole('button', { name: /打开/ }).click();
  await expect(page.getByText('当前项目', { exact: true })).toBeVisible();
  await expect(page.getByText(project.name).last()).toBeVisible();
  await page.getByRole('button', { name: /上传并精读论文/ }).click();
  await expect(page).toHaveURL(/\/paper\/read$/);
});

test('problem decomposition submits a durable job and renders its artifact', async ({ page }) => {
  await seedAuthenticatedSession(page, true);
  await mockSharedApi(page);

  let submittedBody: Record<string, unknown> | undefined;
  await page.route('**/api/v1/jobs?**', (route) => json(route, { items: [] }));
  await page.route('**/api/v1/research/decompose-async', async (route) => {
    submittedBody = route.request().postDataJSON();
    await json(route, {
      id: 'job-e2e',
      project_id: project.id,
      job_type: 'research-decomposition',
      status: 'pending',
      progress: 0,
      attempts: 0,
      max_attempts: 2,
      created_at: '2026-08-13T00:00:00Z',
      updated_at: '2026-08-13T00:00:00Z',
    }, 202);
  });
  await page.route('**/api/v1/jobs/job-e2e', (route) => json(route, {
    id: 'job-e2e',
    project_id: project.id,
    job_type: 'research-decomposition',
    status: 'succeeded',
    progress: 100,
    attempts: 1,
    max_attempts: 2,
    created_at: '2026-08-13T00:00:00Z',
    updated_at: '2026-08-13T00:00:01Z',
    completed_at: '2026-08-13T00:00:01Z',
    result: {
      id: 'artifact-e2e',
      project_id: project.id,
      core_question: '如何构建可验证的软件缺陷预测方法？',
      sub_questions: [{
        id: 'question-e2e',
        question: '如何控制跨项目数据分布差异？',
        feasibility: 'high',
        datasets: ['PROMISE'],
        papers: ['Cross-project defect prediction'],
        children: [],
      }],
      review_status: 'draft',
      version: 1,
      generation_mode: 'agent',
      created_at: '2026-08-13T00:00:01Z',
      updated_at: '2026-08-13T00:00:01Z',
    },
  }));

  await page.goto('/research/decompose');
  await page.getByPlaceholder(/基于深度学习/).fill('软件缺陷预测的跨项目泛化');
  await page.getByRole('button', { name: /开始拆解/ }).click();

  await expect.poll(() => submittedBody).toEqual({
    direction: '软件缺陷预测的跨项目泛化',
    project_id: project.id,
  });
  await expect(page.getByText('如何构建可验证的软件缺陷预测方法？')).toBeVisible();
  await expect(page.getByText('如何控制跨项目数据分布差异？')).toBeVisible();
});
