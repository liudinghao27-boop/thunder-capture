(function (window) {
    'use strict';

    function resolveOverviewPrimaryAction(context) {
        if (!context.hasProject) {
            return { label: '新建获客项目', targetView: 'industries', mode: 'create-industry' };
        }
        if (!context.hasLLM) {
            return { label: '去系统设置', targetView: 'settings', mode: 'settings' };
        }
        if (!context.hasDevice) {
            return { label: '去扫描设备', targetView: 'devices', mode: 'devices' };
        }
        if (!context.hasPending) {
            return { label: '开始采集线索', targetView: 'industries', mode: 'collect' };
        }
        if (context.isWorking) {
            return { label: '查看执行记录', targetView: 'jobs', mode: 'jobs' };
        }
        return { label: '开始发送任务', targetView: 'jobs', mode: 'send' };
    }

    function overviewStageItems(context) {
        return [
            { key: 'project', label: '项目配置', ready: context.hasProject, summary: context.projectSummary },
            { key: 'devices', label: '设备接入', ready: context.hasDevice, summary: context.deviceSummary },
            { key: 'collect', label: '采集线索', ready: context.hasPending, summary: context.collectSummary },
            { key: 'send', label: '发送任务', ready: context.canSend, summary: context.sendSummary },
        ];
    }

    window.DashboardUi = Object.freeze({
        resolveOverviewPrimaryAction,
        overviewStageItems,
    });
})(window);
