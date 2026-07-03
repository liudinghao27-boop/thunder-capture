(function (window) {
    'use strict';

    window.DeviceApi = Object.freeze({
        list() {
            return window.apiFetch('/api/devices');
        },
        scan() {
            return window.apiFetch('/api/devices/scan', { method: 'POST' });
        },
        health(deviceId) {
            return window.apiFetch(`/api/devices/${deviceId}/health`);
        },
        heartbeat(deviceId) {
            return window.apiFetch(`/api/devices/${deviceId}/heartbeat`, { method: 'POST' });
        },
        prepareKeyboard(deviceId) {
            return window.apiFetch(`/api/devices/${deviceId}/prepare-keyboard`, { method: 'POST' });
        },
        resetFuse(deviceId) {
            return window.apiFetch(`/api/devices/${deviceId}/reset-fuse`, { method: 'POST' });
        },
        dryRun(deviceId, payload) {
            return window.apiFetch(`/api/devices/${deviceId}/acceptance/dry-run`, {
                method: 'POST',
                body: JSON.stringify(payload || {}),
            });
        },
        liveSend(deviceId, payload) {
            return window.apiFetch(`/api/devices/${deviceId}/acceptance/live-send`, {
                method: 'POST',
                body: JSON.stringify(payload || {}),
            });
        },
        screenUrl(deviceId) {
            return `/api/devices/${deviceId}/screen/stream?_=${Date.now()}`;
        },
        control(deviceId, action, payload) {
            return window.apiFetch(`/api/devices/${deviceId}/control/${action}`, {
                method: 'POST',
                body: JSON.stringify(payload || {}),
            });
        },
    });
})(window);
