import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User
from .models import Conversation, Message


class ChatConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time chat between customers and sellers."""

    async def connect(self):
        """Handle WebSocket connection."""
        self.user = self.scope["user"]
        self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
        self.room_group_name = f'chat_{self.conversation_id}'

        # Verify user is part of this conversation
        is_member = await self.verify_conversation_member()
        if not is_member:
            await self.close()
            return

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """Receive message from WebSocket."""
        try:
            data = json.loads(text_data)
            message_content = data.get('message', '').strip()

            if not message_content:
                return

            # Save message to database
            message = await self.save_message(message_content)

            # Broadcast message to room group
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',
                    'message': message_content,
                    'sender': self.user.username,
                    'sender_id': self.user.id,
                    'timestamp': str(message.created_at),
                }
            )
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'error': 'Invalid message format'
            }))

    async def chat_message(self, event):
        """Send message to WebSocket."""
        message = event['message']
        sender = event['sender']
        sender_id = event['sender_id']
        timestamp = event['timestamp']

        # Determine if this is the current user's message
        is_own_message = sender_id == self.user.id

        await self.send(text_data=json.dumps({
            'message': message,
            'sender': sender,
            'sender_id': sender_id,
            'timestamp': timestamp,
            'is_own_message': is_own_message,
        }))

    @database_sync_to_async
    def verify_conversation_member(self):
        """Verify that the current user is part of the conversation."""
        try:
            conversation = Conversation.objects.get(id=self.conversation_id)
            return self.user == conversation.customer or self.user == conversation.seller
        except Conversation.DoesNotExist:
            return False

    @database_sync_to_async
    def save_message(self, content):
        """Save message to database."""
        conversation = Conversation.objects.get(id=self.conversation_id)
        message = Message.objects.create(
            conversation=conversation,
            sender=self.user,
            content=content,
            is_read=False
        )
        return message
