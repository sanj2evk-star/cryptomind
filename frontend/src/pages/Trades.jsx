import { useApi } from "../hooks/useApi";
import { Loading, ErrorBox, EmptyState } from "../components/StatusMessage";
import TradesTable from "../components/TradesTable";
import TradeScatter from "../components/TradeScatter";
import CumulativePnl from "../components/CumulativePnl";

export default function Trades() {
  const { data, loading, error, retry } = useApi("/trades?limit=50", 30000);

  // 1. Loading state
  if (loading) return <><h1>Trade History</h1><Loading message="Loading trades..." /></>;

  // 2. Error state
  if (error) {
    return (
      <>
        <h1>Trade History</h1>
        <ErrorBox message={error} onRetry={retry} />
      </>
    );
  }

  const trades = data?.trades || [];

  // 3. Empty state
  if (trades.length === 0) {
    return (
      <>
        <h1>Trade History</h1>
        <EmptyState
          title="No trades yet"
          message="Run a trading cycle to see data here."
        />
      </>
    );
  }

  // 4. Success state
  return (
    <>
      <h1>Trade History</h1>
      <p style={{ color: "var(--text-muted)", marginBottom: 16 }}>
        Last {data?.count || trades.length} trades
      </p>

      <TradeScatter trades={trades} />
      <CumulativePnl trades={trades} />
      <TradesTable trades={trades} />
    </>
  );
}
