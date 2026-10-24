"""
Supervisor Agent — Task 2.6
Follow the instructions in lab.ipynb to complete this file.
"""
import json
import os
import boto3
from strands import Agent, tool
from strands.models import BedrockModel
from bedrock_agentcore.runtime import BedrockAgentCoreApp

# Supervisor uses Nova Pro for stronger orchestration reasoning
session = boto3.Session(region_name="us-east-1")
nova_pro = BedrockModel(model_id="amazon.nova-pro-v1:0", boto_session=session)

agentcore_client = boto3.client("bedrock-agentcore", region_name="us-east-1")

# Injected at deploy time — do not hardcode
INTENT_CLASSIFIER_ARN = os.environ.get("INTENT_CLASSIFIER_ARN", "")
TECH_SPECIALIST_ARN   = os.environ.get("TECH_SPECIALIST_ARN", "")
POLICY_SPECIALIST_ARN = os.environ.get("POLICY_SPECIALIST_ARN", "")


def _invoke_specialist(agent_arn: str, prompt: str) -> str:
    """Invoke a deployed AgentCore Runtime endpoint and return the result string."""
    import uuid
    response = agentcore_client.invoke_agent_runtime(
        agentRuntimeArn=agent_arn,
        qualifier="DEFAULT",
        runtimeSessionId=str(uuid.uuid4()),
        payload=json.dumps({"prompt": prompt}),
    )
    raw = response["response"].read()
    return json.loads(raw).get("result", str(raw))


# TODO Step 1: Add all three @tool functions below (intent_classifier, tech_specialist,
# policy_specialist). Each calls _invoke_specialist with the matching ARN.
@tool
def intent_classifier(email_content: str) -> str:
    """
    Classifies the intent of an incoming customer email into a mortgage support
    category. Always call this first for any new customer request.

    Args:
        email_content: The full text of the customer email.
    """
    return _invoke_specialist(INTENT_CLASSIFIER_ARN, email_content)


@tool
def tech_specialist(technical_issue: str) -> str:
    """
    Handles technical issues related to mortgage processing systems such as
    Desktop Underwriter and EarlyCheck. Use when intent is 'System & Technology Issues'.

    Args:
        technical_issue: Description of the technical problem.
    """
    return _invoke_specialist(TECH_SPECIALIST_ARN, technical_issue)


@tool
def policy_specialist(policy_question: str) -> str:
    """
    Handles policy questions and support case lookups using the Selling Guide
    knowledge base. Use when intent is 'Policy & Guidelines Clarification' or
    'Underwriting & Eligibility Questions'.

    Args:
        policy_question: The policy question or case lookup request.
    """
    return _invoke_specialist(POLICY_SPECIALIST_ARN, policy_question)



# TODO Step 2: Replace SYSTEM_PROMPT = "<YOUR SYSTEM PROMPT HERE>" with the supervisor system prompt.
SYSTEM_PROMPT = """You are a Supervisor Agent coordinating between 3 specialized mortgage
    support agents. Review incoming emails and orchestrate responses.

    COORDINATION RULES:
    1. Always call intent_classifier first to determine the category
    2. Based on category, engage the appropriate specialist:
    - 'System & Technology Issues' → tech_specialist
    - 'Policy & Guidelines Clarification' or 'Underwriting & Eligibility Questions' → policy_specialist
    - 'UNKNOWN' → respond that you cannot answer the question, no further explanation needed
    3. Synthesize the specialist response into a natural, professional email reply

    DO NOT:
    - Skip classification
    - Mention any organization or company name in the response
    - Restate what the customer said in the reply
"""


# TODO Step 3: Create the agent with nova_pro, SYSTEM_PROMPT, and all three tools.
agent = Agent(
    model=nova_pro,
    system_prompt=SYSTEM_PROMPT,
    tools=[intent_classifier, tech_specialist, policy_specialist],
)

# ── AgentCore entrypoint (do not modify) ──────────────────────────────────
app = BedrockAgentCoreApp()

@app.entrypoint
def agent_invocation(payload, context):
    email_content = payload.get("prompt", "No email content provided.")
    result = agent(email_content)
    return {"result": str(result)}

if __name__ == "__main__":
    app.run()
