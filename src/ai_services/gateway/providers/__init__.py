"""Provider adapters.

Two LiteLLM defaults are switched off before any adapter module can import it:

- DEV mode loads a `.env` file from the working directory into `os.environ` on first import,
  which would override the service's own settings. PRODUCTION mode skips that.
- By default LiteLLM may download its model map (limits, supported parameters) at startup. The
  local copy that ships with the pinned package version is used instead, so startup needs no
  network and behaves the same everywhere (constitution VII).
"""

import os

os.environ.setdefault("LITELLM_MODE", "PRODUCTION")
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
