# Services

21 AWS services named in `data/raw_rca_docs/`'s frontmatter, one file each. `rag/ingestion/loader.py`'s
`service_alias_map()` reads every file's `id`/`name`/`aliases` to normalize the corpus's `services:`
field at ingest; `rag/routing/dependency_graph.py` reads `depends_on` for the `blast_radius` route.

* [acm](acm.md) - Certificate issue and renewal; appears here only as an expiry renewal automation didn't cover.
* [alb](alb.md) - Layer-7 load balancing in front of EC2 and ECS targets; health checks and deregistration delay are the two settings behind every ALB incident here.
* [api-gateway](api-gateway.md) - The HTTP front door for most Lambda-backed services in this corpus; its account-level burst limit and fixed integration timeout are hard edges the backing function's own limits don't see.
* [cloudfront](cloudfront.md) - CDN edge; edge-visible 4xx/5xx here usually originate at the origin or its certificate, not the edge itself.
* [dynamodb](dynamodb.md) - Key-value store; both failure modes here are access-pattern defects that only appear at production traffic shape.
* [ebs](ebs.md) - Block storage for EC2 and RDS; its ceilings are IOPS and throughput, which is where the database incidents in this corpus actually bind.
* [ec2](ec2.md) - Instance compute, including the Auto Scaling groups that front it; failures here are usually a scaling loop reacting to a health signal that doesn't mean what the ASG thinks it does.
* [ecr](ecr.md) - Container image registry behind the ECS services here; present as the source of an image whose resource profile changed, not as a failing component itself.
* [ecs](ecs.md) - Container orchestration, Fargate and EC2 launch types both; task-level resource limits and the ENI-per-task model are where this shows up in incidents.
* [elasticache](elasticache.md) - Managed Redis; the two incidents here fail on opposite sides of the boundary - one server-side eviction policy, one client-side failover handling.
* [eventbridge](eventbridge.md) - Event routing between services; appears as the trigger path for scheduled and reactive Lambda work rather than as the failing component itself.
* [glue](glue.md) - Managed ETL; appears as the workload whose write volume saturated the database it loaded into.
* [iam](iam.md) - Identity and access; every IAM incident here is a change correct in isolation and wrong in combination with a caller nobody re-tested.
* [kms](kms.md) - Encryption key management; failures are either key-policy permission errors or request-rate throttling on `Encrypt`/`Decrypt` calls.
* [lambda](lambda.md) - Serverless compute; VPC-attached functions draw an ENI per concurrent execution, so failures show up as networking/quota issues at least as often as code issues.
* [rds](rds.md) - Managed relational databases; both incidents here are capacity limits reached by something upstream with no matching limit of its own.
* [route-53](route-53.md) - DNS and health checking; in this corpus it's the detector, not the failure - its HTTPS health check was the first signal of a certificate expiry.
* [s3](s3.md) - Object storage; failures here are almost never S3 itself, but policy, key, and replication-configuration changes shipped against it.
* [sqs](sqs.md) - Queueing between producers and consumers; shows up as where backlog becomes visible when a consumer is throttled, OOMing, or scanning.
* [step-functions](step-functions.md) - Workflow orchestration for the batch pipelines here; carries the retry/timeout policy that decides whether a slow downstream becomes a failed pipeline.
* [vpc](vpc.md) - The network everything else sits in; its failures are address-space and port-space arithmetic that scale-out walks into.
