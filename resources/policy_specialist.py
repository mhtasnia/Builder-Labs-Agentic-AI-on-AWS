"""
Policy Specialist Agent — Task 2.5
Follow the instructions in lab.ipynb to complete this file.
"""
import json
import os
import boto3
from strands import Agent, tool
from strands.models import BedrockModel
from bedrock_agentcore.runtime import BedrockAgentCoreApp

session = boto3.Session(region_name="us-east-1")
nova_lite = BedrockModel(model_id="us.amazon.nova-2-lite-v1:0", boto_session=session)
lambda_client = boto3.client("lambda", region_name="us-east-1")
bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", region_name="us-east-1")

# Injected at deploy time — do not hardcode
KNOWLEDGE_BASE_ID = os.environ.get("KNOWLEDGE_BASE_ID", "")


# ── Tool 1: Selling Guide knowledge base search ───────────────────────────
# TODO Step 1: Add the complete search_selling_guide @tool function here.
@tool
def search_selling_guide(query: str) -> str:
    """
    Searches the Selling Guide knowledge base for policy information
    relevant to the query. Returns relevant excerpts with source references.

    Args:
        query: The policy question or topic to search for.
    """
    response = bedrock_agent_runtime.retrieve(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        retrievalQuery={"text": query},
        retrievalConfiguration={
            "vectorSearchConfiguration": {"numberOfResults": 5}
        },
    )
    results = response.get("retrievalResults", [])
    if not results:
        return "No relevant policy information found."
    formatted = []
    for i, r in enumerate(results, 1):
        content = r.get("content", {}).get("text", "")
        source = r.get("location", {}).get("s3Location", {}).get("uri", "")
        formatted.append(f"[Result {i}] Source: {source}\n{content}")
    return "\n\n".join(formatted)



# ── Tool 2: Support case lookup ───────────────────────────────────────────
# TODO Step 2: Add the complete lookup_support_case @tool function here.
@tool
def lookup_support_case(case_number: str) -> str:
    """
    Retrieves details for a specific support case using the case number.

    Args:
        case_number: The support case number (e.g., 4567890123).
    """
    response = lambda_client.invoke(
        FunctionName="create-customer-resources-CaseLookupFunction",
        InvocationType="RequestResponse",
        Payload=json.dumps({
            "parameters": [{"name": "case_number", "value": case_number}]
        }),
    )
    body = json.loads(response["Payload"].read())
    return body.get("body", str(body))



# ── System prompt ─────────────────────────────────────────────────────────
# TODO Step 3: Replace the placeholder with the policy specialist system prompt.
SYSTEM_PROMPT = """You are a mortgage policy support agent specializing in Selling Guide
    interpretations and guidelines clarification.

    AUTHORIZED ACTIONS:
    - Search the Selling Guide knowledge base for published policy information
    - Look up support case details when a case number is provided
    - Reference specific guide sections and effective dates

    PROHIBITED:
    - Do NOT create new policy interpretations
    - Do NOT make eligibility determinations
    - Do NOT provide unofficial guidance

    Always cite the guide section and effective date in your response.
"""


# ── Agent ─────────────────────────────────────────────────────────────────
# TODO Step 4: Create the agent with nova_lite, SYSTEM_PROMPT, and both tools.
agent = Agent(
    model=nova_lite,
    system_prompt=SYSTEM_PROMPT,
    tools=[search_selling_guide, lookup_support_case],
)

# ── AgentCore entrypoint (do not modify) ──────────────────────────────────
app = BedrockAgentCoreApp()

@app.entrypoint
def agent_invocation(payload, context):
    query = payload.get("prompt", "No policy question provided.")
    result = agent(query)
    return {"result": str(result)}

if __name__ == "__main__":
    app.run()
