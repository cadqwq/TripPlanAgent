"""启动脚本"""
import sys
import os

# ===== 修复 Windows GBK 编码问题 =====
# 补丁：让 print 不因 HelloAgents 内部 emoji 而崩溃
import builtins as _bi
_real_print = _bi.print
def _safe_print(*args, **kw):
    try:
        _real_print(*args, **kw)
    except (UnicodeEncodeError, UnicodeDecodeError):
        try:
            _real_print(*(str(a).encode('ascii', errors='replace').decode('ascii') for a in args), **kw)
        except Exception:
            pass
_bi.print = _safe_print
# =====

import uvicorn
from app.config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "app.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        log_level=settings.log_level.lower()
    )
