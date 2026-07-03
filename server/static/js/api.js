(function (window) {
    'use strict';

    function formatApiErrorDetail(detail) {
        if (!detail) return '';
        if (typeof detail === 'string') return detail;
        if (Array.isArray(detail)) {
            return detail.map((item) => {
                if (!item) return '';
                if (typeof item === 'string') return item;
                const loc = Array.isArray(item.loc) ? item.loc.filter(Boolean).join('.') : '';
                const msg = item.msg || item.message || JSON.stringify(item);
                return loc ? `${loc}: ${msg}` : msg;
            }).filter(Boolean).join('；');
        }
        if (typeof detail === 'object') {
            return detail.message || JSON.stringify(detail);
        }
        return String(detail);
    }

    async function apiFetchRaw(endpoint, options = {}) {
        const request = { ...options };
        const headers = new Headers(options.headers || {});
        const token = localStorage.getItem('thunder_token') || '';
        if (token) headers.set('Authorization', `Bearer ${token}`);
        if (request.body && !(request.body instanceof FormData) && !(request.body instanceof Blob)) {
            headers.set('Content-Type', 'application/json');
        }
        request.headers = headers;

        const response = await fetch(`${window.location.origin}${endpoint}`, request);
        if (response.status === 401) {
            localStorage.removeItem('thunder_token');
            window.location.assign('/');
            throw new Error('登录已过期，请重新登录');
        }
        return response;
    }

    async function apiFetch(endpoint, options = {}) {
        const response = await apiFetchRaw(endpoint, options);
        if (response.status === 204 || response.headers.get('content-length') === '0') {
            return {};
        }
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(formatApiErrorDetail(data.detail) || data.message || `请求失败 (${response.status})`);
        }
        return data;
    }

    window.formatApiErrorDetail = formatApiErrorDetail;
    window.apiFetchRaw = apiFetchRaw;
    window.apiFetch = apiFetch;
})(window);
