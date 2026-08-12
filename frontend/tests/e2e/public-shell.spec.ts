import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });
});

test('public home presents the SciPilot research workflow', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByRole('heading', { name: /把研究/ })).toBeVisible();
  await expect(page.getByText('五个模块，顺着研究自然推进。')).toBeVisible();
  await expect(page.getByRole('button', { name: '登录', exact: true }).first()).toBeVisible();
});

test('login form exposes the real account entry points', async ({ page }) => {
  await page.goto('/login');

  await expect(page.getByRole('heading', { name: '登录 SciCopilot' })).toBeVisible();
  await expect(page.getByLabel('邮箱')).toBeEditable();
  await expect(page.getByLabel('密码', { exact: true })).toBeEditable();
  await expect(page.getByRole('link', { name: '忘记密码' })).toHaveAttribute('href', '/forgot-password');
  await expect(page.getByRole('link', { name: '立即注册' })).toHaveAttribute('href', '/register');
});

test('protected workspace redirects anonymous visitors to login', async ({ page }) => {
  await page.goto('/projects');

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole('heading', { name: '登录 SciCopilot' })).toBeVisible();
});
