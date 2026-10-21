"""Provider adapters.

LiteLLM's default DEV mode loads a `.env` file from the working directory into `os.environ` the
first time it is imported, which would override the service's own settings. PRODUCTION mode skips
that, so it is set here, before any adapter module can import LiteLLM.
"""

import os

os.environ.setdefault("LITELLM_MODE", "PRODUCTION")
