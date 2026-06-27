\# QueueStorm Investigator



QueueStorm Investigator is a deterministic, rule-based API for analyzing mobile financial service support tickets.



The system receives a customer complaint and optional transaction history, then returns a structured investigation result with evidence verdict, case type, severity, department routing, recommended next action, and a safe customer reply.



\## Live Public Endpoint



Base URL:



```txt

https://cent-rain-tank-dimensional.trycloudflare.com

```



Health check:



```txt

GET /health

```



Analyze ticket:



```txt

POST /analyze-ticket

```



\## Docker Image



```txt

mrnowyouseeme/queuestorm-investigator:latest

```



\## GitHub Repository



```txt

https://github.com/MrNowYouSeeMe/queuestorm-investigator

```



\## Tech Stack



\* Python 3.11

\* FastAPI

\* Pydantic

\* Uvicorn

\* Docker

\* Cloudflare Tunnel for public endpoint exposure from Poridhi VM



\## Solution Type



This solution is fully deterministic and rule-based.



No LLM, external AI API, or paid model service is used.

This keeps the system fast, reproducible, and safe for structured API evaluation.



\## Main Features



\* Required `/health` endpoint

\* Required `/analyze-ticket` endpoint

\* Schema-compliant JSON response

\* Rule-based complaint classification

\* Transaction evidence matching

\* Evidence verdict generation

\* Severity assignment

\* Department routing

\* Human review decision

\* Safe customer reply generation

\* Basic Bangla and mixed-language complaint handling

\* Safety guardrails for OTP, PIN, password, phishing, and suspicious-link cases

\* Dockerized deployment



\## Supported Case Types



The API classifies complaints into the following case types:



\* `wrong\_transfer`

\* `payment\_failed`

\* `refund\_request`

\* `duplicate\_payment`

\* `merchant\_settlement\_delay`

\* `agent\_cash\_in\_issue`

\* `phishing\_or\_social\_engineering`

\* `other`



\## Supported Evidence Verdicts



The API returns one of the following evidence verdicts:



\* `consistent`

&#x20; The complaint matches the available transaction evidence.



\* `inconsistent`

&#x20; The complaint conflicts with the available transaction evidence.



\* `insufficient\_data`

&#x20; There is not enough transaction evidence to make a strong decision.



\## Supported Severity Levels



The API returns one of:



\* `low`

\* `medium`

\* `high`

\* `critical`



Severity is decided using case type, transaction amount, evidence strength, and safety risk.



Examples:



\* Phishing, OTP, PIN, or password-related issues are marked as `critical`.

\* Large wrong-transfer cases are marked as `high` or `critical`.

\* Simple refund requests with small amounts may be marked as `low`.

\* Vague complaints without evidence may be marked as `low`.



\## Department Routing



The system routes cases to the most relevant department:



| Case Type                        | Department            |

| -------------------------------- | --------------------- |

| `wrong\_transfer`                 | `dispute\_resolution`  |

| `payment\_failed`                 | `payments\_ops`        |

| `refund\_request`                 | `customer\_support`    |

| `duplicate\_payment`              | `payments\_ops`        |

| `merchant\_settlement\_delay`      | `merchant\_operations` |

| `agent\_cash\_in\_issue`            | `agent\_operations`    |

| `phishing\_or\_social\_engineering` | `fraud\_risk`          |

| `other`                          | `customer\_support`    |



\## How the System Works



The system follows this pipeline:



1\. Receive JSON request.

2\. Validate input using Pydantic models.

3\. Normalize complaint text.

4\. Convert Bangla digits when possible.

5\. Detect high-risk safety keywords such as OTP, PIN, password, phishing, and suspicious links.

6\. Classify complaint type using rule-based signals.

7\. Analyze transaction history.

8\. Match the most relevant transaction using amount, type, status, transaction ID, and counterparty signals.

9\. Decide evidence verdict.

10\. Assign severity.

11\. Route the case to the correct department.

12\. Decide whether human review is required.

13\. Generate agent summary.

14\. Generate recommended next action.

15\. Generate safe customer reply.

16\. Enforce final output schema and safety constraints.



\## Safety Design



The API is designed to avoid unsafe financial or credential-related responses.



The system never asks the customer to share:



\* PIN

\* OTP

\* Password

\* Full card details



The system also avoids making direct financial promises such as:



\* “We will refund you.”

\* “Your account is unblocked.”

\* “Your money will be reversed immediately.”



Instead, it uses safe language such as:



```txt

Your case will be reviewed through official support channels.

Please do not share your PIN or OTP with anyone.

```



\## API Example



\### Request



```json

{

&#x20; "ticket\_id": "TKT-001",

&#x20; "complaint": "I sent 5000 taka to a wrong number. Please help.",

&#x20; "language": "en",

&#x20; "channel": "in\_app\_chat",

&#x20; "user\_type": "customer",

&#x20; "transaction\_history": \[

&#x20;   {

&#x20;     "transaction\_id": "TXN-1",

&#x20;     "timestamp": "2026-04-14T14:08:22Z",

&#x20;     "type": "transfer",

&#x20;     "amount": 5000,

&#x20;     "counterparty": "+8801719876543",

&#x20;     "status": "completed"

&#x20;   }

&#x20; ]

}

```



\### Response



```json

{

&#x20; "ticket\_id": "TKT-001",

&#x20; "relevant\_transaction\_id": "TXN-1",

&#x20; "evidence\_verdict": "consistent",

&#x20; "case\_type": "wrong\_transfer",

&#x20; "severity": "high",

&#x20; "department": "dispute\_resolution",

&#x20; "agent\_summary": "Customer reports a wrong transfer involving TXN-1 for 5000 BDT.",

&#x20; "recommended\_next\_action": "Verify TXN-1 details and route through the wrong-transfer dispute workflow.",

&#x20; "customer\_reply": "Your case will be reviewed through official support channels. Any eligible amount or action will be handled according to policy. Please do not share your PIN or OTP with anyone.",

&#x20; "human\_review\_required": true,

&#x20; "confidence": 0.9,

&#x20; "reason\_codes": \[

&#x20;   "wrong\_transfer",

&#x20;   "transaction\_match"

&#x20; ]

}

```



\## Run with Docker



Pull the Docker image:



```bash

docker pull mrnowyouseeme/queuestorm-investigator:latest

```



Run the container:



```bash

docker run -d --name queuestorm\_api -p 8000:8000 mrnowyouseeme/queuestorm-investigator:latest

```



Check health:



```bash

curl http://localhost:8000/health

```



Expected response:



```json

{"status":"ok"}

```



\## Run Locally for Development



Install dependencies:



```bash

pip install -r requirements.txt

```



Start the FastAPI server:



```bash

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

```



Check health:



```bash

curl http://localhost:8000/health

```



\## Public Deployment Notes



The submitted public endpoint is served through a Cloudflare Tunnel from the Poridhi VM.



Request flow:



```txt

Client / Judge

&#x20;   ↓

Cloudflare public URL

&#x20;   ↓

Cloudflare Tunnel on Poridhi VM

&#x20;   ↓

localhost:8000 on Poridhi VM

&#x20;   ↓

Docker container

&#x20;   ↓

FastAPI application

&#x20;   ↓

JSON response

```



\## Known Limitations



\* The system is rule-based, so it may not understand every possible natural-language variation.

\* It handles common English, Bangla, and mixed complaint patterns, but very unusual wording may be classified as `other`.

\* It does not use an LLM, so semantic understanding is limited compared to a hybrid LLM-based normalizer.

\* When transaction evidence is unclear, the system may return `insufficient\_data`.



\## Why Rule-Based?



A rule-based approach was chosen to make the system:



\* Fast

\* Deterministic

\* Reproducible

\* Schema-safe

\* Easy to deploy

\* Free from external API-key dependency

\* Safer for financial-support responses



\## Security and Compliance



\* No real customer data is used.

\* No real payment data is used.

\* No API keys are required.

\* No secrets are committed.

\* No LLM or external AI provider is called.

\* Customer replies avoid unsafe refund, reversal, unblock, OTP, PIN, or password instructions.



