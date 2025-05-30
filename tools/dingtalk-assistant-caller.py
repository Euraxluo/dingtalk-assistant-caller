from collections.abc import Generator
import os
import time
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.config.logger_format import plugin_logger_handler

# Import DingTalk API client
from tools.dingtalk import dingtalk_api

# Set up logger
import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
# 检查是否已经有处理器，如果没有才添加
# logger.addHandler(plugin_logger_handler)

class DingtalkAssistantCallerTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        """Call DingTalk AI Assistant to get response"""
        try:
            # Get user query
            query = tool_parameters.get("query", "")
            if not query:
                logger.warning("Received empty query")
                yield self.create_text_message("Error: Question cannot be empty")
                return

            # Get instructions
            instructions = tool_parameters.get("instructions", "")
            if not instructions:
                logger.warning("No instructions provided, using default instructions")

            # Get environment variables
            assistant_id = os.getenv("DINGTALK_ASSISTANT_ID")
            if not assistant_id:
                logger.error("DINGTALK_ASSISTANT_ID environment variable not set")
                yield self.create_text_message("Error: DINGTALK_ASSISTANT_ID environment variable not set")
                return

            logger.info(f"Starting to process user query: {query}")

            # 1. Create session
            thread, thread_id = dingtalk_api.create_thread()
            logger.info(f"Successfully created new session, Thread ID: {thread_id}")

            try:
                # 2. Send user message
                user_message, message_id = dingtalk_api.create_message(
                    thread_id=thread_id,
                    role="user",
                    content=query
                )
                logger.info(f"Successfully sent user message, Message ID: {message_id}")

                # 3. Run session with streaming
                logger.info(f"Starting streaming run for Thread {thread_id}")
                yield_context = ""
                processed_events = set()  # 用于追踪已处理的事件
                
                # 打印instructions
                logger.info(f"instructions :{instructions}")
                for event in dingtalk_api.create_run(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    instructions=instructions
                ):
                    event_type = event.get('event_type')
                    data = event.get('data')
                    text = event.get('text')
                    
                    # 直接打印事件信息
                    print(f"\n=== Event Debug ===")
                    print(f"Event Type: {event_type}")
                    print(f"Text: {text}")
                    print(f"Data: {data}")
                    print(f"================\n")
                    
                    # 记录每个事件的详细信息
                    logger.debug(f"Received event: type={event_type}, text={text}, data={data}")
                    
                    # 生成事件唯一标识
                    event_id = f"{event_type}_{text}"
                    if event_id in processed_events:
                        logger.debug(f"Skipping duplicate event: {event_id}")
                        continue
                    processed_events.add(event_id)
                    
                    if event_type == 'thread.message.delta':
                        # 使用流式变量返回增量文本
                        if text:
                            print(f"Yielding delta text: {text}")
                            yield self.create_text_message(text[len(yield_context):])
                            yield_context = text
                            
                    elif event_type == 'thread.message.completed':
                        print("Message completed")
                            
                    elif event_type == 'thread.run.completed':
                        status = data.get('statusEnum') if data else None
                        logger.info(f"Run completed with status: {status}")
                        if status == 'FAILED':
                            error_msg = data.get('lastError', {}).get('message', 'Unknown error')
                            logger.error(f"Run failed: {error_msg}")
                            yield self.create_text_message(f"AI processing failed: {error_msg}")
                            return
                            
                    elif event_type == 'done':
                        logger.info("Stream completed")
                        break

            finally:
                # Cleanup: Delete session
                try:
                    dingtalk_api.delete_thread(thread_id)
                    logger.info(f"Successfully cleaned up session {thread_id}")
                except Exception as e:
                    logger.error(f"Failed to clean up session: {str(e)}")

        except Exception as e:
            logger.error(f"Error occurred during processing: {str(e)}", exc_info=True)
            yield self.create_text_message(f"An error occurred: {str(e)}") 
            return