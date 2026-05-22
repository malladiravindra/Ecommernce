# WebSocket Live Chat Setup Guide

## Overview
A real-time chat system has been successfully added to your Django e-commerce project using Django Channels and WebSockets. This enables WhatsApp-style messaging between customers and sellers about products.

## What Was Added

### 1. **Models** (`shop/models.py`)
- `Conversation`: Represents a chat thread between a customer and seller
  - Fields: customer, seller, product, created_at, updated_at
  - Unique constraint on (customer, seller, product)
  
- `Message`: Individual messages in a conversation
  - Fields: conversation, sender, content, created_at, is_read
  - Ordered by created_at

### 2. **WebSocket Consumer** (`shop/consumers.py`)
- `ChatConsumer`: Handles real-time messaging
  - Manages WebSocket connections
  - Verifies user permissions
  - Saves messages to database
  - Broadcasts messages to all connected clients in conversation

### 3. **Routing** (`shop/routing.py`)
- WebSocket URL pattern: `ws/chat/<conversation_id>/`

### 4. **ASGI Configuration** (`ecommernce/asgi.py`)
- Updated to use ProtocolTypeRouter for both HTTP and WebSocket
- Uses AuthMiddlewareStack for authentication
- AllowedHostsOriginValidator for security

### 5. **Settings Updates** (`ecommernce/settings.py`)
- Added `daphne` to INSTALLED_APPS
- Configured `ASGI_APPLICATION`
- Configured `CHANNEL_LAYERS`:
  - Uses Redis in production
  - Falls back to InMemoryChannelLayer for development

### 6. **Views** (`shop/views.py`)
- `ConversationListView`: Lists all user conversations with unread count
- `ConversationDetailView`: Displays a specific conversation
- `StartConversationView`: API to initiate a new conversation

### 7. **URLs** (`shop/urls.py`)
Added:
```
/chat/                              - List all conversations
/chat/<id>/                         - View specific conversation
/chat/start/                        - API to start conversation
```

### 8. **Templates**
- `templates/shop/conversations_list.html`: Conversation list UI
- `templates/shop/chat.html`: Real-time chat interface with WebSocket

### 9. **Admin Interface** (`shop/admin.py`)
Registered Conversation and Message models in Django admin for management

## Setup Instructions

### Step 1: Install Daphne (if not already installed)
```bash
pip install daphne
```

### Step 2: Run Migrations
```bash
python manage.py makemigrations
python manage.py migrate
```

### Step 3: Running the Development Server

**Option A: Using Daphne (Recommended)**
```bash
daphne -b 0.0.0.0 -p 8000 ecommernce.asgi:application
```

**Option B: Using Django runserver**
```bash
# This still works but won't have real-time WebSocket support
python manage.py runserver
```

### Step 4: Test the Chat Feature

1. **Create multiple users** (if you don't have them)
   - Go to `/admin/` and create test users
   - Or use the `/register/` page

2. **Start a conversation**
   - Login as a customer
   - Navigate to a product detail page
   - Look for a "Message Seller" button (you'll need to add this to the product detail template)
   - Or directly access: `/chat/start/` with POST data

3. **Open the chat**
   - Click on a conversation from `/chat/`
   - Messages will appear in real-time

## Key Features

✅ **Real-time Messaging**: Messages appear instantly using WebSocket  
✅ **User Authentication**: Only verified users can access conversations  
✅ **Message History**: All messages are stored in database  
✅ **Unread Tracking**: System tracks which messages are read  
✅ **Product Context**: Each conversation is tied to a specific product  
✅ **Responsive Design**: Bootstrap-based responsive UI  

## Architecture

```
Client 1 (Browser)
    |
    |-- WebSocket Connection
    |
Channel Layer (Redis/InMemory)
    |
    |-- ChatConsumer (Daphne ASGI)
    |
    |-- Database
    |       ↓
Customer | Seller
    Message: "Is this in stock?"
```

## Configuration Options

### Redis Configuration (Production)
Set `REDIS_URL` in your `.env` file:
```
REDIS_URL=redis://localhost:6379
```

### Development (InMemory)
By default, development uses InMemoryChannelLayer. To use Redis even in development:
```bash
# Start Redis
redis-server

# Set environment variable
set REDIS_URL=redis://localhost:6379

# Start Daphne
daphne -b 0.0.0.0 -p 8000 ecommernce.asgi:application
```

## Frontend Integration

To add a "Message Seller" button to product detail page, add to `product_detail.html`:

```html
{% if user.is_authenticated %}
    <form method="post" action="{% url 'start_conversation' %}">
        {% csrf_token %}
        <input type="hidden" name="seller_id" value="{{ product.seller.id }}">
        <input type="hidden" name="product_id" value="{{ product.id }}">
        <button type="submit" class="btn btn-primary">
            <i class="fas fa-comments"></i> Message Seller
        </button>
    </form>
{% else %}
    <a href="{% url 'login' %}" class="btn btn-primary">Login to Chat</a>
{% endif %}
```

## Database Schema

### Conversation Table
```
id (PK)
customer_id (FK -> User)
seller_id (FK -> User)
product_id (FK -> Product, nullable)
created_at
updated_at
```

### Message Table
```
id (PK)
conversation_id (FK -> Conversation)
sender_id (FK -> User)
content (TextField)
created_at
is_read
```

## Troubleshooting

### WebSocket Connection Refused
- Ensure Daphne is running, not `runserver`
- Check firewall settings allow WebSocket connections
- Verify ALLOWED_HOSTS in settings.py includes your domain

### Messages Not Persisting
- Ensure migrations were run: `python manage.py migrate`
- Check database connection

### Real-time Updates Not Working
- Verify Redis is running (if using Redis)
- Check browser console for WebSocket connection errors
- Ensure correct WebSocket URL in chat.html

## Security Considerations

✅ **User Verification**: Consumer verifies user is part of conversation  
✅ **CSRF Protection**: CSRF token in message form  
✅ **Authentication**: AuthMiddlewareStack ensures only logged-in users connect  
✅ **Origin Validation**: AllowedHostsOriginValidator prevents cross-origin attacks  
✅ **Message Validation**: Server-side validation of message content  

## Performance Tips

1. **Use Redis** for better performance with multiple users
2. **Implement message pagination** for conversations with many messages
3. **Add connection pooling** for database connections
4. **Monitor consumer memory** usage with many concurrent connections

## Future Enhancements

- [ ] Message read receipts and typing indicators
- [ ] File/Image sharing in chat
- [ ] Message search functionality
- [ ] Chat notifications (email, push)
- [ ] Rate limiting on messages
- [ ] Auto-delete old messages
- [ ] Chat rooms for multiple users
- [ ] Admin moderation tools

## Testing WebSocket

### Using WebSocket Test Tools
```bash
# Using wscat (npm)
npm install -g wscat
wscat -c ws://localhost:8000/ws/chat/1/

# Using websocat (Rust)
cargo install websocat
websocat ws://localhost:8000/ws/chat/1/
```

### Manual Testing in Browser Console
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/chat/1/');
ws.onmessage = (e) => console.log(JSON.parse(e.data));
ws.send(JSON.stringify({message: 'Hello!'}));
```

## Files Modified/Created

### Created:
- `shop/consumers.py` - WebSocket consumer
- `shop/routing.py` - WebSocket routing
- `templates/shop/chat.html` - Chat UI
- `templates/shop/conversations_list.html` - Conversations list

### Modified:
- `ecommernce/asgi.py` - Channels configuration
- `ecommernce/settings.py` - Channel layers, Daphne app
- `shop/models.py` - Conversation, Message models
- `shop/views.py` - Chat views
- `shop/urls.py` - Chat URLs
- `shop/admin.py` - Admin registration

## Support & Documentation

- [Django Channels Documentation](https://channels.readthedocs.io/)
- [Django WebSocket Best Practices](https://channels.readthedocs.io/en/latest/topics/security.html)
- [Redis Setup Guide](https://redis.io/docs/getting-started/)
