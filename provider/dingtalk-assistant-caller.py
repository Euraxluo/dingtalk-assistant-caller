import os
from typing import Any

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError
from dify_plugin.config.logger_format import plugin_logger_handler

# Set up logger
import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(plugin_logger_handler)

class DingtalkAssistantCallerProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        try:
            """Validate DingTalk credentials"""
            logger.info("Starting to validate DingTalk credentials")
            required_vars = {
                "app_key": "DINGTALK_APP_KEY",
                "app_secret": "DINGTALK_APP_SECRET",
                "assistant_id": "DINGTALK_ASSISTANT_ID"
            }
            
            # Set environment variables
            for key, env_var in required_vars.items():
                if key not in credentials:
                    logger.error(f"Missing required credential: {key}")
                    raise ValueError(f"Missing required credential: {key}")
                os.environ[env_var] = credentials[key]
                logger.info(f"Set environment variable {env_var}")
            
            logger.info("DingTalk credentials validated successfully")
        except Exception as e:
            logger.error(f"DingTalk credentials validation failed: {str(e)}", exc_info=True)
            raise ToolProviderCredentialValidationError(str(e))