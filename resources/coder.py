from mcp import StdioServerParameters, stdio_client
from strands import Agent, tool
from strands.tools.mcp import MCPClient
from strands.models import BedrockModel
from strands_tools import file_read, file_write, python_repl

import boto3

# Create a custom boto3 session
session = boto3.Session(region_name="us-east-1")

# Create a Bedrock model with the custom session
lite_model = BedrockModel(model_id="amazon.nova-lite-v1:0", boto_session=session)

@tool
def coder(query: str) -> str:
    try:
        coder_agent = Agent(
            model=lite_model,
            system_prompt="You are a helpful assistant. You can read from the local file system and write code",
            tools=[
                file_read,
                file_write,
            ],
        )
        # Call the agent and return its response
        response = coder_agent(query)

        return str(response)
    except Exception as e:
        return f"Error in coder: {str(e)}"
