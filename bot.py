from dialog_bot_sdk.bot import DialogBot
import grpc
from collections import defaultdict




class Strategy:
    def __init__(self, token, endpoint, async_=True):
        self.bot = None
        self.endpoint = endpoint
        self.token = token
        self.async_ = async_
        
    def start(self, *args, **kwargs):
        self.bot = DialogBot.get_secure_bot(
        self.endpoint,  # bot endpoint (specify different endpoint if you want to connect to your on-premise environment)
        grpc.ssl_channel_credentials(), # SSL credentials (empty by default!)
        self.token,  # bot token
        verbose=False # optional parameter, when it's True bot prints info about the called methods, False by default
        )
        if not self.async_:
            self.bot.messaging.on_message(self.on_msg, self.on_click)
        else:
            self.bot.messaging.on_message_async(self.on_msg, self.on_click)
        self.strategy(*args, **kwargs)
        
        
    def strategy(self, *args, **kwargs):
        pass
    
    def on_msg(self, *params):
        pass
    
    def on_click(self, *params):
        pass