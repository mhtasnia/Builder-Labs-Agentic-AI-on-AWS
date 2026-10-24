"""
Tech Specialist Agent — Task 2.3
Follow the instructions in lab.ipynb to complete this file.
"""

import json
import boto3
from strands import Agent, tool
from strands.models import BedrockModel
from bedrock_agentcore.runtime import BedrockAgentCoreApp

session = boto3.Session(region_name="us-east-1")
nova_lite = BedrockModel(model_id="us.amazon.nova-2-lite-v1:0", boto_session=session)
lambda_client = boto3.client("lambda", region_name="us-east-1")


# ── Tool 1: EarlyCheck error lookup ───────────────────────────────────────
# TODO Step 1: Add the complete check_earlycheck_error @tool function here.
@tool
def check_earlycheck_error(error_code: str) -> str:
    """
    Looks up an EarlyCheck error code and returns description,
    severity, and resolution steps.

    Args:
        error_code: The EarlyCheck error code to look up (e.g., EC-405).
    """
    response = lambda_client.invoke(
        FunctionName="create-customer-resources-EarlyCheckErrorCheckFunction",
        InvocationType="RequestResponse",
        Payload=json.dumps(
            {"parameters": [{"name": "error_code", "value": error_code}]}
        ),
    )
    body = json.loads(response["Payload"].read())
    return body.get("body", str(body))


# ── Tool 2: DU system status ──────────────────────────────────────────────
# TODO Step 2: Add the complete check_du_system_status @tool function here.
@tool
def check_du_system_status() -> str:
    """
    Retrieves the current operational status of the Desktop Underwriter (DU)
    system, including known issues or scheduled maintenance.
    """
    response = lambda_client.invoke(
        FunctionName="create-customer-resources-DUSystemStatusCheckFunction",
        InvocationType="RequestResponse",
        Payload=json.dumps({}),
    )
    body = json.loads(response["Payload"].read())
    return body.get("body", str(body))


# ── System prompt ─────────────────────────────────────────────────────────
# TODO Step 3: Replace the placeholder with the tech specialist system prompt.
SYSTEM_PROMPT = """You are a technical support agent specializing in mortgage system issues.
    Your role is to provide troubleshooting guidance and system status information.

    PRIMARY SYSTEMS: Desktop Underwriter (DU), EarlyCheck, Collateral Underwriter.

    For each request:
    1. Check DU system status if the issue relates to DU
    2. Look up the error code if one is provided
    3. Provide clear, sequential troubleshooting steps
"""


# ── Agent ─────────────────────────────────────────────────────────────────
# TODO Step 4: Create the agent with nova_lite, SYSTEM_PROMPT, and both tools.
agent = Agent(
    model=nova_lite,
    system_prompt=SYSTEM_PROMPT,
    tools=[check_earlycheck_error, check_du_system_status],
)

# ── AgentCore entrypoint (do not modify) ──────────────────────────────────
app = BedrockAgentCoreApp()


@app.entrypoint
def agent_invocation(payload, context):
    query = payload.get("prompt", "No issue description provided.")
    result = agent(query)
    return {"result": str(result)}


if __name__ == "__main__":
    app.run()
