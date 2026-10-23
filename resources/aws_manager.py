import readline
import time
from mcp import StdioServerParameters, stdio_client
from strands import Agent, tool
from strands.tools.mcp import MCPClient
from strands.models import BedrockModel
from strands_tools import file_read
import os
import boto3

# Create a custom boto3 session
session = boto3.Session(region_name="us-east-1")

# Create a Bedrock model with the custom session
lite_model = BedrockModel(model_id="amazon.nova-lite-v1:0", boto_session=session)


@tool
def sleep() -> str:
    time.sleep(10)
    return "Slept for 10 seconds. Time to re-check status"

@tool
def aws_manager(query: str) -> str:
    # Connect to an MCP server using stdio transport
    stdio_mcp_client = MCPClient(
        lambda: stdio_client(
            StdioServerParameters(
                command="uvx",
                args=["awslabs.aws-api-mcp-server@latest"],
                env={"AWS_API_MCP_WORKING_DIR": os.getcwd()},
            )
        )
    )

    # Create an agent with MCP tools
    with stdio_mcp_client:
        # Get the tools from the MCP server
        tools = stdio_mcp_client.list_tools_sync() + [file_read, sleep]

        # Create an agent with these tools
        aws_manager_agent = Agent(
            model=lite_model,
            tools=tools,
            system_prompt="""You are an AWS operations assistant with access to multiple AWS services.

                When handling requests:
                - For all AWS operations: Use the AWS API MCP tools
                - For file operations: Use the file_read tool
                - To sleep: Use the sleep tool

                Example uses:
                - "Create an EC2 instance" → use the AWS API MCP tools
                - "Query DynamoDB table" → use the AWS API MCP tools
                - "Read configuration file" → use file_read tool
                - "Sleep for 10 seconds" → use sleep tool""",
        )
        return aws_manager_agent(query)


if __name__ == "__main__":
    print("Welcome to AWS Manager. Type 'exit' to quit or press Ctrl+C.")
    try:
        while True:
            try:
                query = input("Enter your prompt: ")
                if query.lower() == "exit":
                    print("Exiting AWS Manager. Goodbye!")
                    break
                result = aws_manager(query)
                print("Response:", result)
            except Exception as e:
                print(f"An error occurred: {e}")
    except KeyboardInterrupt:
        print("\nReceived keyboard interrupt. Exiting AWS Manager. Goodbye!")
