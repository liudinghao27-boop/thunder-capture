(function (window) {
    'use strict';

    window.JobApi = Object.freeze({
        list(limit = 100) {
            return window.apiFetch(`/api/jobs?limit=${encodeURIComponent(limit)}`);
        },
        get(jobId) {
            return window.apiFetch(`/api/jobs/${jobId}`);
        },
        devices(jobId) {
            return window.apiFetch(`/api/jobs/${jobId}/devices`);
        },
        startCollect(industrySlug, skipDiscover = false) {
            return window.apiFetch('/api/jobs/collect/start', {
                method: 'POST',
                body: JSON.stringify({
                    industry_slug: industrySlug,
                    skip_discover: Boolean(skipDiscover),
                }),
            });
        },
        startSend(industrySlug, deviceIds) {
            return window.apiFetch('/api/jobs/send/start', {
                method: 'POST',
                body: JSON.stringify({
                    industry_slug: industrySlug,
                    device_ids: deviceIds,
                }),
            });
        },
        cancel(jobId) {
            return window.apiFetch(`/api/jobs/${jobId}/cancel`, { method: 'POST' });
        },
        isTerminal(status) {
            return ['done', 'failed', 'cancelled', 'sent', 'restricted', 'unconfirmed'].includes(status);
        },
    });
})(window);
