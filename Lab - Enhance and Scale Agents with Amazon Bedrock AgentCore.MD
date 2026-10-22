# Amazon Bedrock AgentCore Lab Notes

Notes from the guided lab on building a production-ready customer support agent with Strands Agents, AgentCore Memory, AgentCore Gateway and AgentCore Identity.

The full working code and outputs are in the notebook: **[notebook _Enhance and Scale Agents with Amazon Bedrock AgentCore.ipnyb](notebook _Enhance and Scale Agents with Amazon Bedrock AgentCore.ipnyb)**. Each section below says which part of the notebook it comes from.

## What the lab builds

The agent grows in three stages, one per notebook task:

| Stage | Notebook task | What is added | Limitation it fixes |
|---|---|---|---|
| 1. Basic agent | Task 1.1 | Strands agent with four local `@tool` functions and a system prompt | n/a (starting point) |
| 2. Memory | Task 1.2 | AgentCore Memory with USER_PREFERENCE and SEMANTIC strategies, plus hooks | The agent forgot customers between sessions |
| 3. Gateway and Identity | Task 1.3 | Tools moved behind an MCP Gateway secured with JWT (Cognito) | Local-only tools, no shared or secured tool layer |

## Task 1.1: Basic agent (Strands)

- An agent is a foundation model, a system prompt, and tools.
- Tools are plain Python functions with the `@tool` decorator. The docstring is what the model reads to decide when to call the tool.
- The four local tools were `get_product_info`, `get_return_policy`, `get_technical_support` and `web_search`. They return mock data.
- Flow of one request: analyze the query, pick a tool, call it, then combine the result into an answer.
- Test: "What's the return policy for laptops?" called `get_return_policy` and returned the 30-day policy.

## Task 1.2: AgentCore Memory

**Two levels of memory**

- **Short-term:** the current conversation. Strands handles this automatically.
- **Long-term:** facts and preferences extracted across sessions. This is the AgentCore Memory service.

**Strategies and namespaces**

| Strategy | Stores | Namespace used |
|---|---|---|
| USER_PREFERENCE | Preferences and behaviour | `support/customer/{actorId}/preferences` |
| SEMANTIC | Facts from conversations | `support/customer/{actorId}/semantic` |

- `{actorId}` is the customer ID, so each customer's memories are kept apart.
- The memory resource was created with `create_memory_and_wait` and `event_expiry_days=90`. Its ID was saved in SSM Parameter Store.
- Past conversations were seeded with `create_event`. Extraction into long-term memory happens in the background, which is why the notebook waits 60 seconds.

**Memory hooks (`HookProvider`)**

- `retrieve_customer_context` runs on `MessageAddedEvent`. It queries each strategy namespace and prepends the results to the user message as `Customer Context:`.
- `save_support_interaction` runs on `AfterInvocationEvent`. It finds the last user query and assistant reply and calls `create_event`.
- `register_hooks` connects both callbacks to the agent.
- Only plain-text user messages are enriched. Tool results are skipped.

**What I noticed in the output**

- The memory test ("What are my laptop preferences?") did not recall the seeded ThinkPad and Linux preferences. The agent asked clarifying questions instead.
- Likely reasons: extraction had not finished, or the lookup returned nothing relevant. It is a useful reminder that memory extraction is asynchronous and recall is not guaranteed immediately.
- The notebook hook saves the enriched message (with `Customer Context:` attached) as the customer's query. In my own project I kept the original query separately so memory does not fill with its own recalled text.

## Task 1.3: Gateway and Identity

**AgentCore Gateway**

- A managed MCP (Model Context Protocol) server. It exposes Lambda functions and APIs to agents as tools through one endpoint.
- Benefits: no server to run, one interface for many tools, centralized auth, reusable across agents.
- One Lambda (`CustomerSupportLambda`) serves several tools. The Gateway passes the tool name in the Lambda context and the parameters in the event, and the Lambda routes to the right handler.
- Tools were defined with an inline JSON schema (`check_warranty_status` and `web_search`). The target was named `LambdaTarget`.
- Gateway tools show up to the model with the target name as a prefix, for example `LambdaTarget___web_search`.

**Inbound authentication (AgentCore Identity with Cognito)**

```
Agent   -> Cognito : client_id + client_secret
Cognito -> Agent   : JWT access token
Agent   -> Gateway : Authorization: Bearer <token>
Gateway -> Cognito : validate token and allowed client
Gateway -> Agent   : access granted
```

- The Gateway used `authorizerType="CUSTOM_JWT"` with a `customJWTAuthorizer` containing `allowedClients` and a `discoveryUrl`.
- The agent fetched a token with the OAuth 2.0 client credentials flow and sent it as a Bearer header through `MCPClient`.
- Credentials were kept in SSM Parameter Store and never hard-coded.
- Outbound auth (for third-party tools) was not used in this lab, so the Identity page's Outbound Auth section was empty.

**Final agent**

- Hybrid setup: three local tools plus the gateway tools, five tools total.
- Tests: web search for iPhone 15 troubleshooting, a warranty check for serial `ABC12345678` (returned an expired extended warranty), and a combined memory plus web search for gaming headphones.

## Console tour (Task 2)

| Where | What it shows |
|---|---|
| Bedrock AgentCore, Memory, `CustomerSupportMemory` | The two long-term strategies, plus an Observability section with memory metrics |
| Identity | Inbound auth only. Outbound Auth is empty |
| Gateways, `customersupport-gw`, `LambdaTarget` | Lambda ARN containing `CustomerSupportLambda` |
| Lambda, `CustomerSupportLambda` | `web_search` and `check_warranty` Python files |
| DynamoDB | `WarrantyTable` (e.g. serial `ABC12345678`) and `CustomerProfileTable` (e.g. `CUST001`) |

## Knowledge check

Score: 100% (5 of 5).

1. The Gateway target Lambda is `CustomerSupportLambda`, which holds both the web search and warranty tools.
2. Gateway authentication is JWT-based, using Amazon Cognito through AgentCore Identity.
3. The two long-term strategies are USER_PREFERENCE and SEMANTIC.
4. Memory operational metrics are in the Observability section of the memory resource page.
5. The Lambda contains `web_search` and `check_warranty`. There is no payment, profile update or ticket tool.

## How this lab compares to my own project

| Topic | This lab | My customer support agent project |
|---|---|---|
| Gateway auth | `CUSTOM_JWT` with Cognito | `NONE` authorizer (unsigned MCP connection) |
| MCP import | `streamablehttp_client` | `streamable_http_client` (newer `mcp` package) |
| Namespace formatting | `namespace.format(actorId=...)` | `.replace("{actorId}", ...)` |
| Strategy fields | `namespaces` | `namespaceTemplates`, with `namespaces` as a fallback |
| Other tools | Local mock tools | Knowledge Base RAG, Code Interpreter, Browser |
| Deployment | Run in a notebook | Deployed to AgentCore Runtime with `agentcore deploy` |

## Key takeaways

- Tool docstrings drive tool selection, so write them as instructions for the model.
- Memory is asynchronous. Seed it, wait, then test, and do not assume instant recall.
- Isolate memory by customer ID through namespaces.
- Centralize shared tools in a Gateway so multiple agents reuse them and updates happen in one place.
- Secure tool access. JWT through Cognito is the right choice for production, and `NONE` is only acceptable for a course project.
- Keep secrets in SSM Parameter Store or Secrets Manager, not in code.
- Check the logs when something fails. Several issues in my project (an IAM gap, a Playwright permission error) were only visible in the CloudWatch runtime logs.

## Notes on the notebook

- The notebook was run in the AWS lab IDE with Python 3.12 and `mcp<1.24`.
- Cell outputs include a Cognito client ID, a user pool discovery URL and a gateway ID. These are identifiers, not secrets, and the client secret is not printed. If you want to be careful, clear the outputs before publishing (Jupyter: Clear All Outputs).
- The notebook imports `lab_helpers` and `scripts`, which come from the lab environment and are not included here, so it will not run outside the lab.
