"""GET /api/dashboard/overview — the numbers for the top-level summary cards."""
from datetime import datetime

from fastapi import APIRouter, Depends

import database as db
import paper_trading
from api.auth import require_token
from api.schemas import OverviewResponse

router = APIRouter(prefix="/api/dashboard", tags=["overview"])


@router.get("/overview", response_model=OverviewResponse, dependencies=[Depends(require_token)])
async def overview():
    today = db.get_todays_stats()
    all_time = db.get_alltime_stats()
    active = db.get_active_trades()
    pending = db.get_pending_trades()

    wins = all_time.get("wins", 0)
    losses = all_time.get("losses", 0)
    win_rate = wins / (wins + losses) if (wins + losses) > 0 else None

    gross_profit = all_time.get("gross_profit", 0) or 0
    gross_loss = all_time.get("gross_loss", 0) or 0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

    unrealized_pnl = 0.0
    capital_deployed = 0.0
    for t in active:
        ltp = t.get("current_ltp") or t.get("entry_price") or t["entry_trigger"]
        try:
            unrealized_pnl += paper_trading.calculate_pnl(t, ltp)
        except Exception:
            pass
        entry = t.get("entry_price") or t["entry_trigger"]
        capital_deployed += entry * t["quantity"] * t["lot_size"]

    realized_pnl = all_time.get("realized_pnl", 0) or 0
    total_charges = all_time.get("total_charges", 0) or 0

    return {
        "today": {
            "total_trades": today.get("total", 0),
            "wins": today.get("wins", 0),
            "losses": today.get("losses", 0),
            "realized_pnl": today.get("total_pnl", 0) or 0,
        },
        "all_time": {
            "total_trades": all_time.get("total", 0),
            "wins": wins,
            "losses": losses,
            "realized_pnl": realized_pnl,
        },
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "net_pnl": realized_pnl - total_charges,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "active_positions": len(active),
        "pending_signals": len(pending),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "capital_deployed": round(capital_deployed, 2),
        "as_of": datetime.now().isoformat(timespec="seconds"),
    }
