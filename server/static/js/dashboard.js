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

    function describeOverviewPrimaryAction(context) {
        var primary = resolveOverviewPrimaryAction(context);
        var descriptions = {
            'create-industry': '先配置平台、关键词和对标账号，后续采集和发送才能启动。',
            settings: '先补齐 LLM Key，意向识别和文案生成才可用。',
            devices: '建议先接入并检查至少 1 台设备，再开始发送任务。',
            collect: '当前没有待发送线索，先做一轮采集填充库存。',
            jobs: '当前已有任务运行中，先查看执行进度和异常状态。',
            send: '线索和设备已具备，可以开始发送任务。',
        };
        var idleClass = 'w-full py-3 bg-slate-700 hover:bg-slate-600 text-slate-200 font-bold font-display text-xs rounded-lg transition-all disabled:opacity-30 disabled:cursor-not-allowed';
        var activeCollectClass = 'w-full py-3 bg-cyan-600 hover:bg-cyan-500 text-white font-bold font-display text-xs rounded-lg transition-all disabled:opacity-30 disabled:cursor-not-allowed';
        var activeSendClass = 'w-full py-3 bg-pink-600 hover:bg-pink-500 text-white font-bold font-display text-xs rounded-lg transition-all disabled:opacity-30 disabled:cursor-not-allowed';

        var buttonClass = idleClass;
        if (primary.mode === 'collect') {
            buttonClass = activeCollectClass;
        } else if (primary.mode === 'send' || primary.mode === 'jobs') {
            buttonClass = activeSendClass;
        }

        return {
            mode: primary.mode,
            label: primary.label,
            targetView: primary.targetView,
            description: descriptions[primary.mode] || '系统会根据当前状态给出最短路径。',
            buttonClass: buttonClass,
        };
    }

    function shouldShowFirstUseHint() {
        return localStorage.getItem('thunder_onboarding_seen') !== 'true';
    }

    function markFirstUseHintSeen() {
        localStorage.setItem('thunder_onboarding_seen', 'true');
    }

    function decorateOverviewForFirstUse(primary) {
        if (!shouldShowFirstUseHint()) return primary;
        return {
            ...primary,
            hint: '首次使用建议按顺序完成：项目配置、设备接入、采集线索、发送任务。',
        };
    }

    window.DashboardUi = Object.freeze({
        describeOverviewPrimaryAction: describeOverviewPrimaryAction,
        overviewStageItems: overviewStageItems,
        resolveOverviewPrimaryAction: resolveOverviewPrimaryAction,
        shouldShowFirstUseHint: shouldShowFirstUseHint,
        markFirstUseHintSeen: markFirstUseHintSeen,
        decorateOverviewForFirstUse: decorateOverviewForFirstUse,
    });
})(window);
