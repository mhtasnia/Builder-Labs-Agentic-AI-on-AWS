"""
Intent Classification Agent — Task 2.2
Follow the instructions in lab.ipynb to complete this file.
"""

import boto3
from strands import Agent
from strands.models import BedrockModel
from bedrock_agentcore.runtime import BedrockAgentCoreApp

session = boto3.Session(region_name="us-east-1")
nova_lite = BedrockModel(model_id="us.amazon.nova-2-lite-v1:0", boto_session=session)

# TODO Step 1: Replace SYSTEM_PROMPT = "<YOUR SYSTEM PROMPT HERE>" with the full system prompt from the instructions.
SYSTEM_PROMPT = """You are an email categorization agent for mortgage customer support.
    Analyze the incoming email and classify it into the appropriate category.

    CATEGORIES:
    1. System & Technology Issues
    - Desktop Underwriter (DU) access problems
    - Technical issues with platforms (EarlyCheck, Collateral Underwriter)
    - Login or credential issues
    2. Underwriting & Eligibility Questions
    - DU findings interpretation
    - Loan program eligibility questions
    - Borrower qualification scenarios
    3. Policy & Guidelines Clarification
    - Selling Guide interpretation
    - Documentation requirements
    - Income calculation questions
    4. Loan Delivery & Purchase Issues
    - Loan delivery errors
    - Missing documentation
    - Post-purchase adjustment requests

    OUTPUT FORMAT (strictly follow this):
    {
        "category": "",
        "subcategory": ""
    }

    IMPORTANT: If the incoming text doesn't fall under any of the given categories, respond with:
    {
        "category": "UNKNOWN",
        "subcategory": "UNKNOWN"
    }
"""


# TODO Step 2: Create the agent using nova_lite and SYSTEM_PROMPT.
agent = Agent(model=nova_lite, system_prompt=SYSTEM_PROMPT)

# ── AgentCore entrypoint (do not modify) ──────────────────────────────────
app = BedrockAgentCoreApp()


@app.entrypoint
def agent_invocation(payload, context):
    email_content = payload.get("prompt", "No email content provided.")
    result = agent(email_content)
    return {"result": str(result)}


if __name__ == "__main__":
    app.run()
