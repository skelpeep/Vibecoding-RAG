"""Independent periodic miner and transactional cache invalidation consumer."""
import time
from sqlalchemy import select

from atguigu.business import models as m
from atguigu.business.chat_service import session_factory
from atguigu.business.faq_cache import consume_outbox
from atguigu.business.security import load_principal
from atguigu.business.settlement_service import mine
from atguigu.config.config import SettlementConfig


def run_worker(once=False):
    while True:
        try:
            with session_factory() as db:
                consume_outbox(db)
                # Each miner sees only its own current knowledge grants. No superuser bypass.
                for user in db.scalars(select(m.User).where(m.User.status == "active")).all():
                    principal = load_principal(db, user)
                    if {"settlement:faq:review", "settlement:gap:manage"}.issubset(principal.permissions):
                        result = mine(db, principal)
                        db.commit()
                        print({"settlement": result}, flush=True)
        except Exception as exc:
            # Never print provider exceptions/URLs which may carry credentials.
            print({"settlement": "retry_next_interval", "error_type": type(exc).__name__}, flush=True)
        if once:
            return
        time.sleep(SettlementConfig.interval)
