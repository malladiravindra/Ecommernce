/* Admin panel helpers — every page loads its data from /api/admin/. */
window.Admin = (() => {
    function getCookie(name) {
        const match = document.cookie.split('; ').find(row => row.startsWith(name + '='));
        return match ? decodeURIComponent(match.split('=')[1]) : '';
    }

    function errorMessage(body, status) {
        if (!body) return `Request failed (${status}).`;
        if (typeof body === 'string') return body;
        if (body.error) return body.error;
        if (body.detail) return body.detail;
        return Object.entries(body).map(([key, val]) => {
            const text = Array.isArray(val) ? val.join(' ') : (typeof val === 'object' ? JSON.stringify(val) : val);
            return key === 'non_field_errors' ? text : `${key.replace(/_/g, ' ')}: ${text}`;
        }).join(' · ');
    }

    /** fetch wrapper: session auth + CSRF, JSON or FormData bodies, throws on non-2xx. */
    async function api(url, { method = 'GET', data, form } = {}) {
        const opts = {
            method,
            credentials: 'same-origin',
            headers: { 'X-CSRFToken': getCookie('csrftoken'), 'Accept': 'application/json' },
        };
        if (form) {
            opts.body = form;
        } else if (data !== undefined) {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(data);
        }
        const res = await fetch(url, opts);
        let body = null;
        if (res.status !== 204 && (res.headers.get('content-type') || '').includes('application/json')) {
            body = await res.json();
        }
        if (res.status === 401) {
            window.location.href = '/admin-login/?next=' + encodeURIComponent(location.pathname);
        }
        if (!res.ok) {
            const err = new Error(errorMessage(body, res.status));
            err.status = res.status;
            err.body = body;
            throw err;
        }
        return body;
    }

    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const money = value => '₹' + Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const date = value => value ? new Date(value).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '—';
    const shortDate = value => value ? new Date(value).toLocaleDateString('en-IN', { dateStyle: 'medium' }) : '—';

    function toast(message, type = 'success') {
        let box = document.querySelector('.ap-toasts');
        if (!box) {
            box = document.createElement('div');
            box.className = 'ap-toasts';
            document.body.appendChild(box);
        }
        const icon = { success: 'circle-check', error: 'circle-exclamation', info: 'circle-info' }[type] || 'circle-info';
        const el = document.createElement('div');
        el.className = `ap-toast ${type}`;
        el.setAttribute('role', 'status');
        el.innerHTML = `<i class="fa-solid fa-${icon}" style="margin-top:2px"></i><span>${esc(message)}</span>`;
        box.appendChild(el);
        setTimeout(() => el.remove(), type === 'error' ? 6000 : 3500);
    }

    const statusBadge = (status, label) => `<span class="badge-status s-${esc(String(status).toLowerCase())}">${esc(label || status)}</span>`;
    const paymentBadge = payment => payment
        ? `<span class="badge-status p-${esc(payment.status.toLowerCase())}">${esc(payment.status)}</span>`
        : '<span class="badge-status p-pending">UNPAID</span>';
    const activeBadge = active => active ? '<span class="badge-status b-active">Active</span>' : '<span class="badge-status b-inactive">Inactive</span>';

    function stockText(stock, threshold = 5) {
        if (stock <= 0) return '<span class="stock-out">Out of stock</span>';
        if (stock <= threshold) return `<span class="stock-low">${stock} left</span>`;
        return `${stock}`;
    }

    function thumb(url, size = 44) {
        return url
            ? `<img src="${esc(url)}" class="ap-thumb" style="width:${size}px;height:${size}px" alt="" loading="lazy">`
            : `<div class="ap-thumb" style="width:${size}px;height:${size}px"><i class="fa-regular fa-image"></i></div>`;
    }

    /** Render DRF PageNumberPagination controls (server page size is 20). */
    function pagination(container, data, page, onPage, pageSize = 20) {
        if (!container) return;
        const totalPages = Math.max(1, Math.ceil(data.count / pageSize));
        container.innerHTML = `
            <span class="text-muted small">${data.count} result${data.count === 1 ? '' : 's'} · page ${page} of ${totalPages}</span>
            <div class="d-flex gap-2">
                <button class="btn btn-sm btn-outline-secondary" ${data.previous ? '' : 'disabled'} data-page="${page - 1}"><i class="fa-solid fa-chevron-left"></i></button>
                <button class="btn btn-sm btn-outline-secondary" ${data.next ? '' : 'disabled'} data-page="${page + 1}"><i class="fa-solid fa-chevron-right"></i></button>
            </div>`;
        container.querySelectorAll('button[data-page]').forEach(btn => btn.addEventListener('click', () => onPage(Number(btn.dataset.page))));
    }

    function confirmDialog(message, confirmLabel = 'Delete', danger = true) {
        return new Promise(resolve => {
            const modalEl = document.getElementById('ap-confirm');
            modalEl.querySelector('.ap-confirm-text').textContent = message;
            const ok = modalEl.querySelector('.ap-confirm-ok');
            ok.textContent = confirmLabel;
            ok.className = `btn ap-confirm-ok ${danger ? 'btn-danger' : 'btn-primary'}`;
            const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
            let result = false;
            const onOk = () => { result = true; modal.hide(); };
            ok.addEventListener('click', onOk, { once: true });
            modalEl.addEventListener('hidden.bs.modal', () => { ok.removeEventListener('click', onOk); resolve(result); }, { once: true });
            modal.show();
        });
    }

    function debounce(fn, ms = 300) {
        let t;
        return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
    }

    function setBusy(button, busy, label) {
        if (!button) return;
        if (busy) {
            button.dataset.label = button.innerHTML;
            button.disabled = true;
            button.innerHTML = `<span class="spinner-border spinner-border-sm me-2"></span>${esc(label || 'Saving…')}`;
        } else {
            button.disabled = false;
            if (button.dataset.label) button.innerHTML = button.dataset.label;
        }
    }

    function query(params) {
        const q = new URLSearchParams();
        Object.entries(params).forEach(([k, v]) => { if (v !== '' && v !== null && v !== undefined) q.set(k, v); });
        const s = q.toString();
        return s ? `?${s}` : '';
    }

    // Mobile sidebar toggle
    document.addEventListener('click', e => {
        if (e.target.closest('.ap-menu-btn')) document.body.classList.toggle('ap-nav-open');
        else if (e.target.closest('.ap-backdrop')) document.body.classList.remove('ap-nav-open');
    });

    return { api, esc, money, date, shortDate, toast, statusBadge, paymentBadge, activeBadge, stockText, thumb, pagination, confirmDialog, debounce, setBusy, query, errorMessage };
})();
