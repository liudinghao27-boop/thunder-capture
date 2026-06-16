"""Dify AI Workflow adapter.

Replaces the hardcoded prompt templates in core/classify.py with
Dify's visual workflow engine.

Integration status:
  - adapters/dify/client.py      : production Dify HTTP client (batch + retry)
  - adapters/dify/workflow-template.yml : importable workflow definition
  - core/classify.py             : ClassificationRouter auto-selects DifyBackend
                                   when DIFY_API_URL + DIFY_API_KEY are set,
                                   falling back to DirectLLMBackend otherwise.

Deployment steps:
  1. Deploy Dify (self-hosted or cloud): https://docs.dify.ai
  2. Import adapters/dify/workflow-template.yml as a workflow.
  3. Configure the LLM node (DeepSeek / OpenAI / etc.) and publish.
  4. Create an API key for the workflow.
  5. Set in .env:
       DIFY_API_URL=https://your-dify.example.com/v1
       DIFY_API_KEY=app-xxx
  6. Restart workers; classify_batch() will use Dify automatically.
"""
