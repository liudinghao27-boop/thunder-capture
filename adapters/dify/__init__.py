"""Dify AI Workflow adapter.

Replaces the hardcoded prompt templates in core/classify.py with
Dify's visual workflow engine. Once deployed:

1. Create a Dify workflow that:
   - Receives: {industry, comments[], categories[]}
   - Outputs: [{index, is_target, confidence, category, question, suggested_reply_topic, evidence}]

2. Set DIFY_API_URL + DIFY_API_KEY in .env

3. Update core/classify.py classify_batch() to call dify_client.classify()
   instead of the inline LLM batch loop.
"""
