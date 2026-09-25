/* Customer payment flow (Razorpay).
 *
 * 1. POST /api/payments/create/  -> backend creates the gateway order for the
 *    server-side order total and records a PENDING payment.
 * 2. Razorpay Checkout collects the payment (card/UPI details never touch
 *    this site's servers).
 * 3. POST /api/payments/verify/  -> backend verifies the gateway signature,
 *    marks the payment SUCCESS, confirms the order and deducts stock.
 * The browser's "success" callback alone never confirms an order.
 */
window.ShopPayments = (() => {
    function csrf() {
        const m = document.cookie.split('; ').find(r => r.startsWith('csrftoken='));
        return m ? decodeURIComponent(m.split('=')[1]) : '';
    }

    async function post(url, data) {
        const res = await fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': csrf() },
            body: JSON.stringify(data),
        });
        let body = {};
        if ((res.headers.get('content-type') || '').includes('application/json')) body = await res.json();
        return { ok: res.ok, status: res.status, body };
    }

    function describe(body, fallback) {
        if (!body) return fallback;
        const parts = [body.error || body.detail || fallback];
        if (Array.isArray(body.problems) && body.problems.length) parts.push(body.problems.join(' '));
        return parts.join(' ');
    }

    /**
     * Pay for an existing PENDING order.
     * callbacks: onStatus(text), onSuccess(order), onError(message), onDismiss()
     */
    async function payForOrder(orderId, { onStatus, onSuccess, onError, onDismiss, urls }) {
        onStatus && onStatus('Connecting to secure payment gateway…');
        const created = await post(urls.create, { order_id: orderId });
        if (!created.ok) {
            onError(describe(created.body, 'Could not start the payment.'));
            return;
        }
        if (typeof Razorpay === 'undefined') {
            onError('The payment window could not be loaded. Check your connection and try again.');
            return;
        }
        const p = created.body;
        const rzp = new Razorpay({
            key: p.key_id,
            amount: p.amount,
            currency: p.currency,
            order_id: p.gateway_order_id,
            name: 'Shopping_App',
            description: `Order #${p.order_id}`,
            prefill: p.prefill,
            theme: { color: '#6366F1' },
            handler: async response => {
                onStatus && onStatus('Verifying payment…');
                const verified = await post(urls.verify, {
                    razorpay_order_id: response.razorpay_order_id,
                    razorpay_payment_id: response.razorpay_payment_id,
                    razorpay_signature: response.razorpay_signature,
                });
                if (verified.ok && verified.body.success) onSuccess(verified.body.order);
                else onError(describe(verified.body, 'Payment could not be verified.'));
            },
            modal: { ondismiss: () => onDismiss && onDismiss() },
        });
        rzp.on('payment.failed', resp => {
            onError((resp && resp.error && resp.error.description) || 'The payment failed. You have not been charged.');
        });
        rzp.open();
    }

    return { post, describe, payForOrder };
})();
