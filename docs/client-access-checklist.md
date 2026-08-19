# SRE agent: access checklist

What we need from you to run the CloudOps360 SRE agent in your AWS account. Work through the
numbered items below. Items 1 to 6 block the agent from running; items 7 to 10 can follow later.

Everything we ask for is read-only against your resources, apart from permission to call Claude
models in Amazon Bedrock inside your own account. No write access is requested on any service.

---

## Before you start: two decisions we need from you

These two answers change what you deploy, so settle them first.

**Which AWS region should the agent call Bedrock from?** Model access in Bedrock is granted per
account and per region, so we need to name one region.

**Do you have a written data-residency requirement?** If not, use global routing. It costs less
and works in every Bedrock region. If you do, see item 3.

---

## Blocking items

### 1. Deploy the onboarding CloudFormation stack

We will send you `client-onboarding-sre-rag.yaml` along with two parameter values: our AWS
account ID and an external ID generated for your connection.

The stack creates one IAM role, `CloudOps360ScanRole`. Only our account can assume it, and only
when the request carries your external ID. We request one-hour sessions.

If you already have a CloudOps360 onboarding stack, **update that stack** rather than creating a
second one. This template uses the same role name and is a superset of the older one: nothing is
removed and both AWS managed policies stay as they were.

Time needed: about 15 minutes, plus your review cycle.

### 2. Send us the Role ARN

The stack has one output, `RoleArn`. Paste it into the CloudOps360 onboarding page. We will
assume the role and read a single alarm to confirm the connection works.

### 3. Enable Bedrock model access

In the AWS console, go to Bedrock, then Model access, and request these models in the region you
picked above:

| Model | Bedrock model ID | Notes |
|---|---|---|
| Claude Sonnet 5 | `anthropic.claude-sonnet-5` | Required. Handles most investigations |
| Claude Haiku 4.5 | `anthropic.claude-haiku-4-5` | Required. Alarm triage and log filtering |
| Claude Opus 5 | `anthropic.claude-opus-5` | Optional. Used for severe or low-confidence cases |
| Claude Opus 4.8 | `anthropic.claude-opus-4-8` | Optional fallback |

Sonnet 5, Haiku 4.5 and Opus 4.8 are open to all Bedrock customers. Opus 5 has its own access
criteria, so check the console and start that request early if you want it.

**Routing mode.** The model ID carries a prefix that sets both price and data residency:

| Mode | Example | Price | Data stays in |
|---|---|---|---|
| Global | `global.anthropic.claude-sonnet-5` | Standard | No guarantee, routes worldwide |
| Geo | `us.` or `eu.` or `au.anthropic.claude-sonnet-5` | 10% more | US and Canada, EU, or Australia |
| In-region | `anthropic.claude-sonnet-5` | 10% more | The single region you name |

One warning for anyone in Singapore. Claude Opus 5 in `ap-southeast-1` only supports global
routing. There is no in-region option and no APAC geo profile. If your inference has to stay
inside APAC, your options are the AU geo prefix or in-region in `ap-southeast-4` (Melbourne).
Worth settling before you build anything else. Opus 5 in-region is available only in
`us-east-1`, `eu-north-1`, `eu-west-1`, `ap-southeast-4` and `us-gov-west-1`.

Time needed: about 10 minutes, then however long AWS takes to approve.

### 4. Provision a PostgreSQL database for the knowledge base

The agent stores your past incident write-ups as vector embeddings in a database in your account.

Amazon RDS or Aurora PostgreSQL, version 15 or later, with the `pgvector` extension available.
Run `CREATE EXTENSION vector;` in the target database. A `db.t4g.medium` is enough; the data is
megabytes, not gigabytes. Encrypt at rest with a KMS key you control and require TLS in transit.

Backups are worth having but the index is rebuildable from the source documents, so this is
convenience rather than a system of record.

We can provision this instead if you would rather we did. Tell us which you prefer.

Time needed: about an hour.

### 5. Agree the network path to that database

The database sits in your account and the agent runs on our platform, so the two need a route to
each other. Pick whichever fits your policies:

1. We run the retrieval component inside your account. This keeps retrieved text in your
   account and is what we recommend.
2. AWS PrivateLink. Private, nothing exposed to the internet, and you keep control of the
   endpoint service.
3. VPN or Transit Gateway. Sensible if you already run one to partner networks.
4. A publicly reachable RDS endpoint, locked to our IP range by security group, TLS required.
   Quickest to stand up, and defensible for a time-boxed pilot, but most security reviewers
   reject it for production.

Also check whether the subnet making Bedrock calls has internet egress. If it does not, add an
interface VPC endpoint for Bedrock.

Time needed: a decision, then about a day of work.

### 6. Sign off on the agent reading log content

This is the permission worth reading closely rather than approving by default.

The role includes `logs:FilterLogEvents` and `logs:GetLogEvents`, so the agent can read your
application log content. We ask for it because an analysis that cannot quote a real log line is
guesswork. It is also the most sensitive grant in the template.

Before you approve it, tell us which log groups hold personal data, secrets or regulated data.
We can exclude those from retrieval. If you want prompts and completions filtered by a Bedrock
Guardrail as well, say so now, because that changes which Bedrock endpoint we build against and
adds `bedrock:ApplyGuardrail` to the role.

A Guardrail sits at the model boundary, which is after the log content has already been read.
If personal data in logs is the concern, the filtering has to happen where the logs are read, so
we would handle that in the application rather than relying on the Guardrail alone.

---

## Items that can follow later

### 7. Cost visibility

Add `ce:GetCostAndUsage` and `ce:GetDimensionValues`, which the template enables by default. Cost
Explorer has no resource-level permissions, so this grant is account-wide, but it is read-only
and returns aggregated figures rather than resource configuration.

Without it the cost panel in the platform stays empty, and neither `SecurityAudit` nor
`ViewOnlyAccess` covers Cost Explorer. Easy to miss until somebody asks why the numbers are
blank.

### 8. Bedrock invocation logging

Turn on Bedrock invocation logging to CloudWatch Logs or S3. It records the prompts and
completions in your own account so you can audit exactly what the agent asked the model and what
came back. Switching it on gives neither AWS nor Anthropic access to that content. Also confirm
CloudTrail is on in the Bedrock region.

We suggest keeping 30 days of rolling logs.

### 9. The secret holding the database credential

If you keep the knowledge base credential in Secrets Manager, give us the ARN and the template
scopes `secretsmanager:GetSecretValue` to that one secret.

### 10. Raise the Bedrock token quota if your volume is high

The default is 2 million input tokens per minute, and you can raise it to 4 million yourself
without asking Anthropic. One investigation runs to roughly 150,000 tokens, so the default suits
interactive use. Raise it if you expect many investigations at once or want us to load a large
back catalogue of documents in one go. Requests-per-minute limits are set by AWS, so those need a
support ticket.

---

## What the role can and cannot do

Useful if a security reviewer wants the summary without reading our code.

**Granted, read-only:**

- `SecurityAudit` and `ViewOnlyAccess`, the two AWS managed policies, for resource configuration
- CloudWatch alarm state and history, metric datapoints, and the metric list
- CloudWatch Logs: log group listing and log content
- Describe calls against the alarmed resource for EC2, RDS, Lambda, ECS, load balancer target
  health, DynamoDB and SQS
- Recent RDS events, which is how the agent spots failovers and restarts

**Granted, model inference:**

- `bedrock-mantle:CreateInference`, or `bedrock:InvokeModel` and
  `bedrock:InvokeModelWithResponseStream` if you require Guardrails. Scoped to Anthropic Claude
  model ARNs and pinned to the one region you named by an `aws:RequestedRegion` condition

**Not granted, and will not work through this role:**

- Any write, create, update or delete action on any service
- Patch management, which needs `ssm:SendCommand` and several mutating EC2 actions
- Terraform provisioning

The read-only property is enforced by a test rather than by convention. It asserts that every AWS
method the agent calls begins with `describe_`, `get_`, `filter_` or `list_`, so a mutating call
cannot be added without the test failing.

To revoke everything, delete the CloudFormation stack. That takes effect immediately and you do
not need to tell us first.

If a permission is missing, the agent reports it in its output as a gap and carries on with what
it can reach, so you will see it rather than having to debug it.

---

## Questions to send back with the Role ARN

1. Which AWS account IDs should the agent cover?
2. Which regions do your production workloads run in?
3. Which region should the agent call Bedrock from?
4. Global, geo or in-region routing? Do you have a written residency requirement?
5. Do you require Bedrock Guardrails on prompts and completions?
6. Who approves the IAM role, and what does their review involve?
7. Are you already onboarded to CloudOps360, so we know whether to update or create the stack?
8. Will you provision the PostgreSQL database, or should we?
9. Which of the four network options in item 5 works for you?
10. Do the subnets involved have internet egress?
11. Which log groups hold personal data, secrets or regulated data?
12. Roughly how many alarm-triggered incidents do you see per month?

Send answers and the Role ARN together and we can finish setup in the same week.

Separate from access, the agent gets better the more of your past incident write-ups, service
list and runbooks we can load. That is covered in the full prerequisites document rather than
here, and it does not block anything above.
