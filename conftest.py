"""Root pytest 설정 (계약 v2).

- 워크스페이스 루트와 backend/ 를 import 경로에 추가.
- Hypothesis 프로파일 등록.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_BACKEND = _ROOT / "backend"
for p in (str(_ROOT), str(_BACKEND)):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from hypothesis import HealthCheck, settings

    settings.register_profile("default", deadline=None, suppress_health_check=[HealthCheck.too_slow])
    settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))
except ImportError:  # pragma: no cover
    pass
