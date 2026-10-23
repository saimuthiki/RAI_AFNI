# Infra requirements form: Problem 2, Halcyon Logistics (AWS)

Answers to every column of the L&D infra form. Fields in `[brackets]` need our own details.
A spreadsheet copy in the same column order is in `01-infra-request.xlsx`. The team SPOC posts it
once in the infra Teams group.

**What we are building, which sizes the request:** a late-delivery root-cause and fix platform.
It ingests about 48k deliveries plus orders, WMS, carrier events and the complaint inbox; attributes
lateness to each process step; runs AI agents for email-order extraction, carrier scorecards,
exception triage and an executive Q&A; and simulates on-time delivery before and after each fix.

## Team

- **Team name:** `[Team name]`
- **Members (Employee ID, Name, Email):**
  - `[EMP ID]` · `[Name]` · smuthiki@evoketechnologies.com (team SPOC)
  - `[EMP ID]` · `[Name]` · `[email]`
  - `[EMP ID]` · `[Name]` · `[email]`

## The form fields

- **Preferred Tech Stack**
  - Backend: Python 3.11+ with FastAPI.
  - Frontend: React + TypeScript (Next.js or Vite).
  - Database: PostgreSQL, with DuckDB for analytics over the 48k-row history.
  - Containers: Docker.
- **Frameworks / Libraries / Tools Required**
  - Backend: pandas or polars, DuckDB, SQLAlchemy, Pydantic, scikit-learn, statsmodels.
  - Simulation: SimPy, for the what-if model of the cutoff and carrier changes.
  - Frontend: Tailwind CSS, shadcn/ui, Recharts or ECharts.
  - Testing: pytest, Playwright.
  - Agents: the Anthropic SDK (Bedrock client) or the Claude Agent SDK, or LangGraph, for agent orchestration.
  - Faker, to generate synthetic orders and deliveries where the data has gaps.
- **Any Specific SDKs or APIs Needed**
  - **Amazon Bedrock Runtime API** with Anthropic Claude models (Sonnet-class for agents, Haiku-class for bulk extraction). This is the AI inside the solution.
  - AWS SDK for Python (boto3): Bedrock, S3, Secrets Manager.
  - No paid third-party logistics APIs. Routing distances, if needed, come from the provided data or offline estimates.
- **Azure DevOps Repository**
  - Yes: one private repo for the team.
  - The guidelines PDF says source must be pushed to the "designated **GitHub** repository". Please confirm which one is the official submission repo. We can mirror to both, with CI/CD deploying to AWS.
- **AI Coding Tool Required**
  - Claude Code on Evoke Claude, for all 3 members. Please raise the usage limit above the 5-hour window, or provide API credits: we run agent pipelines across BA, design, dev and test roles.
  - Cursor.
  - GitHub Copilot.
- **Cloud Environment Needed (Azure / AWS)**
  - **AWS.** One sandbox account, or an IAM role with the permissions below, for the hackathon period.
  - Region: **ap-south-1 (Mumbai)**, using Bedrock cross-region inference for Claude. If the Claude models aren't enabled there, use **us-east-1**.
- **Required Services**
  - **Amazon Bedrock:** model access enabled for Anthropic Claude (Sonnet + Haiku). This is the AI service.
  - **ECS on Fargate** behind an **Application Load Balancer**, or **AWS App Runner**, for the API container.
  - Frontend on **AWS Amplify Hosting**, or **S3 + CloudFront**.
  - **Amazon RDS for PostgreSQL**, db.t4g.micro or small, single-AZ.
  - **Amazon S3**, for raw data files, email text and generated reports.
  - **Amazon ECR**, for container images.
  - **AWS Secrets Manager**, for DB credentials and config.
  - **Amazon CloudWatch** logs and metrics, for monitoring and the AI usage logs.
  - **IAM:** a deploy role or user for CI/CD, and task roles with `bedrock:InvokeModel` access.
  - **EC2 / VM:** only if members are on CSC client laptops; one t3.large dev box. Otherwise none.
- **Any External API Integrations?**
  - None outside AWS. Claude is reached through Amazon Bedrock.
  - Carrier, EDI and WMS feeds are simulated from the provided dataset; we do not call real carriers.
- **Any dependencies on external data sources or services?**
  - Only the hackathon dataset from the organisers: 48,340 deliveries, WMS orders and inventory, EDI and API feeds, carrier events, the complaint inbox and the carrier preference spreadsheet.
  - We generate synthetic data for any gaps. No real customer or personal data.
- **Any specific software installations required?**
  - Git
  - VS Code
  - Python 3.11+
  - Node.js 20 LTS
  - Docker Desktop
  - AWS CLI v2
  - Claude Code CLI, Cursor, GitHub Copilot extension
  - A Postgres client (DBeaver or psql)
  - Playwright browsers
- **Any restrictions or firewall exceptions required?**
  - Package registries: `pypi.org`, `files.pythonhosted.org`, `registry.npmjs.org`
  - Code and CI: `github.com`, `*.githubusercontent.com`, `dev.azure.com`
  - AWS: `*.amazonaws.com`, in particular `bedrock-runtime.<region>.amazonaws.com`, `*.ecr.<region>.amazonaws.com` and `*.s3.amazonaws.com`
  - AWS console and SSO: `*.signin.aws.amazon.com`, `*.awsapps.com`
  - App hosting: `*.amplifyapp.com`, `*.cloudfront.net`, `*.awsapprunner.com`
  - Claude Code: `api.anthropic.com`, `claude.ai`
  - Playwright browser download: `playwright.azureedge.net`
  - Optional, for library docs: `mcp.context7.com`
- **Any other requests or setup requirements not covered above**
  - Access to the full Problem 2 dataset and a data dictionary: field meanings, and how "on-time" is computed.
  - A public or Evoke-network URL for the deployed app so judges can reach it for the L1 check.
  - IAM credentials or an OIDC role for CI/CD deploys from the repo to AWS.
  - An AWS budget alert, to keep spend in check.
  - Confirmation that agent and AI usage logs committed to the repo satisfy the "AI usage logs" deliverable.
  - Access kept active until the L2 presentations in the first week of November.
