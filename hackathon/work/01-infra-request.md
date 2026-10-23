# Infra request as submitted: Team InfinityStacks (Problem 2, Halcyon)

The request the team actually sent, which is the source of truth for the build plan. The same
rows are in `01-infra-request.xlsx`.

| Field | Value |
|---|---|
| Team | InfinityStacks |
| Members | 7549 · Sravan Kumar D · sdayyala@evoketechnologies.com<br>8388 · Sai M · smuthiki@evoketechnologies.com<br>5511 · Dinesh K · dkarasu@evoketechnologies.com |
| Tech stack | ReactJS, Python and AWS |
| Tools | Docker, Postman |
| SDK / API | Amazon Bedrock Runtime API |
| Repository | GitHub |
| AI coding tool | Claude Chat + Claude Code |
| Cloud | AWS |
| Services | Amazon Bedrock (Claude model access) · AWS IAM · Amazon S3 · Amazon ECR · AWS Secrets Manager · Amazon RDS PostgreSQL · Amazon CloudWatch · AWS Amplify (frontend hosting) · Amazon EC2 |

**Not requested, so the design does not depend on them:** ECS/Fargate, ALB, CloudFront,
Lambda, EventBridge, CDK/CloudFormation. If one is needed later, raise it in the infra group.
Bedrock Guardrails comes with Bedrock, but its permissions may not; we have a fallback (see the
design doc, §9).
