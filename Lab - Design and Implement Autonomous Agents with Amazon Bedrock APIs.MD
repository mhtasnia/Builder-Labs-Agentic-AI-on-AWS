# Design and Implement Autonomous Agents with Amazon Bedrock APIs

Self notes from the lab *Design and Implement Autonomous Agents with Amazon Bedrock APIs* (SPL-TF-300-MLDIAA-1). The lab builds a Retrieval Augmented Generation (RAG) stack by hand with the AWS SDK, then puts a Strands agent on top of it. The agent answers questions from an IT employee handbook and creates and looks up IT support tickets.




## Notebook: [resources/bedrock_agents_lab.ipynb](resources/bedrock_agents_lab.ipynb)

## The big picture

```
IT handbook (PDF) ──> S3 bucket ──> Bedrock Knowledge Base ──> OpenSearch Serverless (vector index)
                                           ▲
User question ──> Strands agent (Nova Lite) ┤ retrieve tool
                                           ├ create_ticket tool ──> Lambda: SkillBuilder-ITSM-Create
                                           └ lookup_ticket tool ──> Lambda: SkillBuilder-ITSM-Lookup
```

| Piece | What it does |
|---|---|
| Amazon S3 | Holds the source document (`Fictitious-Company-Employee-IT-Handbook.pdf`) |
| Amazon OpenSearch Serverless | The vector store, a `VECTORSEARCH` collection |
| Amazon Titan Text Embeddings V2 | Turns text chunks into 1024-dimension vectors |
| Bedrock Knowledge Base | Manages chunking, embedding, ingestion and retrieval |
| Strands Agents SDK | The agent: a model, tools and a system prompt |
| Lambda functions (pre-created) | The ticketing backend (create and look up tickets) |

An important point: **the agent is not deployed anywhere.** It is a Python object in the notebook. No managed Bedrock Agent resource is created. (The AgentCore labs are the ones that deploy agents to a runtime.)

## Requirements

Packages the notebook installs (Python 3.12 kernel, "Global Env"):

```
boto3
requests
requests-aws4auth
strands-agents
strands-agents-tools
```

`requests` and `requests-aws4auth` are used to sign calls to the OpenSearch Serverless endpoint. `strands-agents-tools` provides the ready-made `retrieve` tool.

## Task 1: Build the Knowledge Base (Steps 1 to 9)

### Step 1: Setup

Two lab values go into the notebook (from the lab's left panel):

| Output | Variable |
|---|---|
| `BedrockKnowledgeBaseRoleArn` | `bedrock_bkb_role_arn` |
| `S3BucketBKB` | `s3_bucket` |

The notebook also finds its own execution role from the STS caller identity (`sts get_caller_identity`) so it can grant that role access to the collection.

### Steps 2 to 4: Three security policies

OpenSearch Serverless needs policies before a collection can exist and be used. Collection name: `skillbuilder`.

| Step | Policy | What it does |
|---|---|---|
| 2 | **Network** | `AllowFromPublic: True` for the collection and its dashboard, so Bedrock can reach it |
| 3 | **Data access** | Gives `aoss:*` on the collection and its indexes to the Bedrock Knowledge Base role and to the notebook's role |
| 4 | **Encryption** | Encrypts the collection at rest with an AWS-owned key |

Each call is wrapped in `try/except ConflictException` so a rerun skips what already exists.

### Step 5 and 6: Create the collection

```python
client.create_collection(name=collection_name, type='VECTORSEARCH', ...)
```

Creation is asynchronous. The notebook polls `batch_get_collection` every 15 seconds until the status is `ACTIVE` (it showed `CREATING` about 14 times first). Then it reads the collection endpoint and dashboard endpoint.

### Step 7: Create the vector index

The index is created with a signed `PUT` request to the collection endpoint (AWS Signature Version 4, service name `aoss`). The mapping must match what Bedrock expects:

```python
"bedrock-knowledge-base-default-vector": {
    "type": "knn_vector",
    "dimension": 1024,                      # Titan Text Embeddings V2 output size
    "method": {"engine": "faiss", "space_type": "l2", "name": "hnsw", "parameters": {}}
},
"AMAZON_BEDROCK_TEXT_CHUNK": {"type": "text", "index": "true"},      # the chunk text
"AMAZON_BEDROCK_METADATA":   {"type": "text", "index": "false"}      # source info
```

- The vector dimension (1024) must equal the embedding model's output dimension.
- FAISS with the HNSW algorithm does approximate nearest-neighbour search quickly.
- These three field names are repeated in the Knowledge Base's `fieldMapping` in the next step.

### Step 8: Create the Knowledge Base

```python
bedrock_client.create_knowledge_base(
    name="skillbuilder-kb",
    roleArn=bedrock_bkb_role_arn,
    knowledgeBaseConfiguration={
        "type": "VECTOR",
        "vectorKnowledgeBaseConfiguration": {
            "embeddingModelArn": f"arn:aws:bedrock:{curr_region}::foundation-model/amazon.titan-embed-text-v2:0"
        }
    },
    storageConfiguration={
        "type": "OPENSEARCH_SERVERLESS",
        "opensearchServerlessConfiguration": {
            "collectionArn": ...,
            "vectorIndexName": "skillbuilder-index",
            "fieldMapping": {
                "vectorField": "bedrock-knowledge-base-default-vector",
                "textField": "AMAZON_BEDROCK_TEXT_CHUNK",
                "metadataField": "AMAZON_BEDROCK_METADATA",
            },
        },
    },
)
```

- If this fails with `ValidationException ... no such index [skillbuilder-index]`, run the cell again. The index can take a moment to become visible. (The lab warns about this.)
- A polling loop waits until the Knowledge Base status is `ACTIVE`.

### Step 9: Data source and ingestion

1. Upload the PDF to the S3 bucket with `s3_client.upload_file`.
2. `create_data_source` with an S3 configuration and this chunking setup:

   | Setting | Value |
   |---|---|
   | Strategy | `FIXED_SIZE` |
   | `maxTokens` | 300 |
   | `overlapPercentage` | 20 |

3. `start_ingestion_job` reads the PDF, splits it into chunks, embeds each chunk, and writes the vectors to the index.
4. A loop polls `get_ingestion_job` until it is `COMPLETE`.

Chunk size is a trade-off. Smaller chunks give precise matches but less context. The 20% overlap keeps sentences that straddle a boundary from being cut off.

## Task 2: Build and test the Strands agent (Steps 10 and 11)

### The agent

```python
from strands import Agent, tool
from strands.models import BedrockModel
from strands_tools import retrieve

os.environ['KNOWLEDGE_BASE_ID'] = knowledge_base_id   # the retrieve tool reads these
os.environ['AWS_REGION'] = curr_region

@tool
def create_ticket(tickettype: str, description: str, impact: str, urgency: str) -> str:
    """Create an ITSM ticket. ..."""
    result = lambda_client.invoke(FunctionName='SkillBuilder-ITSM-Create', Payload=...)
    payload = json.loads(result['Payload'].read())
    return payload.get('ticketNumber', str(payload))

@tool
def lookup_ticket(ticketNumber: str) -> dict:
    """Look up the status and details of an ITSM ticket by its ticket number. ..."""
    result = lambda_client.invoke(FunctionName='SkillBuilder-ITSM-Lookup', Payload=...)
    return json.loads(result['Payload'].read())

geo = 'us' if curr_region.startswith('us-') else 'eu'
bedrock_model = BedrockModel(model_id=f"{geo}.amazon.nova-lite-v1:0")

agent = Agent(model=bedrock_model, system_prompt=system_prompt,
              tools=[retrieve, create_ticket, lookup_ticket])
```

Points to remember:

- **Three tools:** the prebuilt `retrieve` (semantic search over the Knowledge Base), plus two custom `@tool` functions that call Lambda functions. The docstrings and `Args:` sections tell the model how to use them.
- **Cross-Region inference profile.** Nova Lite is called through a profile ID with a geography prefix (`us.` or `eu.`), which the notebook derives from the Region.
- **The system prompt** tells the agent when to use each tool and forbids making up ticket details: "Do not make up any ticket details; they must come from the `lookup_ticket` tool."
- A small `chat(prompt)` helper prints the prompt and calls `agent(prompt)`.

### Test results

| Test | Result |
|---|---|
| "Tell me the password policy from the IT handbook." | Called `retrieve`. Answer: at least 8 characters, mixed character types, change every 90 days |
| "Tell me the policy on using personal mobile phones..." | `retrieve` found nothing relevant. The agent said so and offered to create a ticket instead of inventing a policy |
| "Tell me the remote work policy..." | Called `retrieve`. Answer: use a VPN and keep company data on approved devices |
| "Please create an INC ticket... Power outage, High, Critical" | Called `create_ticket`. Returned ticket number `INC40918362` |
| "Please look up information for ticket number: INC40918362" | Called `lookup_ticket`. Returned status Pending, the same description, impact, urgency and a created time |

The mobile phone question is the most useful result: when the knowledge base had no answer, the agent admitted it instead of guessing. This is the grounding behaviour RAG should have.

The lookup cell needs the real ticket number pasted in (`ticket_number = "INC40918362"`).

## Observations

- **Ingestion statistics looked empty.** The job ended `COMPLETE`, but the notebook printed `Documents processed: 0`. The retrieval answers show that the document was indexed. The likely reason is that the notebook reads a statistics key (`numberOfDocumentsProcessed`) that the API doesn't return. The counters I would check instead are `numberOfNewDocumentsIndexed`, `numberOfDocumentsScanned` and `numberOfDocumentsFailed`. I haven't confirmed this against the API response.
- **The agent runs in the notebook.** Closing the notebook ends it. There is no endpoint to call from elsewhere.
- **Printed reasoning.** The agent prints `<thinking>` text and tool numbers as it works, which is useful when learning and not something to show to end users.

## Lessons learned

- A Bedrock Knowledge Base is a pipeline: document, chunks, embeddings, vector index. Each part has to match (embedding dimension, field names, chunking).
- OpenSearch Serverless needs three policies (network, data access, encryption). The encryption policy must exist before the collection.
- Creating resources through the API is asynchronous, so poll until `ACTIVE` or `COMPLETE` before the next step.
- Prebuilt tools (`retrieve`) and custom tools (`@tool` around a Lambda call) work side by side in one agent.
- Telling the agent to take ticket details only from the tool, and watching it decline the mobile phone question, shows how a prompt and good retrieval limit made-up answers.

## Production considerations

- **Network.** `AllowFromPublic: True` is a lab shortcut. A real deployment should reach the collection through a VPC endpoint.
- **Least privilege.** The data access policy gives `aoss:*` to two roles. Scope it to the actions needed (read for the agent, index and write for ingestion).
- **Cost.** OpenSearch Serverless is billed on capacity units while the collection exists, even with no queries. Delete the collection, Knowledge Base and policies when finished, especially in your own account. The lab has no cleanup step.
- **Ticketing safety.** `create_ticket` creates real records. In production, validate the inputs (ticket type, impact, urgency) and ask the user to confirm before creating a ticket.
- **Evaluation.** Test retrieval quality with a set of known questions (including ones with no answer) and check that answers match the retrieved chunks.
- **Keeping data fresh.** The Knowledge Base only knows what was ingested. Re-run ingestion whenever the handbook changes.
- **Hosting.** To serve the agent to users it would need to be deployed (for example to AgentCore Runtime) with authentication.

