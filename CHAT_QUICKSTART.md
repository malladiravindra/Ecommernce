# Quick Start Guide - WebSocket Chat

## 1. Run Database Migrations
```bash
python manage.py makemigrations
python manage.py migrate
```

## 2. Start the Development Server (Daphne)
```bash
daphne -b 0.0.0.0 -p 8000 ecommernce.asgi:application
```

## 3. Test the Chat System

### Create Test Users
1. Go to http://localhost:8000/admin/
2. Create 2 users: "seller1" and "customer1"
3. Assign some products to the "seller1" user (create a seller field in Product model if needed)

### Access Chat
1. Login as customer1: http://localhost:8000/login/
2. Navigate to conversations: http://localhost:8000/chat/
3. Start a conversation with the StartConversationView API

### Start a Conversation (API Example)
```bash
curl -X POST http://localhost:8000/chat/start/ \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "seller_id=1&product_id=1" \
  -b "csrftoken=YOUR_CSRF_TOKEN"
```

## 4. Features to Test

✅ **Real-time Message Delivery**
- Open chat in two browser windows (seller & customer)
- Type a message
- Verify it appears instantly in the other window

✅ **Message History**
- Refresh the page
- Old messages should still be visible

✅ **Read Status**
- Messages are marked as read when viewed
- Check in admin

✅ **User Verification**
- Try accessing someone else's conversation
- Should be denied access

## Important: You Need to Add to Product Detail Page

Add this button to make it easy to start conversations:

**File: `templates/shop/product_detail.html`**

```html
<!-- Add this near the product price/actions -->
<div class="mt-3">
    {% if user.is_authenticated and user != product.seller %}
        <form method="post" action="{% url 'start_conversation' %}">
            {% csrf_token %}
            <input type="hidden" name="seller_id" value="{{ seller_user.id }}">
            <input type="hidden" name="product_id" value="{{ product.id }}">
            <button type="submit" class="btn btn-outline-primary">
                <i class="fas fa-comments"></i> Message Seller
            </button>
        </form>
    {% elif not user.is_authenticated %}
        <a href="{% url 'login' %}" class="btn btn-outline-primary">
            <i class="fas fa-comments"></i> Login to Message
        </a>
    {% endif %}
</div>
```

## Debugging

### Enable WebSocket Logging
Add to settings.py:
```python
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'channels': {
            'handlers': ['console'],
            'level': 'DEBUG',
        },
    },
}
```

### Check WebSocket Connection
Open browser console (F12) and look for:
- "Chat WebSocket connection established"
- Messages appearing in console

### Common Issues
1. **WebSocket Connection Failed**
   - Check Daphne is running
   - Check ALLOWED_HOSTS includes your domain
   
2. **Messages Not Saving**
   - Verify migrations: `python manage.py showmigrations`
   - Check database: `python manage.py shell`
   
3. **Redis Connection Error**
   - Start Redis: `redis-server`
   - Or set `REDIS_URL` env var

## Next Steps

1. ✅ Test with Daphne
2. ✅ Add "Message Seller" button to product page
3. ✅ Test messaging between users
4. ⬜ Deploy with production WebSocket server (e.g., Gunicorn + Daphne)
5. ⬜ Add WebSocket authentication tokens
6. ⬜ Implement typing indicators
7. ⬜ Add file/image sharing
