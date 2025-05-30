# -*- coding: utf-8 -*-
import os
import time
import threading
import logging
from typing import Dict, Optional, Tuple
import json

from dotenv import load_dotenv # Import dotenv library
from dify_plugin.config.logger_format import plugin_logger_handler

# DingTalk OAuth2.0 related
from alibabacloud_dingtalk.oauth2_1_0.client import Client as DingtalkOAuthClient # Rename to avoid conflicts
from alibabacloud_tea_openapi import models as OpenApiModels
from alibabacloud_dingtalk.oauth2_1_0 import models as DingtalkOAuthModels # Rename to avoid conflicts

from alibabacloud_dingtalk.assistant_1_0.client import Client as DingtalkAssistantClient
from alibabacloud_dingtalk.assistant_1_0 import models as DingtalkAssistantModels
from alibabacloud_tea_util import models as util_models # Utility tools
from alibabacloud_tea_util.client import Client as UtilClient # Utility client

import requests

load_dotenv() # Load environment variables from .env file

# 创建控制台日志处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
# 设置日志格式
console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)

# Set up logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
# 添加两个处理器
logger.addHandler(plugin_logger_handler)
logger.addHandler(console_handler)

class DingtalkTokenManager:
    """DingTalk AccessToken Manager"""
    
    _lock = threading.Lock()
    _token_cache: Dict[str, Dict] = {}  # Support multiple application scenarios
    
    @classmethod
    def _create_oauth_client(cls) -> DingtalkOAuthClient: # Rename method to distinguish
        """Create DingTalk OAuth client"""
        config = OpenApiModels.Config()
        config.protocol = 'https'
        config.region_id = 'central'
        return DingtalkOAuthClient(config)
    
    @classmethod
    def get_access_token(cls, app_key: Optional[str] = None, app_secret: Optional[str] = None) -> str:
        """
        Get DingTalk access token
        
        Args:
            app_key: DingTalk application Key, defaults to environment variable
            app_secret: DingTalk application Secret, defaults to environment variable
            
        Returns:
            str: access token
        """
        app_key = app_key or os.getenv('DINGTALK_APP_KEY')
        app_secret = app_secret or os.getenv('DINGTALK_APP_SECRET')
        
        if not app_key or not app_secret:
            logger.error("DingTalk configuration missing, please check environment variables DINGTALK_APP_KEY and DINGTALK_APP_SECRET")
            raise ValueError("DingTalk configuration missing, please check environment variables DINGTALK_APP_KEY and DINGTALK_APP_SECRET")
        
        with cls._lock:
            now = int(time.time())
            cache = cls._token_cache.get(app_key, {})
            
            # If token is not expired, return directly
            if cache.get('token') and now < cache.get('expire_at', 0) - 60:  # Refresh 1 minute early
                logger.debug(f"Using cached access token, expires in: {cache.get('expire_at', 0) - now} seconds")
                return cache['token']
            
            try:
                logger.info("Starting to get new access token")
                client = cls._create_oauth_client() # Use new method name
                req = DingtalkOAuthModels.GetAccessTokenRequest( # Use new model name
                    app_key=app_key,
                    app_secret=app_secret
                )
                resp = client.get_access_token(req)
                access_token = resp.body.access_token
                expire_in = resp.body.expire_in

                # Update cache
                cls._token_cache[app_key] = {
                    'token': access_token,
                    'expire_at': now + expire_in
                }
                
                logger.info(f"Successfully obtained new DingTalk access token, expires in: {expire_in} seconds")
                return access_token
                
            except Exception as e:
                logger.error(f"Failed to get DingTalk access token: {str(e)}", exc_info=True)
                raise

class DingtalkAPI:
    """DingTalk API Call Wrapper"""
    
    def __init__(self):
        self.api_host = os.getenv('DINGTALK_API_HOST', 'api.dingtalk.com')
        self.base_url = f"https://{self.api_host}"
        self._assistant_client: Optional[DingtalkAssistantClient] = None
        logger.info(f"Initializing DingTalk API client, API host: {self.api_host}")

    @property
    def assistant_client(self) -> DingtalkAssistantClient:
        """Get or create DingTalk Assistant API client"""
        if self._assistant_client is None:
            logger.debug("Creating new DingTalk Assistant API client")
            config = OpenApiModels.Config()
            config.protocol = 'https'
            config.region_id = 'central'
            self._assistant_client = DingtalkAssistantClient(config)
        return self._assistant_client

    def _get_assistant_headers(self) -> DingtalkAssistantModels.CreateAssistantThreadHeaders:
        """Get Assistant API request headers, including Access Token"""
        headers = DingtalkAssistantModels.CreateAssistantThreadHeaders()
        headers.x_acs_dingtalk_access_token = DingtalkTokenManager.get_access_token()
        print(headers.x_acs_dingtalk_access_token)
        return headers

    # --- Thread Management ---
    def create_thread(self, metadata: Optional[Dict] = None) -> Tuple[DingtalkAssistantModels.CreateAssistantThreadResponseBody, str]:
        """
        Create AI Assistant session (Thread)

        Args:
            metadata: Session metadata

        Returns:
            DingtalkAssistantModels.CreateAssistantThreadResponseBody: Creation result
        """
        logger.info("Starting to create new AI Assistant session")
        request = DingtalkAssistantModels.CreateAssistantThreadRequest(metadata=metadata)
        try:
            resp = self.assistant_client.create_assistant_thread_with_options(
                request, self._get_assistant_headers(), util_models.RuntimeOptions()
            )
            # Add debug information
            logger.debug(f"Thread creation response: {resp.body}")
            # Safely get thread_id using getattr, fallback to id if not found
            thread_id = getattr(resp.body, 'thread_id', getattr(resp.body, 'id', None))
            if thread_id:
                logger.info(f"Successfully created AI Assistant session, Thread ID: {thread_id}")
            else:
                logger.warning("Thread created successfully but ID not found, response body: %s", resp.body)
            return resp.body, thread_id
        except Exception as e:
            logger.error(f"Failed to create DingTalk Thread: {str(e)}", exc_info=True)
            if hasattr(e, 'code') and hasattr(e, 'message'):
                logger.error(f"Error code: {e.code}, Error message: {e.message}")
            raise

    def delete_thread(self, thread_id: str) -> bool:
        """
        Delete AI Assistant session (Thread)

        Args:
            thread_id: Session ID

        Returns:
            bool: Whether deletion was successful
        """
        logger.info(f"Starting to delete AI Assistant session: {thread_id}")
        try:
            self.assistant_client.delete_assistant_thread_with_options(
                thread_id, self._get_assistant_headers(), util_models.RuntimeOptions()
            )
            logger.info(f"Successfully deleted DingTalk Thread: {thread_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete DingTalk Thread {thread_id}: {str(e)}", exc_info=True)
            if not UtilClient.empty(e.code) and not UtilClient.empty(e.message):
                logger.error(f"Error code: {e.code}, Error message: {e.message}")
            raise
            return False

    def retrieve_thread(self, thread_id: str) -> DingtalkAssistantModels.RetrieveAssistantThreadResponseBody:
        """
        Retrieve AI Assistant session (Thread)

        Args:
            thread_id: Session ID

        Returns:
            DingtalkAssistantModels.RetrieveAssistantThreadResponseBody: Session details
        """
        logger.info(f"Starting to retrieve AI Assistant session: {thread_id}")
        try:
            resp = self.assistant_client.retrieve_assistant_thread_with_options(
                thread_id, self._get_assistant_headers(), util_models.RuntimeOptions()
            )
            logger.info(f"Successfully retrieved DingTalk Thread: {thread_id}")
            return resp.body
        except Exception as e:
            logger.error(f"Failed to retrieve DingTalk Thread {thread_id}: {str(e)}", exc_info=True)
            if not UtilClient.empty(e.code) and not UtilClient.empty(e.message):
                logger.error(f"Error code: {e.code}, Error message: {e.message}")
            raise

    # --- Message Management ---
    def create_message(self, thread_id: str, role: str, content: str) -> Tuple[DingtalkAssistantModels.CreateAssistantMessageResponseBody, str]:
        """
        Create message in specified session

        Args:
            thread_id: Session ID
            role: Message role (e.g., "user", "assistant")
            content: Message content

        Returns:
            DingtalkAssistantModels.CreateAssistantMessageResponseBody: Creation result
        """
        logger.info(f"Starting to create {role} message in Thread {thread_id}")
        request = DingtalkAssistantModels.CreateAssistantMessageRequest(
            role=role,
            content=content
        )
        try:
            resp = self.assistant_client.create_assistant_message_with_options(
                thread_id, request, self._get_assistant_headers(), util_models.RuntimeOptions()
            )
            # 使用 getattr 安全地获取 message_id，如果不存在则使用 id
            message_id = getattr(resp.body, 'message_id', getattr(resp.body, 'id', None))
            if message_id:
                logger.info(f"Successfully created message in Thread {thread_id}, Message ID: {message_id}")
            else:
                logger.warning(f"Message created successfully but ID not found in response body: {resp.body}")
            return resp.body, message_id
        except Exception as e:
            logger.error(f"Failed to create message in Thread {thread_id}: {str(e)}", exc_info=True)
            # 检查异常是否有 code 和 message 属性
            if hasattr(e, 'code') and hasattr(e, 'message'):
                logger.error(f"Error code: {e.code}, Error message: {e.message}")
            raise

    def delete_message(self, thread_id: str, message_id: str) -> bool:
        """
        Delete specific message in session

        Args:
            thread_id: Session ID
            message_id: Message ID

        Returns:
            bool: Whether deletion was successful
        """
        logger.info(f"Starting to delete message {message_id} in Thread {thread_id}")
        try:
            self.assistant_client.delete_assistant_message_with_options(
                thread_id, message_id, self._get_assistant_headers(), util_models.RuntimeOptions()
            )
            logger.info(f"Successfully deleted message {message_id} in Thread {thread_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete message {message_id} in Thread {thread_id}: {str(e)}", exc_info=True)
            if not UtilClient.empty(e.code) and not UtilClient.empty(e.message):
                logger.error(f"Error code: {e.code}, Error message: {e.message}")
            raise
            return False

    def list_messages(self, thread_id: str, limit: int = 20, order: str = "desc", run_id: Optional[str] = None) -> Tuple[DingtalkAssistantModels.ListAssistantMessageResponseBody, list]:
        """
        Get message list in session (using Assistant SDK)

        Args:
            thread_id: Session ID
            limit: Messages per page
            order: Sort order (desc or asc)
            run_id: Run ID (optional)

        Returns:
            Tuple[DingtalkAssistantModels.ListAssistantMessageResponseBody, list]: Message list response and messages
        """
        logger.info(f"Starting to get message list for Thread {thread_id}, limit={limit}, order={order}")
        request = DingtalkAssistantModels.ListAssistantMessageRequest(
            limit=limit,
            order=order,
            run_id=run_id
        )
        try:
            resp = self.assistant_client.list_assistant_message_with_options(
                thread_id, request, self._get_assistant_headers(), util_models.RuntimeOptions()
            )
            # Add debug information
            logger.debug(f"Message list response: {resp.body}")
            # Safely get messages using getattr
            messages = getattr(resp.body, 'data', [])
            if messages:
                logger.info(f"Successfully got message list for Thread {thread_id}, total messages: {len(messages)}")
            else:
                logger.warning("No messages found in response body: %s", resp.body)
            return resp.body, messages
        except Exception as e:
            logger.error(f"Failed to get message list for Thread {thread_id}: {str(e)}", exc_info=True)
            if not UtilClient.empty(e.code) and not UtilClient.empty(e.message):
                logger.error(f"Error code: {e.code}, Error message: {e.message}")
            raise
            
    def retrieve_message(self, thread_id: str, message_id: str) -> DingtalkAssistantModels.RetrieveAssistantMessageResponseBody:
        """
        Retrieve specific message in session

        Args:
            thread_id: Session ID
            message_id: Message ID

        Returns:
            DingtalkAssistantModels.RetrieveAssistantMessageResponseBody: Message details
        """
        logger.info(f"Starting to retrieve message {message_id} in Thread {thread_id}")
        try:
            resp = self.assistant_client.retrieve_assistant_message_with_options(
                thread_id, message_id, self._get_assistant_headers(), util_models.RuntimeOptions()
            )
            logger.info(f"Successfully retrieved message {message_id} in Thread {thread_id}")
            return resp.body
        except Exception as e:
            logger.error(f"Failed to retrieve message {message_id} in Thread {thread_id}: {str(e)}", exc_info=True)
            if not UtilClient.empty(e.code) and not UtilClient.empty(e.message):
                logger.error(f"Error code: {e.code}, Error message: {e.message}")
            raise

    # --- Run Management ---
    def create_run(self, thread_id: str, assistant_id: str, instructions: Optional[str] = None, stream: bool = True) -> Tuple[DingtalkAssistantModels.CreateAssistantRunResponseBody, str]:
        """
        Run AI Assistant session (Thread)

        Args:
            thread_id: Session ID
            assistant_id: Assistant ID
            instructions: Run instructions (optional)
            stream: Whether to stream output (defaults to True)

        Yields:
            Dict: Stream events including:
                - event_type: Type of the event
                - data: Event data
                - text: Current text content (for message.delta events)
        """
        logger.info(f"Starting to create run task in Thread {thread_id}, assistant_id={assistant_id}")
        
        # 构建请求URL和headers
        url = f"https://{self.api_host}/v1.0/assistant/threads/{thread_id}/runs"
        headers = {
            'x-acs-dingtalk-access-token': DingtalkTokenManager.get_access_token(),
            'Content-Type': 'application/json'
        }
        
        # 构建请求体
        payload = {
            "assistantId": assistant_id,
            "instructions": instructions,
            "stream": stream
        }
        
        try:
            # 使用 requests 直接处理流式响应
            with requests.post(url, headers=headers, json=payload, stream=True) as response:
                response.raise_for_status()
                
                # 处理流式响应
                run_id = None
                current_message = None
                current_text = ""
                event_type = None
                
                for line in response.iter_lines():
                    if not line:
                        continue
                        
                    line = line.decode('utf-8')
                    if line.startswith('event:'):
                        event_type = line.split(':', 1)[1].strip()
                        continue
                    
                    if line.startswith('data:'):
                        try:
                            data = json.loads(line.split(':', 1)[1].strip())
                            
                            if event_type == 'thread.run.created':
                                run_id = data.get('runId')
                                logger.info(f"Run created with ID: {run_id}")
                                yield {
                                    'event_type': event_type,
                                    'data': data,
                                    'text': None
                                }
                                
                            elif event_type == 'thread.message.created':
                                current_message = data.get('messageId')
                                logger.info(f"Message created with ID: {current_message}")
                                yield {
                                    'event_type': event_type,
                                    'data': data,
                                    'text': None
                                }
                                
                            elif event_type == 'thread.message.delta':
                                if data.get('delta', {}).get('text', {}).get('value'):
                                    delta_text = data['delta']['text']['value']
                                    current_text += delta_text
                                    logger.info(f"Delta received: {delta_text}")
                                    yield {
                                        'event_type': event_type,
                                        'data': data,
                                        'text': current_text
                                    }
                                    
                            elif event_type == 'thread.message.completed':
                                logger.info(f"Message completed: {current_text}")
                                yield {
                                    'event_type': event_type,
                                    'data': data,
                                    'text': current_text
                                }
                                
                            elif event_type == 'thread.run.completed':
                                logger.info(f"Run completed with status: {data.get('statusEnum')}")
                                yield {
                                    'event_type': event_type,
                                    'data': data,
                                    'text': None
                                }
                                
                            elif event_type == 'done':
                                logger.info("Stream completed")
                                yield {
                                    'event_type': event_type,
                                    'data': None,
                                    'text': None
                                }
                                
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse JSON data: {e}")
                            continue
                            
            if not run_id:
                logger.warning("Run ID not found in response")
                
            return None, run_id
            
        except Exception as e:
            logger.error(f"Failed to run Thread {thread_id}: {str(e)}", exc_info=True)
            if hasattr(e, 'code') and hasattr(e, 'message'):
                logger.error(f"Error code: {e.code}, Error message: {e.message}")
            raise

    def retrieve_run(self, thread_id: str, run_id: str) -> DingtalkAssistantModels.RetrieveAssistantRunResponseBody:
        """
        Get AI Assistant session run information

        Args:
            thread_id: Session ID
            run_id: Run ID

        Returns:
            DingtalkAssistantModels.RetrieveAssistantRunResponseBody: Run details
        """
        logger.info(f"Starting to get run {run_id} information for Thread {thread_id}")
        try:
            resp = self.assistant_client.retrieve_assistant_run_with_options(
                thread_id, run_id, self._get_assistant_headers(), util_models.RuntimeOptions()
            )
            logger.info(f"Successfully got run information, status: {resp.body.status}")
            return resp.body
        except Exception as e:
            logger.error(f"Failed to get run {run_id} information for Thread {thread_id}: {str(e)}", exc_info=True)
            if not UtilClient.empty(e.code) and not UtilClient.empty(e.message):
                logger.error(f"Error code: {e.code}, Error message: {e.message}")
            raise

# Create global instance
dingtalk_api = DingtalkAPI()

# Usage example (needs to be adjusted based on new methods)
if __name__ == "__main__":
    # Example: Create a Thread, send a message, run it, and finally get message list
    try:
        # 1. Create Thread
        logger.info("Attempting to create Thread...")
        created_thread, thread_id = dingtalk_api.create_thread(metadata={"user_id": "test_user_123"})
        logger.info(f"Thread created successfully, ID: {thread_id}")

        # 2. Create user message in Thread
        logger.info(f"Attempting to create message in Thread {thread_id}...")
        user_message, message_id = dingtalk_api.create_message(thread_id, role="user", content="连接模型是什么?")
        logger.info(f"User message created successfully, ID: {message_id}")

        # 在运行之前,先检查当前message列表
        messages_response, messages_list = dingtalk_api.list_messages(thread_id, order="asc")
        logger.info("Current messages before run:")
        for msg in messages_list:
            role = getattr(msg, 'role', 'unknown')
            msg_id = getattr(msg, 'id', 'unknown')
            content = getattr(msg, 'content', [])
            text_value = 'No text content'
            if content and 'text' in content[0] and 'value' in content[0]['text']:
                text_value = content[0]['text']['value']
            logger.info(f"  - [{role}] ({msg_id}): {text_value}")

        # 3. Run Thread with streaming output
        your_assistant_id = os.getenv("DINGTALK_ASSISTANT_ID", "your_assistant_id_here")
        if your_assistant_id == "your_assistant_id_here":
            logger.error("Please set DINGTALK_ASSISTANT_ID environment variable or provide assistant_id directly in code to run example.")
        else:
            logger.info(f"Starting streaming run for Thread {thread_id} with Assistant ID: {your_assistant_id}...")
            
            # 使用生成器处理流式响应
            for event in dingtalk_api.create_run(
                thread_id, 
                assistant_id=your_assistant_id, 
                instructions="你好,请你作为一个知识库,回答用户的问题"
            ):
                if event['event_type'] == 'thread.message.delta':
                    # 实时打印增量文本
                    print(event['text'], end='', flush=True)
                elif event['event_type'] == 'thread.message.completed':
                    # 消息完成时打印换行
                    print()
                elif event['event_type'] == 'done':
                    # 流结束时打印最终消息列表
                    logger.info("Getting final message list...")
                    messages_response, messages_list = dingtalk_api.list_messages(thread_id, order="asc")
                    logger.info("Final message list:")
                    for msg in messages_list:
                        role = getattr(msg, 'role', 'unknown')
                        msg_id = getattr(msg, 'id', 'unknown')
                        content = getattr(msg, 'content', [])
                        text_value = 'No text content'
                        if content and 'text' in content[0] and 'value' in content[0]['text']:
                            text_value = content[0]['text']['value']
                        logger.info(f"  - [{role}] ({msg_id}): {text_value}")

    except Exception as e:
        logger.error(f"An error occurred: {str(e)}", exc_info=True)