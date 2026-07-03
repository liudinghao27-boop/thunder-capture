async page => {
    const assert = (condition, message) => {
        if (!condition) throw new Error(message);
    };

    await page.reload();
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.waitForTimeout(1000);

    assert(await page.locator('link[href="/static/css/tailwind.css"]').count() === 1, 'Local Tailwind CSS is not loaded');

    // Overview primary CTA and title
    await page.locator('[data-nav="overview"]').click();
    await page.waitForTimeout(200);
    assert(await page.locator('#overview-primary-action').count() === 1, 'Overview primary CTA is missing');
    assert((await page.locator('#current-view-title').innerText()) === '首页总览', 'Overview title did not update');

    await page.locator('[data-nav="industries"]').click();
    await page.getByRole('button', { name: '新建获客项目', exact: true }).click();
    const modal = page.locator('#modal-industry');
    assert(await modal.isVisible(), 'Project modal did not open');
    const desktopCancel = await modal.getByText('取消', { exact: true }).boundingBox();
    const desktopSave = await modal.getByText('确认保存', { exact: true }).boundingBox();
    assert(desktopCancel && desktopCancel.y + desktopCancel.height <= 900, 'Desktop cancel button is outside the viewport');
    assert(desktopSave && desktopSave.y + desktopSave.height <= 900, 'Desktop save button is outside the viewport');
    await page.screenshot({ path: '.playwright-cli/desktop-project-modal.png' });
    await modal.getByText('取消', { exact: true }).click();

    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(250);
    const mainBefore = await page.locator('main').boundingBox();
    const sidebarBefore = await page.locator('#dashboard-sidebar').boundingBox();
    assert(mainBefore && mainBefore.width === 390, 'Mobile main pane is not full width');
    assert(sidebarBefore && sidebarBefore.x <= -250, 'Mobile sidebar is not closed by default');

    await page.locator('#btn-sidebar-open').click();
    await page.waitForTimeout(250);
    const sidebarOpen = await page.locator('#dashboard-sidebar').boundingBox();
    assert(sidebarOpen && sidebarOpen.x === 0, 'Mobile sidebar did not open');
    await page.screenshot({ path: '.playwright-cli/mobile-dashboard-drawer.png' });

    const views = [];
    for (const nav of ['devices', 'tasks', 'jobs', 'settings', 'industries']) {
        await page.locator(`[data-nav="${nav}"]`).click();
        await page.waitForTimeout(300);
        const mainBox = await page.locator('main').boundingBox();
        const backdropHidden = await page.locator('#dashboard-sidebar-backdrop').evaluate(el => el.classList.contains('hidden'));
        assert(mainBox && mainBox.width === 390, `${nav}: main pane lost mobile width`);
        assert(backdropHidden, `${nav}: sidebar did not close after navigation`);
        views.push({ nav, title: await page.locator('#current-view-title').innerText() });
        await page.locator('#btn-sidebar-open').click();
        await page.waitForTimeout(100);
    }
    await page.locator('[data-nav="overview"]').click();

    await page.locator('#btn-sidebar-open').click();
    await page.locator('[data-nav="industries"]').click();
    await page.getByRole('button', { name: '新建获客项目', exact: true }).click();
    const mobileCancel = await modal.getByText('取消', { exact: true }).boundingBox();
    const mobileSave = await modal.getByText('确认保存', { exact: true }).boundingBox();
    assert(mobileCancel && mobileCancel.y + mobileCancel.height <= 844, 'Mobile cancel button is outside the viewport');
    assert(mobileSave && mobileSave.y + mobileSave.height <= 844, 'Mobile save button is outside the viewport');
    await page.screenshot({ path: '.playwright-cli/mobile-project-modal.png' });
    await modal.getByText('取消', { exact: true }).click();

    return { desktopModal: true, mobileMainWidth: mainBefore.width, views };
}
