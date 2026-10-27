# Harbor Events

Original sample of a multi-tenant event API. Tenants, account IDs, IP ranges, and VPC endpoint IDs are fictional. Deploy it only in a personal AWS account.

`203.0.113.0/24` is a documentation network. `123456789012` is a documentation account. `vpce-0123456789abcdef0` is a placeholder. Replace them before a real deploy. The Roles Anywhere template takes a certificate you create yourself. This repo has no private key.

## Flow

One shared API accepts either SigV4 or a Cognito JWT. The Lambda reads a tenant map from AppConfig and calls `send_message` on that tenant's queue. The queue URL can point at another region. Each tenant stack creates one role, one queue, and an SNS subscription filtered by `customer`. S3 returns a presigned URL for an optional object key. A pipeline deploys the same root stack to `us-east-1`, then `eu-west-1`.

## Where each concept is

| Concept | File |
| --- | --- |
| Nested stacks, mappings, parameters, conditions, `Fn::Sub`, `Fn::GetAtt`, `Fn::FindInMap` | `templates/main.yaml` |
| Identity policy and resource policy, `aws:SourceIp`, `aws:SourceVpce`, role ID, least privilege | `templates/shared.yaml`, `templates/tenant.yaml` |
| IAM Roles Anywhere trust anchor, profile, assumed-role ARN | `templates/roles-anywhere.yaml` |
| REST API, SigV4 authorizer, Cognito authorizer, IP resource policy | `templates/shared.yaml` |
| Cognito user pool, ID token, `cognito:username` | `templates/shared.yaml`, `src/router.py` |
| Same Lambda, two caller types | `src/router.py` |
| SQS `send_message`, cross-region queue URL, queue policy | `src/router.py`, `templates/tenant.yaml` |
| Lambda, boto3, event routing | `src/router.py` |
| AppConfig routing map | `config/routing.json`, `templates/shared.yaml` |
| S3 IP allowlist and presigned URL | `templates/shared.yaml`, `src/router.py` |
| SNS filter policy by customer | `templates/tenant.yaml` |
| CodePipeline `RunOrder`, two regions | `pipeline/pipeline.yaml` |
| One shared API, one role per tenant | `templates/main.yaml` calls `tenant.yaml` twice |

API Gateway validates the Cognito token before the Lambda runs. The function only reads `cognito:username` from the claims. For SigV4 it reads `requestContext.identity.userArn`, which is the assumed-role ARN when the caller used IAM Roles Anywhere.

The queue resource policy allows the router role through the SQS VPC endpoint. A second statement allows a caller only when `aws:userid` starts with that tenant role's unique ID and the call also comes from the endpoint. The first deploy uses a placeholder role ID, so that statement matches nobody. After deploy, copy `AcmeRoleId` and `GlobexRoleId` into `TenantRoleId` and update the stack.

Set `RequireVpcEndpoint` to `false` only for a laptop test in a personal account. The published default is `true`.

## Local check

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
.\scripts\package.ps1
```

`scripts/package.ps1` writes `dist/router.zip` with `router.py` at the root of the archive. Upload that zip to a bucket in each region before deploying the application stack there. Lambda can load code only from a bucket in its own region.

## Deploy outline

Publish `templates/*.yaml` to the S3 prefix you pass as `TemplateBaseUrl`. Upload `router.zip` to the regional artifact bucket. Deploy `templates/main.yaml` with `CAPABILITY_NAMED_IAM`. Deploy `pipeline/pipeline.yaml` in `us-east-1` if you want the two-region pipeline. That pipeline needs an artifact bucket in `us-east-1` and another in `eu-west-1`. Put a `source.zip` of this repo at `source.zip` in the `us-east-1` bucket, then start the pipeline.

After the tenant queues exist, replace the example queue URLs in AppConfig with the `AcmeQueueUrl` and `GlobexQueueUrl` outputs.
