import readline
from mcp import StdioServerParameters, stdio_client
from strands import Agent, tool
from strands.tools.mcp import MCPClient
from strands_tools import file_write
from strands.models import BedrockModel

import boto3

# Create a custom boto3 session
session = boto3.Session(region_name="us-east-1")

# Create a Bedrock model with the custom session
nova_lite = BedrockModel(model_id="amazon.nova-lite-v1:0", boto_session=session)

def aws_researcher(query: str) -> str:
    # Add MCP client
    documentation_mcp_server = MCPClient(
        lambda: stdio_client(
            StdioServerParameters(
                command="uvx", args=["awslabs.aws-documentation-mcp-server"]
            )
        )
    )


    # Add code to setup the MCP server's tools
    with documentation_mcp_server:
        tools = documentation_mcp_server.list_tools_sync() + [file_write]


        # Create the research agent with specific capabilities
        aws_documentation_agent = Agent(
            model=nova_lite,
            system_prompt="""You are a thorough AWS researcher specialized in finding accurate 
            information online. For each question:
            
            1. Determine what information you need
            2. Search the AWS Documentation for reliable information
            3. Extract key information and cite your sources
            4. Store important findings in memory for future reference
            5. Synthesize what you've found into a clear, comprehensive answer
            
            When researching, focus only on AWS documentation. Always provide citations 
            for the information you find.
            """,
            tools=tools,
        )


        # Invoke the agent and return the response
        response = aws_documentation_agent(query)
        return str(response)



if __name__ == "__main__":
    aws_researcher("What is Amazon Bedrock")