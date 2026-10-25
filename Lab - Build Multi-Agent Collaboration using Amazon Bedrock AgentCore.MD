# Build Multi-Agent Collaboration using Amazon Bedrock AgentCore

Self notes from the lab *Build Multi-Agent Collaboration using Amazon Bedrock AgentCore* (SPL-TF-300-MLMULT-1). The lab builds a mortgage customer-support system made of four separate agents. Each one is deployed to its own AgentCore Runtime, and a supervisor agent calls the other three as tools.


| Step | Agent | File |
|---|---|---|
| 2.2 | Intent Classifier | [resources/intent_classifier.py](resources/intent_classifier.py) |
| 2.3 | Tech Specialist | [resources/tech_specialist.py](resources/tech_specialist.py) |
| 2.5 | Policy Specialist | [resources/policy_specialist.py](resources/policy_specialist.py) |
| 2.6 | Supervisor | [resources/supervisor.py](resources/supervisor.py) |
| all | Deployment helpers, tests, memory | [resources/lab_multiagent.ipynb](resources/lab_multiagent.ipynb) |

## Requirements



```
jupyter
ipywidgets
boto3
strands-agents
bedrock-agentcore
uv
```

| Package | Why it is needed |
|---|---|
| `jupyter` | Runs `lab_multiagent.ipynb` |
| `ipywidgets` | Notebook display support |
| `boto3` | AWS clients for AgentCore control and runtime, S3, Lambda, Bedrock Knowledge Bases and STS |
| `strands-agents` | The `Agent` and `@tool` classes used in every agent file |
| `bedrock-agentcore` | `BedrockAgentCoreApp` for the runtime entrypoint and `MemoryClient` for the supervisor's memory |
| `uv` | Used by `deploy_agent` to install arm64 dependencies for the runtime zip |

Install them in a fresh virtual environment (Python 3.13 is what the lab uses and what the runtimes are created with):

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r resources/requirements.txt
```

The lab's Code Editor already has these packages and AWS credentials. On my own machine the notebook would also need AWS credentials with access to AgentCore, S3, Lambda and Bedrock, plus the lab's pre-created resources, so it is not meant to run outside the lab.

## Architecture

```
Customer email
    └─> Supervisor Agent            (AgentCore Runtime, Nova Pro)
            ├─> Intent Classifier   (AgentCore Runtime, Nova Lite)   no tools
            ├─> Tech Specialist     (AgentCore Runtime, Nova Lite)
            │       ├─> EarlyCheckErrorCheckFunction   (Lambda)
            │       └─> DUSystemStatusCheckFunction    (Lambda)
            └─> Policy Specialist   (AgentCore Runtime, Nova Lite)
                    ├─> PolicySellingGuideKB           (Bedrock Knowledge Base)
                    └─> CaseLookupFunction             (Lambda)
```

| Agent | Role | Tools |
|---|---|---|
| Intent Classifier | Sorts an email into one of four mortgage support categories | None |
| Tech Specialist | Diagnoses problems with Desktop Underwriter (DU) and EarlyCheck | `check_earlycheck_error`, `check_du_system_status` (Lambda) |
| Policy Specialist | Answers Selling Guide questions and looks up support cases | `search_selling_guide` (Knowledge Base), `lookup_support_case` (Lambda) |
| Supervisor | Runs the other three and writes the final reply | `intent_classifier`, `tech_specialist`, `policy_specialist` (AgentCore endpoints) |

Key ideas:

- **Agents as tools.** The supervisor does not use a special multi-agent feature. Each specialist is wrapped in a `@tool` function that calls that agent's AgentCore Runtime endpoint and returns its answer as text.
- **AgentCore Runtime.** Each agent is a `.zip` file with an `entrypoint.py` and its dependencies, uploaded to S3 and deployed as a runtime. AgentCore handles cold starts, scaling and sessions. Each runtime gets its own ARN for invocation.
- **Different models for different jobs.** The specialists use Nova Lite. The supervisor uses Nova Pro because it routes requests and writes the final answer.

## Task 2.1: Setup

The notebook creates `boto3` clients for AgentCore control (`bedrock-agentcore-control`) and runtime (`bedrock-agentcore`), then I paste three values from the lab's left panel:

| Output | Variable |
|---|---|
| `AgentCoreExecutionRoleArn` | `EXECUTION_ROLE_ARN` |
| `KnowledgeBaseId` | `KNOWLEDGE_BASE_ID` |
| `DeployBucketName` | `S3_BUCKET` |

### The `deploy_agent` helper

What it does for each agent:

1. Copies pre-built **arm64** Python dependencies (AgentCore runs on Graviton), or installs them with `uv pip install --python-platform aarch64-manylinux2014 --python-version 3.13` if they are missing.
2. Reads `agents/<file>.py`, prepends `os.environ.setdefault(...)` lines for any environment variables, and saves it as `entrypoint.py`. This is how the Knowledge Base ID and the other agents' ARNs reach the code without hardcoding.
3. Zips the folder and uploads it to S3 (`ExpectedBucketOwner` is set as a safety check).
4. Calls `create_agent_runtime` with these settings:
   - `codeConfiguration` pointing at the S3 zip, `runtime: PYTHON_3_13`, `entryPoint: ["entrypoint.py"]`
   - `networkMode: PUBLIC`
   - `roleArn` set to the execution role
   - `lifecycleConfiguration`: idle session timeout 300 seconds, maximum lifetime 1800 seconds
5. Polls `get_agent_runtime` every 10 seconds (up to 5 minutes) until the status is `READY`.

### The `invoke_agent` helper

Calls `invoke_agent_runtime` with `qualifier="DEFAULT"`, a new `runtimeSessionId` (a UUID) and a JSON payload `{"prompt": ...}`, then reads `result` from the response. It retries once after 30 seconds if the runtime is still cold-starting ("initialization time exceeded").

### The `delete_runtime` helper

If I deploy before finishing a `.py` file, the runtime has broken code. `delete_runtime("agent_name")` lists runtimes, finds the one with that name, and deletes it so I can fix the file and redeploy. No lab restart is needed.

## Task 2.2: Intent Classifier

File: [resources/intent_classifier.py](resources/intent_classifier.py). No tools, only a strict system prompt.

Four categories the prompt defines:

| Category | Examples |
|---|---|
| System & Technology Issues | DU access, EarlyCheck or Collateral Underwriter problems, login issues |
| Underwriting & Eligibility Questions | DU findings, program eligibility, borrower scenarios |
| Policy & Guidelines Clarification | Selling Guide interpretation, documentation, income calculation |
| Loan Delivery & Purchase Issues | Delivery errors, missing documents, post-purchase adjustments |

The prompt requires output in this shape, and `UNKNOWN` for anything else:

```json
{ "category": "", "subcategory": "" }
```

```python
agent = Agent(model=nova_lite, system_prompt=SYSTEM_PROMPT)
```

Test: "I'm having trouble accessing Desktop Underwriter. I keep getting Connection failed." returned `System & Technology Issues` / `Desktop Underwriter (DU) access problems`.

**Observation:** the model wrapped the JSON in a Markdown code fence (` ```json ... ``` `). The prompt asks for strict output, but any code that parses the reply as JSON would need to strip the fence or ask for a structured output schema.

## Task 2.3: Tech Specialist

File: [resources/tech_specialist.py](resources/tech_specialist.py). Two Lambda-backed tools.

```python
@tool
def check_earlycheck_error(error_code: str) -> str:
    """Looks up an EarlyCheck error code and returns description,
    severity, and resolution steps."""
    response = lambda_client.invoke(
        FunctionName="create-customer-resources-EarlyCheckErrorCheckFunction",
        InvocationType="RequestResponse",
        Payload=json.dumps({"parameters": [{"name": "error_code", "value": error_code}]}),
    )
    body = json.loads(response["Payload"].read())
    return body.get("body", str(body))

@tool
def check_du_system_status() -> str:
    """Retrieves the current operational status of the Desktop Underwriter (DU)
    system, including known issues or scheduled maintenance."""
    ...  # same pattern with DUSystemStatusCheckFunction and an empty payload

agent = Agent(
    model=nova_lite,
    system_prompt=SYSTEM_PROMPT,
    tools=[check_earlycheck_error, check_du_system_status],
)
```

The system prompt says to check DU status for DU issues, look up an error code when one is given, and give clear, sequential troubleshooting steps. The Lambda payload format is `{"parameters": [{"name": ..., "value": ...}]}`. The docstring becomes the tool description the model uses to pick the tool.

**What happened in my run:** the test for `EC-405` did not return the Lambda's answer. The agent reported an AWS permissions error when it tried the lookup, and then explained EC-405 as "Income Verification Failed" from its own knowledge. The lab's expected output says EC-405 is a document format failure (invalid file format). So the explanation the agent gave was not backed by the tool.

## Task 2.4: Knowledge base check

`bedrock-agent` `get_knowledge_base` showed `PolicySellingGuideKB` with status `ACTIVE`. If it says `CREATING`, wait 1 to 2 minutes.

## Task 2.5: Policy Specialist

File: [resources/policy_specialist.py](resources/policy_specialist.py).

```python
@tool
def search_selling_guide(query: str) -> str:
    """Searches the Selling Guide knowledge base for policy information
    relevant to the query. Returns relevant excerpts with source references."""
    response = bedrock_agent_runtime.retrieve(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        retrievalQuery={"text": query},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 5}},
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

# lookup_support_case(case_number) invokes CaseLookupFunction the same way as the tech tools

agent = Agent(
    model=nova_lite,
    system_prompt=SYSTEM_PROMPT,
    tools=[search_selling_guide, lookup_support_case],
)
```

- `retrieve` runs a vector similarity search and returns the 5 most relevant chunks, each with its source location. This is the same Retrieve API I used in my customer support agent project.
- The system prompt has an **authorized actions** list (search the guide, look up a case, cite sections and dates) and a **prohibited** list (no new policy interpretations, no eligibility decisions, no unofficial guidance). It also says to always cite the guide section and effective date.
- `KNOWLEDGE_BASE_ID` is injected as an environment variable at deploy time.

Test: "What are the requirements for HomeReady mortgage programs regarding homebuyer education?" returned a cited answer that referenced `B2-2-06` (Homeownership Education and Housing Counseling, 04/02/2025) and pointed to `B5-6-01` (HomeReady eligibility, 06/04/2025). This one worked as intended.

## Task 2.6: Supervisor

File: [resources/supervisor.py](resources/supervisor.py).

```python
@tool
def intent_classifier(email_content: str) -> str:
    """Classifies the intent of an incoming customer email into a mortgage support
    category. Always call this first for any new customer request."""
    return _invoke_specialist(INTENT_CLASSIFIER_ARN, email_content)

@tool
def tech_specialist(technical_issue: str) -> str:
    """Handles technical issues related to mortgage processing systems such as
    Desktop Underwriter and EarlyCheck. Use when intent is 'System & Technology Issues'."""
    return _invoke_specialist(TECH_SPECIALIST_ARN, technical_issue)

@tool
def policy_specialist(policy_question: str) -> str:
    """Handles policy questions and support case lookups using the Selling Guide
    knowledge base. Use when intent is 'Policy & Guidelines Clarification' or
    'Underwriting & Eligibility Questions'."""
    return _invoke_specialist(POLICY_SPECIALIST_ARN, policy_question)

agent = Agent(
    model=nova_pro,
    system_prompt=SYSTEM_PROMPT,
    tools=[intent_classifier, tech_specialist, policy_specialist],
)
```

Coordination rules in the system prompt:

1. Always call `intent_classifier` first.
2. System & Technology Issues go to `tech_specialist`. Policy & Guidelines Clarification and Underwriting & Eligibility Questions go to `policy_specialist`. `UNKNOWN` gets a short "cannot answer" reply.
3. Turn the specialist's answer into a natural, professional email reply.
4. Do not skip classification, do not mention any company name, do not restate what the customer said.

`_invoke_specialist` is already in the file. It sends the prompt to the runtime's ARN and returns the response string. The three specialist ARNs and the memory ID are injected as environment variables.

### Supervisor memory

Before deploying the supervisor, the notebook creates AgentCore Memory (`SupervisorSessionMemory`) with two strategies:

| Strategy | Namespace template |
|---|---|
| `summaryMemoryStrategy` (SessionSummarizer) | `/summaries/{actorId}/{sessionId}/` |
| `semanticMemoryStrategy` (FactExtractor) | `/facts/{actorId}/` |

This call uses `namespaceTemplates` for the namespaces, which matches the field name I handled in my customer support agent.

## Task 3: Tests through the supervisor

| Test | Email | Expected flow | Result in my run |
|---|---|---|---|
| 1 | DU "Connection failed" from Sarah | classifier, then tech specialist | A long email reply with troubleshooting steps (see notes below) |
| 2 | HomeReady homebuyer education questions from Michael | classifier, then policy specialist | A policy reply about mandatory education, course types and timing |
| 3 | Hotel recommendations in Seattle | classifier returns `UNKNOWN`, no specialist | A polite refusal |

What I noticed:

- **Test 1 contained invented advice.** The tool lookup failed with an authorization error. The reply admitted a backend authorization error, but it then added troubleshooting details nobody supplied (such as using a DU mobile app, trying off-peak hours after 5 PM, and using EarlyCheck as a workaround). The lab's expected output says DU is operational. The tool result was not available, so the model filled the gap with plausible text.
- **Test 2** ended with `[Your Name]`, a template placeholder. The reply also states a timing rule for post-purchase counseling that I cannot verify against the search results shown.
- **Test 3** worked, but the reply restated the request ("hotel recommendations ... travel-related") even though the prompt said no further explanation was needed.
- **Reasoning text leaked.** Some replies started with `<thinking> ... </thinking>`. A customer-facing system should strip that.
- **Bonus memory test:** turn 1 ("look up case number 4567890123") replied that it could not assist, and turn 2 failed with an authorization error from a service control policy when the case lookup ran. So the case lookup never succeeded, and the memory demo did not show recall in my run.

The authorization errors came from the lab account's permissions for the Lambda calls. The knowledge base path worked, and the Lambda paths did not.

## Lessons learned

- Splitting work across agents with narrow prompts keeps each prompt short and testable. Each specialist can be tested alone (the notebook does this before wiring in the supervisor).
- Calling a deployed agent from another agent is just a tool call, and the supervisor's tool docstrings decide the routing, so they need to say when to use each tool.
- Environment variables injected at deploy time keep ARNs and IDs out of the code.
- A runtime created from unfinished code can be deleted and recreated, so mistakes during deployment are cheap.
- When a tool fails, a model may still answer confidently. Tests should check that the answer matches the tool result, not only that an answer came back.
- Specialist outputs pass through the supervisor, so errors and invented details can travel up the chain.

## Production considerations

- **Fail loudly.** The system prompts should say "if a tool fails or returns nothing, say so and do not guess". For tool failures in a regulated area like mortgages, route to a human instead.
- **Ground the answers.** The policy agent is told to cite sections and dates. Automated checks should confirm the cited text appears in the retrieved chunks.
- **Structured output.** Use a schema or strip code fences before parsing the classifier's JSON.
- **Hide internal reasoning.** Remove `<thinking>` blocks and template placeholders such as `[Your Name]` before a reply goes to a customer.
- **Latency and cost.** Each customer email makes several model calls (classifier, specialist, supervisor) and can hit cold starts. The runtime settings (idle timeout 5 minutes, maximum lifetime 30 minutes) affect both.
- **Security and compliance.** Emails can contain personal and financial data. Add guardrails, log carefully, scope the execution role to the three Lambdas, the knowledge base and the model, and consider authentication between agents.
- **Memory.** Use a per-customer actor ID so facts and summaries stay separate between customers.
- **Cleanup.** Delete the four runtimes and the memory resource when finished, using `delete_runtime(...)` for the runtimes.




